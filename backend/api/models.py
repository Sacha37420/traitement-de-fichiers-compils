from django.db import models


class Fichier(models.Model):
    """Métadonnées d'un fichier, appartenant à une personne (email Keycloak).

    Le backend ne fait plus aucun traitement : les transformations ont lieu côté
    client (atelier). Ici on ne fait que du stockage propriétaire.

    Les octets ne sont plus en base : ils vivent dans l'app storage, point
    d'entrée unique du lab pour les fichiers utilisateur (cf.
    api/storage_client.py). Cette table ne porte plus que les métadonnées et
    l'autorisation (proprietaire + Partage), que storage ne connaît pas.

    Depuis la synchronisation du modèle de partage (voir storage_namespace
    ci-dessous), storage connaît en plus une réplique de cette autorisation
    sous forme de ShareMember — c'est elle qui sécurise l'accès direct
    frontend → storage (le backend ne proxie plus la lecture, cf.
    FichierSerializer.get_fichier_url).
    """

    TYPE_CHOICES = [
        ('Image', 'Image'),
        ('Video', 'Video'),
        ('Audio', 'Audio'),
        ('PDF', 'PDF'),
    ]

    nom = models.CharField(max_length=200)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    taille_fichier = models.DecimalField(max_digits=12, decimal_places=3)  # Mo
    date_upload = models.DateTimeField(auto_now_add=True)
    # Chemin logique DANS le partage storage désigné par storage_namespace
    # (jamais un chemin sur disque).
    fichier_path = models.CharField(max_length=1024, blank=True, default='')
    # Nom du Share storage propre à CE fichier ('tdfc-<uuid hex>' — un Share par
    # fichier, pas un Share global pour toute l'app : le propriétaire et chaque
    # destinataire de Partage ont un ShareMember dessus, ce qui permet un accès
    # direct navigateur → storage sans repasser par ce backend en lecture. Voir
    # api/storage_client.py pour le choix du préfixe 'tdfc-' plutôt que le nom
    # complet de l'app (budget de 64 caractères du slug storage).
    storage_namespace = models.CharField(max_length=64, blank=True, default='')
    fichier_type_mime = models.CharField(max_length=100)
    proprietaire = models.CharField(max_length=255, db_index=True, default='')

    class Meta:
        db_table = 'fichiers'
        ordering = ['-date_upload']

    def __str__(self):
        return self.nom


class Partage(models.Model):
    """Partage d'un fichier à une personne, identifiée par son email (Keycloak)."""

    fichier = models.ForeignKey(Fichier, on_delete=models.CASCADE, related_name='partages')
    destinataire = models.CharField(max_length=255, db_index=True)  # email, en minuscules
    date_partage = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'partages'
        ordering = ['destinataire']
        constraints = [
            models.UniqueConstraint(fields=['fichier', 'destinataire'], name='unique_partage'),
        ]

    def __str__(self):
        return f'{self.fichier_id} -> {self.destinataire}'
