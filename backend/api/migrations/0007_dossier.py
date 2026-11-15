"""Dossiers (contrat storage-hierarchie, I2) — schéma seulement.

Aucun appel réseau ici (le conteneur lance `migrate` au démarrage) : le
regroupement des fichiers existants et le déplacement de leurs octets sont
faits par la commande `rattacher_partages_storage`, lancée après déploiement.
"""
import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0006_ocr_key_vault'),
    ]

    operations = [
        migrations.CreateModel(
            name='Dossier',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('nom', models.CharField(max_length=200)),
                ('proprietaire', models.CharField(db_index=True, max_length=255)),
                ('storage_namespace', models.CharField(max_length=64, unique=True)),
                ('date_creation', models.DateTimeField(auto_now_add=True)),
            ],
            options={
                'db_table': 'dossiers',
                'ordering': ['-date_creation'],
            },
        ),
        migrations.AddField(
            model_name='fichier',
            name='dossier',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name='fichiers', to='api.dossier'),
        ),
    ]
