from rest_framework import serializers
from .models import Fichier


class FichierSerializer(serializers.ModelSerializer):
    # Liste des destinataires — visible uniquement par le propriétaire.
    partages = serializers.SerializerMethodField()

    class Meta:
        model = Fichier
        fields = [
            'id', 'nom', 'type', 'taille_fichier',
            'date_upload', 'fichier_type_mime', 'proprietaire', 'partages',
        ]

    def get_partages(self, obj) -> list[str]:
        request = self.context.get('request')
        if request and obj.proprietaire == request.user.email:
            return [p.destinataire for p in obj.partages.all()]
        return []
