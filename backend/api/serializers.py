from rest_framework import serializers
from .models import Utilisateur, Tag, Fichier, Action, Modification, FichierWorkspace


class TagSerializer(serializers.ModelSerializer):
    class Meta:
        model = Tag
        fields = ['id', 'nom']


class ActionSerializer(serializers.ModelSerializer):
    class Meta:
        model = Action
        fields = ['id', 'nom', 'description', 'type_fichier', 'parametres_schema']


class ModificationSerializer(serializers.ModelSerializer):
    utilisateur = serializers.SerializerMethodField()

    class Meta:
        model = Modification
        fields = ['id', 'date', 'action', 'details', 'utilisateur']

    def get_utilisateur(self, obj):
        return obj.utilisateur.email if obj.utilisateur else None


class FichierListSerializer(serializers.ModelSerializer):
    tags = serializers.StringRelatedField(many=True)
    utilisateur = serializers.SerializerMethodField()

    class Meta:
        model = Fichier
        fields = ['id', 'nom', 'type', 'tags', 'date_upload', 'metadonnees',
                  'taille_fichier', 'fichier_type_mime', 'droits_acces', 'utilisateur']

    def get_utilisateur(self, obj):
        return obj.utilisateur.email if obj.utilisateur else None


class FichierDetailSerializer(serializers.ModelSerializer):
    tags = serializers.StringRelatedField(many=True)
    utilisateur = serializers.SerializerMethodField()

    class Meta:
        model = Fichier
        fields = ['id', 'nom', 'type', 'tags', 'metadonnees', 'taille_fichier',
                  'date_upload', 'droits_acces', 'fichier_type_mime', 'utilisateur']

    def get_utilisateur(self, obj):
        return obj.utilisateur.email if obj.utilisateur else None


class FichierWorkspaceSerializer(serializers.ModelSerializer):
    tags_temporaires = serializers.StringRelatedField(many=True)
    fichier_id = serializers.IntegerField(
        source='fichier_source.id', read_only=True, allow_null=True
    )

    class Meta:
        model = FichierWorkspace
        fields = ['id', 'fichier_temporaire_id', 'etat', 'nom_temporaire',
                  'historique_local', 'tags_temporaires', 'fichier_id']
