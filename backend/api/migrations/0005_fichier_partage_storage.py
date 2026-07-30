"""Synchronise le modèle de partage de l'app avec de vrais Share/ShareMember
storage — un Share PAR Fichier (préfixe 'tdfc-'), plutôt que le Share global
unique utilisé jusqu'ici, pour permettre un accès direct navigateur → storage
en lecture (cf. FichierSerializer.get_fichier_url, api/views.py). Voir
api/storage_client.py pour le raisonnement complet du choix « par fichier ».

Prérequis, à faire AVANT de déployer (sinon la migration échoue proprement,
comme 0004) :
  - le compte de service doit avoir un write_prefix sur 'tdfc-' (storage/.env) :
      KEYCLOAK_SERVICE_WRITE_PREFIXES=…,traitement-de-fichiers-compils-admin:tdfc-
    (le Share par fichier est alors créé automatiquement au premier upload,
    contrairement à l'ancien Share global qui demandait un create_group_share
    préalable — rien à provisionner côté storage pour CE mécanisme.)
  - le frontend de cette app doit être dans KEYCLOAK_TRUSTED_CLIENTS côté
    storage (storage/.env) pour que l'accès direct fonctionne :
      KEYCLOAK_TRUSTED_CLIENTS=…,traitement-de-fichiers-compils

Pour chaque Fichier avec du contenu (fichier_path non vide, ancien format sous
l'unique namespace settings.STORAGE_NAMESPACE) :
  1. télécharge les octets depuis l'ancien emplacement ;
  2. les redépose sous un nouveau Share dédié 'tdfc-<uuid hex>' ;
  3. ajoute un ShareMember (role=read) pour le propriétaire, PUIS pour chaque
     destinataire de Partage déjà enregistré — c'est cette réplique qui
     sécurisera l'accès direct une fois le backend déployé ;
  4. met à jour storage_namespace/fichier_path ;
  5. purge l'ancien blob (best-effort : un blob orphelin sous l'ancien
     namespace est un moindre mal qu'une migration qui échoue à mi-parcours
     sur une étape non critique).

Comme 0004 : transfert des octets et changement de colonne dans la MÊME
migration/transaction. Si storage est injoignable, la migration échoue et rien
n'est perdu (aucun Fichier ne reste à moitié migré) — le conteneur ne démarre
pas (migrate est dans le CMD), c'est le bon mode d'échec.

Fichier.proprietaire vide (quelques lignes historiques de test, jamais
accessibles via l'app puisque _owned/_accessible comparent à l'email de
l'utilisateur connecté, jamais vide) : les octets sont quand même migrés pour
ne rien perdre, mais aucun ShareMember n'est ajouté faute d'email valide —
rien ne change côté accès (déjà inaccessible avant cette migration).
"""
import io
import re
import uuid

from django.db import migrations, models


def _safe_name(nom: str) -> str:
    cleaned = re.sub(r'[^A-Za-z0-9._-]+', '_', (nom or '').strip()) or 'fichier'
    return cleaned.strip('.') or 'fichier'


def vers_partages_individuels(apps, schema_editor):
    from api import storage_client

    Fichier = apps.get_model('api', 'Fichier')
    Partage = apps.get_model('api', 'Partage')

    for fichier in Fichier.objects.exclude(fichier_path='').iterator():
        old_path = fichier.fichier_path
        resp = storage_client.download(old_path)  # ancien namespace implicite
        octets = b''.join(resp.iter_content(65536))

        namespace = f'tdfc-{uuid.uuid4().hex}'
        safe_name = _safe_name(fichier.nom)
        result = storage_client.upload_to(
            namespace, safe_name, io.BytesIO(octets), safe_name,
            fichier.fichier_type_mime or 'application/octet-stream',
        )

        if fichier.proprietaire:
            storage_client.add_member(namespace, fichier.proprietaire, role='read')
        for partage in Partage.objects.filter(fichier=fichier):
            storage_client.add_member(namespace, partage.destinataire, role='read')

        fichier.storage_namespace = namespace
        fichier.fichier_path = result['relative_path']
        fichier.save(update_fields=['storage_namespace', 'fichier_path'])

        try:
            storage_client.delete(old_path)
        except storage_client.StorageClientError:
            pass


def vers_partage_global(apps, schema_editor):
    """Marche arrière : rapatrie chaque fichier dans l'ancien Share global unique,
    au même chemin qu'à l'origine (dérivé de la clé primaire, comme 0004) —
    idempotent en cas de reprise après échec partiel. Les Share par-fichier
    créés en avant ne sont PAS supprimés automatiquement ici : un rollback est
    déjà une situation anormale, mieux vaut laisser des Share orphelins
    (repérables par le préfixe 'tdfc-') que risquer de perdre des octets si la
    suppression échouait à son tour."""
    from api import storage_client

    Fichier = apps.get_model('api', 'Fichier')

    for fichier in Fichier.objects.exclude(storage_namespace='').iterator():
        resp = storage_client.download_from(fichier.storage_namespace, fichier.fichier_path)
        octets = b''.join(resp.iter_content(65536))

        old_path = f'fichiers/{fichier.pk}-{_safe_name(fichier.nom)}'
        storage_client.upload(
            old_path, io.BytesIO(octets), _safe_name(fichier.nom),
            fichier.fichier_type_mime or 'application/octet-stream',
        )

        fichier.fichier_path = old_path
        fichier.storage_namespace = ''
        fichier.save(update_fields=['fichier_path', 'storage_namespace'])


class Migration(migrations.Migration):

    dependencies = [
        ('api', '0004_fichier_storage'),
    ]

    operations = [
        migrations.AddField(
            model_name='fichier',
            name='storage_namespace',
            field=models.CharField(blank=True, default='', max_length=64),
        ),
        migrations.RunPython(vers_partages_individuels, vers_partage_global),
    ]
