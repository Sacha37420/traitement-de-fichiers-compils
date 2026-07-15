from django.conf import settings
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Fichier
from .serializers import FichierSerializer


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


class FichiersView(APIView):
    """GET : mes fichiers. POST : upload d'un fichier qui m'appartient.

    Toutes les opérations sont réservées à l'utilisateur authentifié et cloisonnées
    à ses propres fichiers (`proprietaire`). L'authentification (azp + groupes) est
    vérifiée par KeycloakJWTAuthentication.
    """

    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    def get(self, request):
        qs = Fichier.objects.filter(proprietaire=request.user.email)
        type_filter = request.query_params.get('type')
        if type_filter:
            qs = qs.filter(type=type_filter)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        return paginator.get_paginated_response(FichierSerializer(page, many=True).data)

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

        binary = fichier_file.read()
        mime = fichier_file.content_type or 'application/octet-stream'
        type_ = request.data.get('type') or _type_depuis_mime(mime)
        if type_ not in dict(Fichier.TYPE_CHOICES):
            type_ = _type_depuis_mime(mime)

        fichier = Fichier.objects.create(
            nom=request.data.get('nom') or fichier_file.name,
            type=type_,
            taille_fichier=round(len(binary) / (1024 * 1024), 3),
            fichier_binaire=binary,
            fichier_type_mime=mime,
            proprietaire=request.user.email,
        )
        return Response(FichierSerializer(fichier).data, status=201)


class FichierDetailView(APIView):
    """GET : détail d'un de mes fichiers. DELETE : suppression."""

    permission_classes = [IsAuthenticated]

    def _mine(self, request, pk) -> Fichier:
        return get_object_or_404(Fichier, pk=pk, proprietaire=request.user.email)

    def get(self, request, pk):
        return Response(FichierSerializer(self._mine(request, pk)).data)

    def delete(self, request, pk):
        self._mine(request, pk).delete()
        return Response(status=status.HTTP_204_NO_CONTENT)


class FichierDownloadView(APIView):
    """GET : binaire d'un de mes fichiers."""

    permission_classes = [IsAuthenticated]

    def get(self, request, pk):
        fichier = get_object_or_404(Fichier, pk=pk, proprietaire=request.user.email)
        response = HttpResponse(bytes(fichier.fichier_binaire), content_type=fichier.fichier_type_mime)
        response['Content-Disposition'] = f'attachment; filename="{fichier.nom}"'
        return response
