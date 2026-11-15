import base64
import io
import logging
import re
from uuid import uuid4

import requests

from django.conf import settings
from django.db import transaction
from django.db.models import Count
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Dossier, Fichier, OcrKeyVault, Partage
from .serializers import DossierSerializer, FichierSerializer
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


def chemin_libre(namespace: str, nom_sur: str, exclude_pk=None) -> str:
    """Chemin lisible et libre dans le partage d'un Dossier : `nom_sur`, ou
    `<nom>-2.<ext>`, `-3`… s'il est déjà pris par un autre fichier de ce
    partage (storage écraserait le contenu au même chemin). Déterministe pour
    un même état de la base : la commande de migration en dépend pour être
    rejouable sans doublon."""
    pris = set(
        Fichier.objects.filter(storage_namespace=namespace)
        .exclude(pk=exclude_pk).values_list('fichier_path', flat=True)
    )
    if nom_sur not in pris:
        return nom_sur
    stem, point, ext = nom_sur.rpartition('.')
    if not point or not stem:
        stem, ext = nom_sur, ''
    n = 2
    while True:
        candidat = f'{stem}-{n}.{ext}' if ext else f'{stem}-{n}'
        if candidat not in pris:
            return candidat
        n += 1


def _purger(namespace: str, relative_path: str, dans_dossier: bool) -> None:
    """Purge storage d'un Fichier déjà supprimé en base, au mieux : seul dans
    son partage → le partage ; dans le partage de son dossier → son contenu."""
    if not namespace:
        return
    try:
        if dans_dossier:
            storage_client.delete_file(namespace, relative_path)
        else:
            storage_client.delete_share(namespace)
    except storage_client.StorageClientError:
        log.warning('storage : purge d\'un fichier supprimé impossible (orphelin laissé).')


def _sortir_du_dossier(fichier: Fichier) -> None:
    """Déplace un fichier du partage de son dossier vers un partage à lui,
    enfant de celui du dossier (avant de le partager : un destinataire n'est
    jamais membre du partage du dossier). Le fichier reste dans le Dossier.
    Lève StorageClientError ; rien n'a alors changé en base."""
    ancien = fichier.storage_namespace
    chemin = fichier.fichier_path
    nouveau = f'{settings.STORAGE_NAMESPACE_PREFIX}{uuid4().hex}'
    storage_client.create_share(nouveau, parent=ancien)
    try:
        resp = storage_client.download_from(ancien, chemin)
        try:
            octets = b''.join(resp.iter_content(65536))
        finally:
            resp.close()
        result = storage_client.upload_to(
            nouveau, chemin, io.BytesIO(octets), chemin.rsplit('/', 1)[-1],
            fichier.fichier_type_mime or 'application/octet-stream',
        )
        if int(result.get('size', -1)) != len(octets):
            raise storage_client.StorageClientError('Taille déposée inattendue.')
        storage_client.add_member(nouveau, fichier.proprietaire, role='read')
    except storage_client.StorageClientError:
        try:
            storage_client.delete_share(nouveau)
        except storage_client.StorageClientError:
            pass
        raise
    fichier.storage_namespace = nouveau
    fichier.fichier_path = result['relative_path']
    fichier.save(update_fields=['storage_namespace', 'fichier_path'])
    try:
        storage_client.delete_file(ancien, chemin)
    except storage_client.StorageClientError:
        # Copie restée dans le partage du dossier : lisible du seul
        # propriétaire, écrasée par un dépôt ultérieur au même nom.
        log.warning('storage : ancienne copie laissée dans le partage du dossier.')


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
        qs = (Fichier.objects.filter(proprietaire=request.user.email)
              .select_related('dossier').prefetch_related('partages'))
        type_filter = request.query_params.get('type')
        if type_filter:
            qs = qs.filter(type=type_filter)
        # ?dossier=<id> : les fichiers de ce dossier ; ?dossier=aucun : hors dossier.
        dossier_filter = request.query_params.get('dossier')
        if dossier_filter == 'aucun':
            qs = qs.filter(dossier__isnull=True)
        elif dossier_filter:
            if not dossier_filter.isdigit():
                return Response({'error': 'Dossier invalide.'}, status=400)
            qs = qs.filter(dossier_id=int(dossier_filter))
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

        # Dossier facultatif : un dossier DONT JE SUIS PROPRIÉTAIRE, jamais
        # celui d'un autre (404, même réponse qu'un dossier inexistant).
        dossier = None
        dossier_id = request.data.get('dossier')
        if dossier_id not in (None, ''):
            if not str(dossier_id).isdigit():
                return Response({'error': 'Dossier invalide.'}, status=400)
            if not request.user.email:
                return Response({'error': 'Dossier introuvable.'}, status=404)
            dossier = Dossier.objects.filter(pk=int(dossier_id), proprietaire=request.user.email).first()
            if dossier is None:
                return Response({'error': 'Dossier introuvable.'}, status=404)

        if dossier is not None:
            return self._deposer_dans_dossier(request, dossier, fichier_file, nom, type_, mime,
                                              taille, safe_name)

        # Fichier isolé : un Share storage PAR fichier (pas un global) : c'est
        # ce qui permet au propriétaire de le lire en direct (cf.
        # FichierSerializer) sans donner accès à ses autres fichiers — voir
        # api/storage_client.py. Le partage est créé explicitement, rattaché au
        # conteneur de l'app (contrat I1), AVANT l'upload.
        namespace = f'{settings.STORAGE_NAMESPACE_PREFIX}{uuid4().hex}'
        try:
            storage_client.create_share(namespace)
        except storage_client.StorageClientError as exc:
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        # Les octets partent vers storage AVANT la création de la ligne : une
        # ligne sans fichier serait un fichier fantôme dans la liste de
        # l'utilisateur, alors qu'un blob sans ligne n'est qu'un orphelin
        # invisible (repérable par son namespace, et rien ne le sert).
        try:
            result = storage_client.upload_to(namespace, safe_name, fichier_file, safe_name, mime)
        except storage_client.StorageClientError as exc:
            try:
                storage_client.delete_share(namespace)
            except storage_client.StorageClientError:
                pass
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

    def _deposer_dans_dossier(self, request, dossier, fichier_file, nom, type_, mime, taille, safe_name):
        """Dépôt direct dans le partage du dossier (son propriétaire y est déjà
        membre), sous un nom lisible et libre dans ce dossier.

        Le chemin est RÉSERVÉ par la ligne, créée sous verrou du dossier avant
        l'envoi : deux dépôts simultanés du même nom (l'atelier envoie en
        parallèle) n'écrivent jamais au même chemin. Le verrou n'est tenu que le
        temps du choix du nom, pas pendant l'envoi. En cas d'échec de l'envoi,
        la ligne est retirée."""
        with transaction.atomic():
            Dossier.objects.select_for_update().get(pk=dossier.pk)
            chemin = chemin_libre(dossier.storage_namespace, safe_name)
            fichier = Fichier.objects.create(
                nom=nom,
                type=type_,
                taille_fichier=round(taille / (1024 * 1024), 3),
                fichier_path=chemin,
                storage_namespace=dossier.storage_namespace,
                fichier_type_mime=mime,
                proprietaire=request.user.email,
                dossier=dossier,
            )
        try:
            storage_client.upload_to(dossier.storage_namespace, chemin, fichier_file, safe_name, mime)
        except storage_client.StorageClientError as exc:
            fichier.delete()
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        return Response(FichierSerializer(fichier, context={'request': request}).data, status=201)


class DossiersView(APIView):
    """GET : mes dossiers. POST {nom} : crée un dossier et son partage storage
    (rattaché au conteneur de l'app, contrat I1/I2)."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        qs = Dossier.objects.filter(proprietaire=request.user.email).annotate(nb_fichiers=Count('fichiers'))
        return Response(DossierSerializer(qs, many=True).data)

    def post(self, request):
        nom = request.data.get('nom')
        nom = nom.strip() if isinstance(nom, str) else ''
        if not nom:
            return Response({'error': 'Le nom du dossier est requis.'}, status=400)
        if len(nom) > Dossier._meta.get_field('nom').max_length:
            return Response({'error': 'Nom de dossier trop long (200 caractères au plus).'}, status=400)
        if not request.user.email:
            return Response({'error': 'Compte sans adresse email.'}, status=400)
        namespace = f'{settings.STORAGE_NAMESPACE_PREFIX}d-{uuid4().hex}'
        try:
            storage_client.create_share(namespace)
        except storage_client.StorageClientError as exc:
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        try:
            storage_client.add_member(namespace, request.user.email, role='read')
        except storage_client.StorageClientError as exc:
            try:
                storage_client.delete_share(namespace)
            except storage_client.StorageClientError:
                pass
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        dossier = Dossier.objects.create(nom=nom, proprietaire=request.user.email,
                                         storage_namespace=namespace)
        dossier.nb_fichiers = 0
        return Response(DossierSerializer(dossier).data, status=201)


class DossierDetailView(APIView):
    """DELETE : supprime mes fichiers de ce dossier (octets compris), puis le
    dossier et son partage storage. Propriétaire uniquement (404 sinon)."""

    permission_classes = [IsAuthenticated]

    def delete(self, request, pk):
        if not request.user.email:
            raise Http404
        dossier = get_object_or_404(Dossier, pk=pk, proprietaire=request.user.email)
        fichiers = list(dossier.fichiers.all())
        # Partages propres des fichiers partagés du dossier : ce sont des
        # ENFANTS du partage du dossier, et storage refuse de supprimer un
        # partage qui a des enfants — ils partent donc d'abord. Les fichiers
        # restés dans le partage du dossier partent avec lui.
        enfants = [f.storage_namespace for f in fichiers
                   if f.storage_namespace and f.storage_namespace != dossier.storage_namespace]
        namespace = dossier.storage_namespace
        with transaction.atomic():
            Fichier.objects.filter(pk__in=[f.pk for f in fichiers]).delete()
            dossier.delete()
        # Purge après coup, au mieux (même choix que la suppression d'un fichier).
        for ns in enfants:
            _purger(ns, '', dans_dossier=False)
        try:
            storage_client.delete_share(namespace)
        except storage_client.StorageClientError:
            log.warning('storage : partage d\'un dossier supprimé laissé en place (orphelin).')
        return Response(status=status.HTTP_204_NO_CONTENT)


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
        chemin = fichier.fichier_path
        dans_dossier = fichier.dans_partage_du_dossier
        fichier.delete()
        # Purge après coup : si storage refusait la suppression, mieux vaut un
        # Share orphelin (inaccessible depuis l'app, ses ShareMember ne sont
        # plus jamais mis à jour) qu'une ligne conservée alors que l'utilisateur
        # a demandé la suppression (et que les partages ont déjà disparu en
        # cascade). Le Share étant dédié à ce seul fichier, le supprimer en
        # entier (plutôt qu'un simple delete de contenu) purge aussi ses
        # ShareMember d'un coup — rien à faire membre par membre. Un fichier
        # resté dans le partage de son dossier : seul son contenu part.
        _purger(namespace, chemin, dans_dossier)
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
        # Fichier encore dans le partage de son dossier : il en sort d'abord
        # (partage à lui, enfant de celui du dossier) — le destinataire ne
        # devient jamais membre du partage du dossier, il lirait tout le dossier.
        # Verrou sur la ligne : deux partages simultanés ne le déplacent qu'une fois.
        if fichier.dossier_id:
            with transaction.atomic():
                fichier = Fichier.objects.select_for_update(of=('self',)).select_related('dossier').get(pk=fichier.pk)
                if fichier.dans_partage_du_dossier:
                    try:
                        _sortir_du_dossier(fichier)
                    except storage_client.StorageClientError as exc:
                        return Response({'error': f'Stockage indisponible : {exc}'},
                                        status=status.HTTP_502_BAD_GATEWAY)
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
