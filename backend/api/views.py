import re
from uuid import uuid4

from django.conf import settings
from django.http import Http404
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Fichier, Partage
from .serializers import FichierSerializer
from . import storage_client


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
