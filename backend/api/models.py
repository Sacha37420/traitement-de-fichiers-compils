from django.db import models


class Utilisateur(models.Model):
    email = models.CharField(max_length=255, unique=True)
    date_inscription = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'utilisateurs'
        ordering = ['email']

    def __str__(self):
        return self.email


class Tag(models.Model):
    nom = models.CharField(max_length=50, unique=True)

    class Meta:
        db_table = 'tags'
        ordering = ['nom']

    def __str__(self):
        return self.nom


class Fichier(models.Model):
    TYPE_CHOICES = [('Image', 'Image'), ('Video', 'Video'), ('Audio', 'Audio'), ('PDF', 'PDF')]
    DROITS_CHOICES = [('public', 'public'), ('privé', 'privé')]

    nom = models.CharField(max_length=200)
    type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    metadonnees = models.JSONField(default=dict)
    taille_fichier = models.DecimalField(max_digits=12, decimal_places=3)
    date_upload = models.DateTimeField(auto_now_add=True)
    droits_acces = models.CharField(max_length=10, default='privé', choices=DROITS_CHOICES)
    fichier_binaire = models.BinaryField()
    fichier_type_mime = models.CharField(max_length=50)
    utilisateur = models.ForeignKey(
        Utilisateur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='fichiers',
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name='fichiers')

    class Meta:
        db_table = 'fichiers'
        ordering = ['-date_upload']

    def __str__(self):
        return self.nom


class Action(models.Model):
    TYPE_FICHIER_CHOICES = [('Image', 'Image'), ('Video', 'Video'), ('Audio', 'Audio'), ('PDF', 'PDF')]

    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    type_fichier = models.CharField(max_length=10, choices=TYPE_FICHIER_CHOICES)
    parametres_schema = models.JSONField(default=dict)

    class Meta:
        db_table = 'actions'
        ordering = ['type_fichier', 'nom']
        constraints = [
            models.UniqueConstraint(fields=['nom', 'type_fichier'], name='unique_action_nom_type'),
        ]

    def __str__(self):
        return f'{self.nom} ({self.type_fichier})'


class Modification(models.Model):
    action = models.CharField(max_length=100)
    date = models.DateTimeField(auto_now_add=True)
    details = models.JSONField(null=True, blank=True)
    fichier = models.ForeignKey(
        Fichier,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='modifications',
    )
    utilisateur = models.ForeignKey(
        Utilisateur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='modifications',
    )

    class Meta:
        db_table = 'modifications'
        ordering = ['-date']

    def __str__(self):
        return f'{self.action} ({self.fichier})'


class FichierWorkspace(models.Model):
    fichier_temporaire_id = models.CharField(max_length=100, unique=True)
    etat = models.CharField(max_length=20, default='en_cours')
    nom_temporaire = models.CharField(max_length=200, blank=True, null=True)
    historique_local = models.JSONField(null=True, blank=True, default=list)
    # Lien optionnel vers le Fichier source (ajout d'implémentation pour le finaliser)
    fichier_source = models.ForeignKey(
        Fichier,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='workspace_items',
    )
    tags_temporaires = models.ManyToManyField(Tag, blank=True, related_name='fichiers_workspace')

    class Meta:
        db_table = 'fichiers_workspace'

    def __str__(self):
        return self.fichier_temporaire_id
