import base64
import logging
import re
from uuid import uuid4

import requests

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Fichier, OcrKeyVault, Partage
from .serializers import FichierSerializer
from . import storage_client

log = logging.getLogger(__name__)


class StandardPagination(PageNumberPagination):
    page_size = 12
    page_size_query_param = 'page_size'


def _type_depuis_mime(mime: str) -> str:
    if mime == 'application/pdf':
        return 'PDF'
    if mime.startswith('image/'):
        return 'Image'
    if mime.startswith('video/'):
        return 'Video'
    if mime.startswith('audio/'):
        return 'Audio'
    return 'PDF'


def _safe_name(nom: str) -> str:
    """Nom de fichier sûr pour un segment de chemin storage : ni '/', ni segment
    vide, ni '.'/'..' (cf. storage/backend/api/validators.py). Le nom d'origine
    reste intact dans Fichier.nom — c'est lui qui est renvoyé au navigateur."""
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', (nom or '').strip()) or 'fichier'
    return cleaned.strip('.') or 'fichier'


_EMAIL_RE = re.compile(r'[^@\s/\\%]+@[^@\s/\\%]+')


def _email_valide(email: str) -> bool:
    """Forme d'adresse, sans rien qui puisse changer un chemin d'URL : cette
    valeur devient un segment de l'URL de storage (storage_client.remove_member)."""
    return bool(_EMAIL_RE.fullmatch(email)) and '..' not in email


def _owned(request, pk) -> Fichier:
    """Le fichier s'il m'appartient, sinon 404."""
    return get_object_or_404(Fichier, pk=pk, proprietaire=request.user.email)


def _accessible(request, pk) -> Fichier:
    """Le fichier si je le possède OU s'il m'est partagé, sinon 404."""
    fichier = get_object_or_404(Fichier, pk=pk)
    email = (request.user.email or '').lower()
    if fichier.proprietaire == request.user.email:
        return fichier
    if fichier.partages.filter(destinataire=email).exists():
        return fichier
    raise Http404


class FichiersView(APIView):
    """GET : mes fichiers. POST : upload d'un fichier qui m'appartient."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        qs = Fichier.objects.filter(proprietaire=request.user.email).prefetch_related('partages')
        type_filter = request.query_params.get('type')
        if type_filter:
            qs = qs.filter(type=type_filter)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        data = FichierSerializer(page, many=True, context={'request': request}).data
        return paginator.get_paginated_response(data)

    def post(self, request):
        fichier_file = request.FILES.get('fichier')
        if not fichier_file:
            return Response({'error': 'Le champ fichier est requis.'}, status=400)

        if fichier_file.size > settings.MAX_FICHIER_OCTETS:
            limite_mo = settings.MAX_FICHIER_OCTETS / (1024 * 1024)
            return Response(
                {'error': f'Fichier trop volumineux (limite {limite_mo:.0f} Mo).'},
                status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        mime = fichier_file.content_type or 'application/octet-stream'
        type_ = request.data.get('type') or _type_depuis_mime(mime)
        if type_ not in dict(Fichier.TYPE_CHOICES):
            type_ = _type_depuis_mime(mime)

        nom = request.data.get('nom') or fichier_file.name
        # Bornes des colonnes vérifiées AVANT de déposer les octets : un INSERT
        # refusé après coup laisserait un Share orphelin dans storage.
        if len(nom) > Fichier._meta.get_field('nom').max_length:
            return Response({'error': 'Nom de fichier trop long (200 caractères au plus).'}, status=400)
        if len(mime) > Fichier._meta.get_field('fichier_type_mime').max_length:
            return Response({'error': 'Type de contenu invalide.'}, status=400)
        taille = fichier_file.size
        safe_name = _safe_name(nom)
        # Un Share storage PAR fichier (pas un global) : c'est ce qui permettra
        # au propriétaire de le lire en direct (cf. FichierSerializer) sans
        # donner accès à ses autres fichiers — voir api/storage_client.py pour
        # le raisonnement complet. Le nom est unique et n'a pas besoin d'exister
        # au préalable : storage le crée au premier upload (write_prefix).
        namespace = f'{settings.STORAGE_NAMESPACE_PREFIX}{uuid4().hex}'
        # Les octets partent vers storage AVANT la création de la ligne : une
        # ligne sans fichier serait un fichier fantôme dans la liste de
        # l'utilisateur, alors qu'un blob sans ligne n'est qu'un orphelin
        # invisible (repérable par son namespace, et rien ne le sert).
        try:
            result = storage_client.upload_to(namespace, safe_name, fichier_file, safe_name, mime)
        except storage_client.StorageClientError as exc:
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)

        # Le propriétaire doit lui-même être ShareMember : le Share vient d'être
        # créé avec pour owner_username le COMPTE DE SERVICE (auto-création
        # storage via write_prefix), pas l'utilisateur humain — sans cette
        # ligne, même le propriétaire ne pourrait pas lire son fichier en direct.
        try:
            storage_client.add_member(namespace, request.user.email, role='read')
        except storage_client.StorageClientError as exc:
            # Le blob existe mais personne ne pourrait le lire en direct : on
            # annule plutôt que de laisser un fichier fantôme inaccessible.
            try:
                storage_client.delete_share(namespace)
            except storage_client.StorageClientError:
                pass
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)

        fichier = Fichier.objects.create(
            nom=nom,
            type=type_,
            taille_fichier=round(taille / (1024 * 1024), 3),
            fichier_path=result['relative_path'],
            storage_namespace=namespace,
            fichier_type_mime=mime,
            proprietaire=request.user.email,
        )
        return Response(FichierSerializer(fichier, context={'request': request}).data, status=201)


class PartagesAvecMoiView(APIView):
    """GET : fichiers que d'autres ont partagés avec moi."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        email = (request.user.email or '').lower()
        qs = (
            Fichier.objects
            .filter(partages__destinataire=email)
            .distinct()
            .prefetch_related('partages')
        )
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        data = FichierSerializer(page, many=True, context={'request': request}).data
        return paginator.get_paginated_response(data)


class FichierDetailView(APIView):
    """GET : détail (propriétaire ou destinataire). DELETE : propriétaire uniquement."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        fichier = _accessible(request, pk)
        return Response(FichierSerializer(fichier, context={'request': request}).data)

    def delete(self, request, pk):
        fichier = _owned(request, pk)
        namespace = fichier.storage_namespace
        fichier.delete()
        # Purge après coup : si storage refusait la suppression, mieux vaut un
        # Share orphelin (inaccessible depuis l'app, ses ShareMember ne sont
        # plus jamais mis à jour) qu'une ligne conservée alors que l'utilisateur
        # a demandé la suppression (et que les partages ont déjà disparu en
        # cascade). Le Share étant dédié à ce seul fichier, le supprimer en
        # entier (plutôt qu'un simple delete de contenu) purge aussi ses
        # ShareMember d'un coup — rien à faire membre par membre.
        if namespace:
            try:
                storage_client.delete_share(namespace)
            except storage_client.StorageClientError:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class FichierPartagesView(APIView):
    """POST : partager mon fichier avec un email. DELETE : retirer un partage.

    Chaque changement est répliqué en ShareMember côté storage — c'est ce qui
    rend l'accès direct navigateur → storage (FichierSerializer.fichier_url)
    sûr pour un destinataire : storage refait le contrôle d'accès lui-même à
    chaque requête, il ne fait confiance à ce backend qu'au moment où celui-ci
    modifie la liste des membres.
    """

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        fichier = _owned(request, pk)
        email = (request.data.get('email') or '').strip().lower()
        if not _email_valide(email):
            return Response({'error': 'Adresse email invalide.'}, status=400)
        if email == (request.user.email or '').lower():
            return Response({'error': 'Vous êtes déjà propriétaire de ce fichier.'}, status=400)
        if not fichier.storage_namespace:
            return Response({'error': 'Ce fichier ne peut pas être partagé (stockage incomplet).'},
                            status=status.HTTP_409_CONFLICT)
        # Storage AVANT la ligne Partage : un ShareMember sans Partage ne donne
        # rien de plus que ce que l'app a déjà décidé d'accorder (juste un léger
        # retard d'enregistrement si la requête est rejouée) ; l'inverse — une
        # ligne Partage sans ShareMember — ferait croire au propriétaire que le
        # partage fonctionne alors que le destinataire n'aurait aucun accès direct.
        try:
            storage_client.add_member(fichier.storage_namespace, email, role='read')
        except storage_client.StorageClientError as exc:
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        Partage.objects.get_or_create(fichier=fichier, destinataire=email)
        return Response(FichierSerializer(fichier, context={'request': request}).data, status=201)

    def delete(self, request, pk):
        fichier = _owned(request, pk)
        email = (request.data.get('email') or request.query_params.get('email') or '').strip().lower()
        if not _email_valide(email):
            return Response({'error': 'Adresse email invalide.'}, status=400)
        # Storage AVANT la ligne Partage, dans l'autre sens qu'à la création :
        # tant que le ShareMember existe, l'accès direct reste ouvert — retirer
        # la ligne Partage en premier ferait croire au propriétaire que l'accès
        # est coupé alors qu'il resterait actif si le retrait côté storage échouait
        # ensuite. En cas d'échec ici, la ligne Partage est délibérément conservée.
        if fichier.storage_namespace and email:
            try:
                storage_client.remove_member(fichier.storage_namespace, email)
            except storage_client.StorageClientError as exc:
                return Response({'error': f'Stockage indisponible : {exc}'},
                                status=status.HTTP_502_BAD_GATEWAY)
        Partage.objects.filter(fichier=fichier, destinataire=email).delete()
        return Response(FichierSerializer(fichier, context={'request': request}).data)


# ── Coffre de la clé Mistral et OCR par le serveur (contrat « failles », I3) ──
#
# Avant : le navigateur appelait l'API Mistral lui-même, avec une clé gardée en
# localStorage (lisible par tout script de la page). Maintenant la clé est
# saisie une fois, gardée chiffrée ici (`OcrKeyVault`), jamais rendue ; c'est
# ce backend qui appelle Mistral.

_KEY_FIELD = 'mistral_key'
_KEY_MAX_LEN = 512

MISTRAL_OCR_URL = 'https://api.mistral.ai/v1/ocr'
# Délai de lecture sous le `timeout = 120` de gunicorn (gunicorn.conf.py).
MISTRAL_TIMEOUT = (10, 110)
# Types que l'opération « OCR → HTML » de l'atelier envoie (frontend,
# core/operations/ocr.ops.ts) ET que Mistral lit.
OCR_TYPES = {'application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/gif'}
# Marge pour l'enveloppe multipart (frontières, en-têtes de partie, nom).
_MULTIPART_MARGE = 64 * 1024


def cle_ocr_du_coffre(email: str) -> str:
    """La clé Mistral du compte `email`, '' si elle n'est pas configurée
    (ou ne se déchiffre pas : `EncryptedTextField` la rend alors vide)."""
    if not email:
        return ''
    coffre = OcrKeyVault.objects.filter(owner_email=email).first()
    return (coffre.mistral_key or '') if coffre else ''


class OcrKeyView(APIView):
    """GET /api/ocr-key/ → {"mistral_key_configured": bool} — jamais la valeur,
    ni un extrait.
    PUT /api/ocr-key/ {"mistral_key": "…"} → 204 ; chaîne vide ⇒ supprimée."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response({f'{_KEY_FIELD}_configured': bool(cle_ocr_du_coffre(request.user.email))})

    def put(self, request):
        donnees = request.data if isinstance(request.data, dict) else None
        if not donnees:
            return Response({'error': 'Corps attendu : {"mistral_key": "…"}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        inconnus = sorted(set(donnees) - {_KEY_FIELD})
        if inconnus:
            return Response({'error': f'Champ(s) inconnu(s) : {", ".join(inconnus)}.'},
                            status=status.HTTP_400_BAD_REQUEST)
        valeur = donnees[_KEY_FIELD]
        if not isinstance(valeur, str):
            return Response({'error': f'{_KEY_FIELD} : une chaîne est attendue.'},
                            status=status.HTTP_400_BAD_REQUEST)
        valeur = valeur.strip()
        if len(valeur) > _KEY_MAX_LEN or any(c.isspace() or not c.isprintable() for c in valeur):
            return Response({'error': f'{_KEY_FIELD} : clé mal formée.'},
                            status=status.HTTP_400_BAD_REQUEST)
        if not request.user.email:
            return Response({'error': 'Compte sans adresse email.'}, status=status.HTTP_400_BAD_REQUEST)
        if valeur:
            OcrKeyVault.objects.update_or_create(owner_email=request.user.email,
                                                 defaults={_KEY_FIELD: valeur})
        else:
            OcrKeyVault.objects.filter(owner_email=request.user.email).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


def _pages_filtrees(data) -> list[dict]:
    """Seulement `pages[].markdown` et `pages[].images[].{id, image_base64}` :
    rien d'autre de la réponse du fournisseur n'est rendu au navigateur."""
    pages = data.get('pages') if isinstance(data, dict) else None
    sortie = []
    for page in pages if isinstance(pages, list) else []:
        if not isinstance(page, dict):
            continue
        images = []
        for img in page.get('images') or []:
            if isinstance(img, dict) and isinstance(img.get('id'), str) \
                    and isinstance(img.get('image_base64'), str):
                images.append({'id': img['id'], 'image_base64': img['image_base64']})
        markdown = page.get('markdown')
        sortie.append({'markdown': markdown if isinstance(markdown, str) else '', 'images': images})
    return sortie


class OcrView(APIView):
    """POST /api/ocr/ (multipart, champ `file`) → {"pages": [{"markdown", "images"}]}.

    La clé est celle du coffre de l'utilisateur connecté (`/api/ocr-key/`) ;
    le navigateur n'envoie jamais de clé."""

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser]

    def post(self, request):
        limite = settings.OCR_MAX_OCTETS
        trop_gros = Response(
            {'error': f'Document trop volumineux pour l\'OCR (limite {limite / (1024 * 1024):.0f} Mo).'},
            status=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)
        # Refus AVANT de lire le corps.
        try:
            annonce = int(request.META.get('CONTENT_LENGTH') or 0)
        except ValueError:
            annonce = 0
        if annonce > limite + _MULTIPART_MARGE:
            return trop_gros

        cle = cle_ocr_du_coffre(request.user.email)
        if not cle:
            return Response({'error': 'Clé API Mistral non configurée.', 'code': 'key_not_configured'},
                            status=status.HTTP_400_BAD_REQUEST)

        document = request.FILES.get('file')
        if not document:
            return Response({'error': 'Le champ file est requis.'}, status=status.HTTP_400_BAD_REQUEST)
        mime = (document.content_type or '').lower()
        if mime not in OCR_TYPES:
            return Response({'error': 'Type de document non pris en charge (PDF, PNG, JPEG, WebP, GIF).'},
                            status=status.HTTP_400_BAD_REQUEST)
        if document.size > limite:
            return trop_gros

        uri = f'data:{mime};base64,{base64.b64encode(document.read()).decode()}'
        doc = ({'type': 'document_url', 'document_url': uri} if mime == 'application/pdf'
               else {'type': 'image_url', 'image_url': uri})
        try:
            resp = requests.post(
                MISTRAL_OCR_URL,
                headers={'Authorization': f'Bearer {cle}', 'Content-Type': 'application/json'},
                json={'model': 'mistral-ocr-latest', 'document': doc, 'include_image_base64': True},
                timeout=MISTRAL_TIMEOUT,
            )
        except requests.Timeout:
            log.warning('OCR : délai dépassé en attendant Mistral.')
            return Response({'error': 'Mistral n\'a pas répondu à temps. Réessayez.'},
                            status=status.HTTP_504_GATEWAY_TIMEOUT)
        except requests.RequestException as exc:
            log.warning('OCR : Mistral injoignable (%s).', type(exc).__name__)
            return self._echec()

        if resp.status_code in (401, 403):
            log.info('OCR : clé refusée par Mistral (%s).', resp.status_code)
            return Response({'error': 'Clé API Mistral refusée (invalide ou expirée).', 'code': 'key_rejected'},
                            status=status.HTTP_502_BAD_GATEWAY)
        if not resp.ok:
            log.warning('OCR : Mistral a répondu %s.', resp.status_code)
            return self._echec()
        try:
            data = resp.json()
        except ValueError:
            log.warning('OCR : réponse de Mistral illisible.')
            return self._echec()
        return Response({'pages': _pages_filtrees(data)})

    @staticmethod
    def _echec():
        # Message générique : ni le corps ni le texte d'exception du fournisseur.
        return Response({'error': 'L\'appel à l\'OCR Mistral a échoué. Réessayez plus tard.'},
                        status=status.HTTP_502_BAD_GATEWAY)
