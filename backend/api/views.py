import re
from uuid import uuid4

from django.conf import settings
from django.http import Http404, StreamingHttpResponse
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
        taille = fichier_file.size
        # Les octets partent vers storage AVANT la création de la ligne : une
        # ligne sans fichier serait un fichier fantôme dans la liste de
        # l'utilisateur, alors qu'un blob sans ligne n'est qu'un orphelin
        # invisible (repérable par son chemin, et rien ne le sert).
        relative_path = f'fichiers/{uuid4().hex}-{_safe_name(nom)}'
        try:
            result = storage_client.upload(relative_path, fichier_file, _safe_name(nom), mime)
        except storage_client.StorageClientError as exc:
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)

        fichier = Fichier.objects.create(
            nom=nom,
            type=type_,
            taille_fichier=round(taille / (1024 * 1024), 3),
            fichier_path=result['relative_path'],
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
        fichier_path = fichier.fichier_path
        fichier.delete()
        # Purge après coup : si storage refusait la suppression, mieux vaut un
        # blob orphelin qu'une ligne conservée alors que l'utilisateur a demandé
        # la suppression (et que les partages ont déjà disparu en cascade).
        if fichier_path:
            try:
                storage_client.delete(fichier_path)
            except storage_client.StorageClientError:
                pass
        return Response(status=status.HTTP_204_NO_CONTENT)


class FichierDownloadView(APIView):
    """GET : octets du fichier (propriétaire ou destinataire).

    Proxie storage plutôt que de servir depuis la base. Le cloisonnement reste
    ici : _accessible() décide, storage ne connaît ni propriétaire ni partage
    (cf. api/storage_client.py).
    """

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        fichier = _accessible(request, pk)
        if not fichier.fichier_path:
            raise Http404
        try:
            upstream = storage_client.download(fichier.fichier_path)
        except storage_client.StorageClientError as exc:
            return Response({'error': f'Stockage indisponible : {exc}'},
                            status=status.HTTP_502_BAD_GATEWAY)
        response = StreamingHttpResponse(
            upstream.iter_content(chunk_size=65536),
            content_type=fichier.fichier_type_mime or 'application/octet-stream',
        )
        # Le nom d'origine (Fichier.nom), pas le nom assaini du chemin storage.
        response['Content-Disposition'] = f'attachment; filename="{fichier.nom}"'
        return response


class FichierPartagesView(APIView):
    """POST : partager mon fichier avec un email. DELETE : retirer un partage."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        fichier = _owned(request, pk)
        email = (request.data.get('email') or '').strip().lower()
        if not email or '@' not in email:
            return Response({'error': 'Adresse email invalide.'}, status=400)
        if email == (request.user.email or '').lower():
            return Response({'error': 'Vous êtes déjà propriétaire de ce fichier.'}, status=400)
        Partage.objects.get_or_create(fichier=fichier, destinataire=email)
        return Response(FichierSerializer(fichier, context={'request': request}).data, status=201)

    def delete(self, request, pk):
        fichier = _owned(request, pk)
        email = (request.data.get('email') or request.query_params.get('email') or '').strip().lower()
        Partage.objects.filter(fichier=fichier, destinataire=email).delete()
        return Response(FichierSerializer(fichier, context={'request': request}).data)
