from django.db import models


class Fichier(models.Model):
    """Fichier stocké en base, appartenant à une personne (email Keycloak).

    Le backend ne fait plus aucun traitement : les transformations ont lieu côté
    client (atelier). Ici on ne fait que du stockage propriétaire.
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
    fichier_binaire = models.BinaryField()
    fichier_type_mime = models.CharField(max_length=100)
    proprietaire = models.CharField(max_length=255, db_index=True, default='')

    class Meta:
        db_table = 'fichiers'
        ordering = ['-date_upload']

    def __str__(self):
        return self.nom
