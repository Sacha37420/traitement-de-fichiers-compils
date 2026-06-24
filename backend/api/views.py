import json
import uuid
from io import BytesIO

from django.core.cache import cache
from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from rest_framework import status
from rest_framework.pagination import PageNumberPagination
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Action, Fichier, FichierWorkspace, Modification, Tag, Utilisateur
from .serializers import (
    ActionSerializer,
    FichierDetailSerializer,
    FichierListSerializer,
    FichierWorkspaceSerializer,
    ModificationSerializer,
    TagSerializer,
)


# ── Helpers ────────────────────────────────────────────────────────────────────

class StandardPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = 'page_size'


def _get_or_create_utilisateur(request):
    if request.user and request.user.is_authenticated:
        utilisateur, _ = Utilisateur.objects.get_or_create(email=request.user.email)
        return utilisateur
    return None


def _parse_tags(tags_data):
    if not tags_data:
        return []
    if isinstance(tags_data, list):
        return [t.strip() for t in tags_data if t.strip()]
    if isinstance(tags_data, str):
        try:
            parsed = json.loads(tags_data)
            if isinstance(parsed, list):
                return [t.strip() for t in parsed if t.strip()]
        except json.JSONDecodeError:
            pass
        return [t.strip() for t in tags_data.split(',') if t.strip()]
    return []


def _apply_image_action(binary: bytes, action_nom: str, details: dict) -> bytes:
    try:
        from PIL import Image, ImageEnhance, ImageFilter, ImageOps
    except ImportError:
        return binary

    try:
        img = Image.open(BytesIO(binary))
        fmt = img.format or 'JPEG'

        if action_nom == 'Recadrage':
            x = int(details.get('x', 0))
            y = int(details.get('y', 0))
            w = int(details.get('largeur', img.width))
            h = int(details.get('hauteur', img.height))
            img = img.crop((x, y, x + w, y + h))

        elif action_nom == 'Redimensionnement':
            w = int(details.get('largeur', img.width))
            h = int(details.get('hauteur', img.height))
            img = img.resize((w, h), Image.LANCZOS)

        elif action_nom == 'Rotation':
            angle = float(details.get('angle', 0))
            img = img.rotate(-angle, expand=True)

        elif action_nom == 'Noir et Blanc':
            img = img.convert('L').convert('RGB')

        elif action_nom == 'Sépia':
            gray = img.convert('L')
            img = ImageOps.colorize(gray, '#704214', '#C0A882')

        elif action_nom == 'Contraste':
            niveau = float(details.get('niveau', 1.0))
            img = ImageEnhance.Contrast(img).enhance(niveau)

        elif action_nom == 'Luminosité':
            niveau = float(details.get('niveau', 1.0))
            img = ImageEnhance.Brightness(img).enhance(niveau)

        elif action_nom == 'Compression':
            qualite = int(details.get('qualite', 85))
            fmt = details.get('format', fmt) or fmt
            output = BytesIO()
            img.save(output, format=fmt, quality=qualite, optimize=True)
            return output.getvalue()

        elif action_nom == 'Conversion de format':
            fmt = details.get('format', fmt) or fmt

        output = BytesIO()
        if fmt.upper() in ('JPEG', 'JPG'):
            img = img.convert('RGB')
            img.save(output, format='JPEG', quality=90)
        else:
            img.save(output, format=fmt)
        return output.getvalue()

    except Exception:
        return binary


# ── Fichiers ───────────────────────────────────────────────────────────────────

class FichierUploadView(APIView):
    """POST /api/fichiers/ — Upload d'un fichier (binaire stocké en BDD)."""

    permission_classes = [AllowAny]
    parser_classes = [MultiPartParser, FormParser]

    def post(self, request):
        fichier_file = request.FILES.get('fichier')
        if not fichier_file:
            return Response({'error': 'Le champ fichier est requis.'}, status=400)

        nom = request.data.get('nom', fichier_file.name)
        type_ = request.data.get('type')
        if not type_:
            return Response({'error': 'Le champ type est requis.'}, status=400)

        tags_list = _parse_tags(request.data.getlist('tags') or request.data.get('tags'))

        metadonnees = request.data.get('metadonnees', '{}')
        if isinstance(metadonnees, str):
            try:
                metadonnees = json.loads(metadonnees)
            except json.JSONDecodeError:
                metadonnees = {}

        binary = fichier_file.read()
        taille_mo = round(len(binary) / (1024 * 1024), 3)

        utilisateur = _get_or_create_utilisateur(request)

        droits_acces = request.data.get('droits_acces', 'privé')
        if droits_acces not in ('public', 'privé'):
            droits_acces = 'privé'

        fichier = Fichier.objects.create(
            nom=nom,
            type=type_,
            metadonnees=metadonnees,
            taille_fichier=taille_mo,
            droits_acces=droits_acces,
            fichier_binaire=binary,
            fichier_type_mime=fichier_file.content_type or 'application/octet-stream',
            utilisateur=utilisateur,
        )

        for tag_nom in tags_list:
            tag, _ = Tag.objects.get_or_create(nom=tag_nom)
            fichier.tags.add(tag)

        return Response(FichierDetailSerializer(fichier).data, status=201)


class FichierEnregistrerView(APIView):
    """POST /api/fichiers/enregistrer/ — Enregistrement d'un fichier modifié (lié à un utilisateur)."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        nom = request.data.get('nom')
        fichier_id = request.data.get('fichier_id')
        metadonnees = request.data.get('metadonnees', {})
        tags_list = _parse_tags(request.data.get('tags'))

        utilisateur = _get_or_create_utilisateur(request)

        if fichier_id:
            fichier = get_object_or_404(Fichier, pk=fichier_id)
            fichier.nom = nom or fichier.nom
            fichier.metadonnees = metadonnees or fichier.metadonnees
            fichier.utilisateur = utilisateur
            fichier.save()
            if tags_list:
                tags_objs = []
                for tag_nom in tags_list:
                    tag, _ = Tag.objects.get_or_create(nom=tag_nom)
                    tags_objs.append(tag)
                fichier.tags.set(tags_objs)
        else:
            return Response({'error': 'fichier_id est requis.'}, status=400)

        return Response(FichierDetailSerializer(fichier).data)


class MesFichiersView(APIView):
    """GET /api/fichiers/mes-fichiers/ — Liste des fichiers de l'utilisateur."""

    permission_classes = [IsAuthenticated]

    def get(self, request):
        utilisateur = _get_or_create_utilisateur(request)
        qs = Fichier.objects.filter(utilisateur=utilisateur).prefetch_related('tags', 'utilisateur')

        type_filter = request.query_params.get('type')
        if type_filter:
            qs = qs.filter(type=type_filter)

        tag_filter = request.query_params.get('tag')
        if tag_filter:
            qs = qs.filter(tags__nom=tag_filter)

        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = FichierListSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class FichierDetailView(APIView):
    """GET /api/fichiers/{id}/ — Détail d'un fichier."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        fichier = get_object_or_404(Fichier, pk=pk)
        return Response(FichierDetailSerializer(fichier).data)


class FichierDownloadView(APIView):
    """GET /api/fichiers/{id}/download/ — Téléchargement du binaire."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        fichier = get_object_or_404(Fichier, pk=pk)
        binary = bytes(fichier.fichier_binaire)
        response = HttpResponse(binary, content_type=fichier.fichier_type_mime)
        response['Content-Disposition'] = f'attachment; filename="{fichier.nom}"'
        return response


class FichierModificationsView(APIView):
    """GET /api/fichiers/{id}/modifications/ — Historique des modifications."""

    permission_classes = [AllowAny]

    def get(self, request, pk):
        fichier = get_object_or_404(Fichier, pk=pk)
        qs = fichier.modifications.select_related('utilisateur').all()
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ModificationSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


class FichierActionsView(APIView):
    """POST /api/fichiers/{id}/actions/ — Appliquer une action sur un fichier."""

    permission_classes = [AllowAny]

    def post(self, request, pk):
        fichier = get_object_or_404(Fichier, pk=pk)
        action_nom = request.data.get('action')
        details = request.data.get('details', {})
        preview = request.data.get('preview', False)

        if not action_nom:
            return Response({'error': 'Le champ action est requis.'}, status=400)

        if fichier.type == 'Image':
            binary = bytes(fichier.fichier_binaire)
            result_binary = _apply_image_action(binary, action_nom, details or {})
        else:
            result_binary = bytes(fichier.fichier_binaire)

        if preview:
            token = str(uuid.uuid4())
            cache.set(f'preview:{token}', {
                'binary': result_binary,
                'mime': fichier.fichier_type_mime,
                'nom': fichier.nom,
            }, timeout=300)
            return Response({
                'preview_url': f'/api/preview/{token}/',
                'expires_in': 300,
            })

        fichier.fichier_binaire = result_binary
        fichier.taille_fichier = round(len(result_binary) / (1024 * 1024), 3)
        fichier.save(update_fields=['fichier_binaire', 'taille_fichier'])

        utilisateur = _get_or_create_utilisateur(request)
        modification = Modification.objects.create(
            fichier=fichier,
            utilisateur=utilisateur,
            action=action_nom,
            details=details,
        )

        return Response({
            'success': True,
            'message': f'Action "{action_nom}" appliquée avec succès.',
            'modification_id': modification.id,
        })


class PreviewDownloadView(APIView):
    """GET /api/preview/{token}/ — Télécharger une prévisualisation temporaire."""

    permission_classes = [AllowAny]

    def get(self, request, token):
        data = cache.get(f'preview:{token}')
        if not data:
            return Response({'error': 'Prévisualisation expirée ou introuvable.'}, status=404)
        response = HttpResponse(data['binary'], content_type=data['mime'])
        response['Content-Disposition'] = f'inline; filename="preview_{data["nom"]}"'
        return response


# ── Tags ───────────────────────────────────────────────────────────────────────

class TagListView(APIView):
    """GET /api/tags/ — Liste des tags."""

    permission_classes = [AllowAny]

    def get(self, request):
        qs = Tag.objects.all()
        search = request.query_params.get('search')
        if search:
            qs = qs.filter(nom__icontains=search)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = TagSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ── Actions ────────────────────────────────────────────────────────────────────

class ActionListView(APIView):
    """GET /api/actions/ — Liste des actions disponibles."""

    permission_classes = [AllowAny]

    def get(self, request):
        qs = Action.objects.all()
        type_fichier = request.query_params.get('type_fichier')
        if type_fichier:
            qs = qs.filter(type_fichier=type_fichier)
        paginator = StandardPagination()
        page = paginator.paginate_queryset(qs, request)
        serializer = ActionSerializer(page, many=True)
        return paginator.get_paginated_response(serializer.data)


# ── Workspace ──────────────────────────────────────────────────────────────────

class WorkspaceView(APIView):
    """POST /api/workspace/ — Crée ou récupère le workspace."""

    permission_classes = [IsAuthenticated]

    def post(self, request):
        fichier_id = request.data.get('fichier_id') if request.data else None

        if fichier_id:
            fichier = get_object_or_404(Fichier, pk=fichier_id)
            temp_id = str(uuid.uuid4())
            ws_item = FichierWorkspace.objects.create(
                fichier_temporaire_id=temp_id,
                etat='en_cours',
                nom_temporaire=fichier.nom,
                fichier_source=fichier,
                historique_local=[],
            )
            for tag in fichier.tags.all():
                ws_item.tags_temporaires.add(tag)

        items = FichierWorkspace.objects.filter(etat='en_cours').prefetch_related('tags_temporaires')
        return Response({
            'id': 1,
            'fichiers': FichierWorkspaceSerializer(items, many=True).data,
        })


class WorkspaceFinaliserView(APIView):
    """POST /api/workspace/{id}/finaliser/ — Enregistre un fichier modifié en BDD."""

    permission_classes = [IsAuthenticated]

    def post(self, request, pk):
        fichier_temporaire_id = request.data.get('fichier_temporaire_id')
        if not fichier_temporaire_id:
            return Response({'error': 'fichier_temporaire_id est requis.'}, status=400)

        ws_item = get_object_or_404(FichierWorkspace, fichier_temporaire_id=fichier_temporaire_id)

        nom = request.data.get('nom') or ws_item.nom_temporaire
        metadonnees = request.data.get('metadonnees', {})
        tags_list = _parse_tags(request.data.get('tags'))
        historique = request.data.get('historique', [])

        utilisateur = _get_or_create_utilisateur(request)

        if ws_item.fichier_source:
            source = ws_item.fichier_source
            binary = bytes(source.fichier_binaire)

            if source.type == 'Image':
                for entry in (historique or ws_item.historique_local or []):
                    action_nom = entry.get('action') or entry.get('nom', '')
                    details = entry.get('details', {})
                    binary = _apply_image_action(binary, action_nom, details)

            fichier = Fichier.objects.create(
                nom=nom or source.nom,
                type=source.type,
                metadonnees=metadonnees or source.metadonnees,
                taille_fichier=round(len(binary) / (1024 * 1024), 3),
                fichier_binaire=binary,
                fichier_type_mime=source.fichier_type_mime,
                utilisateur=utilisateur,
            )
        else:
            return Response({'error': 'Aucun fichier source dans le workspace.'}, status=400)

        if tags_list:
            for tag_nom in tags_list:
                tag, _ = Tag.objects.get_or_create(nom=tag_nom)
                fichier.tags.add(tag)
        else:
            for tag in ws_item.tags_temporaires.all():
                fichier.tags.add(tag)

        all_history = historique or ws_item.historique_local or []
        for entry in all_history:
            Modification.objects.create(
                fichier=fichier,
                utilisateur=utilisateur,
                action=entry.get('action') or entry.get('nom', 'Transformation'),
                details=entry.get('details'),
            )

        ws_item.etat = 'finalisé'
        ws_item.save(update_fields=['etat'])

        return Response(FichierDetailSerializer(fichier).data, status=201)
