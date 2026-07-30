from django.conf import settings
from rest_framework import serializers
from .models import Fichier


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

    class Meta:
        model = Fichier
        fields = [
            'id', 'nom', 'type', 'taille_fichier', 'date_upload',
            'fichier_type_mime', 'proprietaire', 'partages', 'fichier_url',
        ]

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
