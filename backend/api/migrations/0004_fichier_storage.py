"""Fichier.fichier_binaire (BinaryField dans devdb) → Fichier.fichier_path
(chemin dans le partage storage de l'app).

Contrairement à la migration équivalente de `restauration`, **il y a des données
à reprendre** : les octets sont transférés vers storage par le RunPython
ci-dessous, puis la colonne est supprimée — dans la même migration, donc dans la
même transaction. Si storage est injoignable ou refuse un upload, la migration
échoue et la colonne n'est pas supprimée : aucun octet ne peut être perdu en
silence. Le conteneur ne démarrera pas (migrate est dans le CMD), ce qui est le
bon mode d'échec — mieux vaut une app arrêtée qu'une app démarrée sans les
fichiers de ses utilisateurs.

Prérequis, à faire AVANT de déployer (sinon la migration échoue proprement) :
  - le partage doit exister côté storage :
      python manage.py create_group_share traitement-de-fichiers-compils \\
          --owner sacha --required-groups developers
  - le compte de service doit y être autorisé (storage/.env) :
      KEYCLOAK_SERVICE_WRITE_SHARES=…,traitement-de-fichiers-compils-admin:traitement-de-fichiers-compils
  - le client compagnon doit exister (setup2.sh le provisionne via
    .keycloak-service-account-roles) et son secret être dans .env.

Le chemin cible est dérivé de la clé primaire (`fichiers/<pk>-<nom>`), pas d'un
UUID comme pour les uploads courants : si la migration échoue à mi-parcours et
qu'on la relance, les fichiers déjà transférés sont réécrits au même chemin
plutôt que dupliqués en blobs orphelins (storage écrase sur (namespace, chemin)).
"""
import io
import re

from django.db import migrations, models


def _safe_name(nom: str) -> str:
    """Nom de fichier sûr pour un segment de chemin storage : pas de '/', pas de
    segment vide ni '.'/'..' (cf. storage/backend/api/validators.py)."""
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', (nom or '').strip()) or 'fichier'
    return cleaned.strip('.') or 'fichier'


def blobs_vers_storage(apps, schema_editor):
    from api import storage_client

    Fichier = apps.get_model('api', 'Fichier')
    for fichier in Fichier.objects.all().iterator():
        octets = bytes(fichier.fichier_binaire or b'')
        if not octets:
            # Ligne sans contenu : rien à transférer, fichier_path reste vide.
            continue
        relative_path = f'fichiers/{fichier.pk}-{_safe_name(fichier.nom)}'
        result = storage_client.upload(
            relative_path,
            io.BytesIO(octets),
            _safe_name(fichier.nom),
            fichier.fichier_type_mime or 'application/octet-stream',
        )
        fichier.fichier_path = result['relative_path']
        fichier.save(update_fields=['fichier_path'])


def storage_vers_blobs(apps, schema_editor):
    """Marche arrière : rapatrie les octets depuis storage dans la colonne.

    Ne supprime rien de storage — un rollback est déjà une situation anormale,
    mieux vaut y laisser des blobs orphelins (repérables par leur chemin
    `fichiers/<pk>-…`) que de détruire l'unique copie si la migration inverse
    échouait ensuite.
    """
    from api import storage_client

    Fichier = apps.get_model('api', 'Fichier')
    for fichier in Fichier.objects.exclude(fichier_path='').iterator():
        resp = storage_client.download(fichier.fichier_path)
        fichier.fichier_binaire = b''.join(resp.iter_content(65536))
        fichier.save(update_fields=['fichier_binaire'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0003_partage'),
    ]

    operations = [
        migrations.AddField(
            model_name='fichier',
            name='fichier_path',
            field=models.CharField(blank=True, default='', max_length=1024),
        ),
        # Rend la colonne facultative : la marche arrière doit pouvoir recréer
        # les lignes avant de les remplir.
        migrations.AlterField(
            model_name='fichier',
            name='fichier_binaire',
            field=models.BinaryField(blank=True, null=True),
        ),
        migrations.RunPython(blobs_vers_storage, storage_vers_blobs),
        migrations.RemoveField(
            model_name='fichier',
            name='fichier_binaire',
        ),
    ]
