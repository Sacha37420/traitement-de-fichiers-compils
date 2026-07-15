from rest_framework import serializers
from .models import Fichier


class FichierSerializer(serializers.ModelSerializer):
    class Meta:
        model = Fichier
        fields = [
            'id', 'nom', 'type', 'taille_fichier',
            'date_upload', 'fichier_type_mime', 'proprietaire',
        ]
        read_only_fields = fields
