from django.conf import settings
from rest_framework import serializers
from .models import Dossier, Fichier


class FichierSerializer(serializers.ModelSerializer):
    # Liste des destinataires — visible uniquement par le propriétaire.
    partages = serializers.SerializerMethodField()
    # URL storage complète, directement appelable par le frontend avec le
    # token de l'utilisateur courant (Authorization: Bearer) — plus de proxy
    # de lecture via ce backend. Sûr uniquement parce que chaque Fichier a son
    # propre Share storage (storage_namespace) dont les ShareMember sont
    # synchronisés sur le propriétaire + les destinataires de Partage (cf.
    # api/views.py) : storage refait lui-même le contrôle d'accès à cette URL,
    # il n'a jamais besoin de faire confiance à ce backend pour la lecture.
    fichier_url = serializers.SerializerMethodField()
    # Dossier du fichier ({id, nom} ou null) — comme `partages`, visible du
    # seul propriétaire : le destinataire d'un partage n'a pas à connaître
    # l'organisation de l'espace d'autrui. Masqué par défaut sans `request`.
    dossier = serializers.SerializerMethodField()

    class Meta:
        model = Fichier
        fields = [
            'id', 'nom', 'type', 'taille_fichier', 'date_upload',
            'fichier_type_mime', 'proprietaire', 'partages', 'fichier_url', 'dossier',
        ]

    def get_dossier(self, obj) -> dict | None:
        request = self.context.get('request')
        if not obj.dossier_id or not request or obj.proprietaire != request.user.email:
            return None
        return {'id': obj.dossier_id, 'nom': obj.dossier.nom}

    def get_partages(self, obj) -> list[str]:
        request = self.context.get('request')
        if request and obj.proprietaire == request.user.email:
            return [p.destinataire for p in obj.partages.all()]
        return []

    def get_fichier_url(self, obj) -> str | None:
        if not obj.storage_namespace or not obj.fichier_path:
            return None
        return (
            f'{settings.STORAGE_PUBLIC_BASE_URL}/api/files/'
            f'{obj.storage_namespace}/content/{obj.fichier_path}'
        )


class DossierSerializer(serializers.ModelSerializer):
    nb_fichiers = serializers.IntegerField(read_only=True, default=0)

    class Meta:
        model = Dossier
        fields = ['id', 'nom', 'date_creation', 'nb_fichiers']
