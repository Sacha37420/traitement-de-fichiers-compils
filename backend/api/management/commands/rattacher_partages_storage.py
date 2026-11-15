"""Range dans storage les partages existants de l'app (contrat
storage-hierarchie, I3). Idempotente, rejouable après une interruption à tout
moment.

    python manage.py rattacher_partages_storage --check   # lecture seule
    python manage.py rattacher_partages_storage

Étapes (sans option) :
  (1) conteneur `traitement-de-fichiers-compils` : il doit appartenir au compte
      de service (I0) — sinon arrêt immédiat, rien n'est touché ;
  (a) regroupe les fichiers `<base>-frame-<N>` d'un même propriétaire (non vide)
      en un Dossier `<base>` (réutilisé s'il existe déjà pour ce propriétaire),
      et s'assure du partage storage de chaque dossier (propriétaire membre) ;
  (b) chaque fichier d'un dossier encore dans un partage à lui et sans Partage
      est déplacé dans le partage du dossier : téléchargé, redéposé sous un nom
      lisible, taille vérifiée, puis ligne mise à jour ET ancien partage
      supprimé dans une même transaction (si la suppression échoue, la ligne
      n'est pas modifiée ; la copie déposée sera réécrite au même chemin à la
      reprise : ni perte ni doublon) ;
  (2) rattache chaque partage connu de l'app à son parent voulu (conteneur, ou
      partage du dossier pour un fichier partagé d'un dossier) : état lu par UN
      appel `GET /api/shares/`, PATCH si le parent diffère ; partage absent de
      storage ou PATCH 404 : ignoré.

Reprise : si l'ancien partage d'un fichier n'existe plus (interruption entre sa
suppression et l'enregistrement de la ligne), la copie déjà présente dans le
partage du dossier, au chemin attendu, est adoptée.

Code de sortie 1 : `--check` → il reste quelque chose à faire ; sans option →
au moins un échec (le fichier en échec reste en place ; relancer). Rien de ce
qui est affiché ne contient de jeton ni d'URL : seulement des codes HTTP.
"""
from __future__ import annotations

import io
import re
from collections import defaultdict
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models import F

from api import storage_client
from api.models import Dossier, Fichier
from api.views import _safe_name, chemin_libre

FRAME_RE = re.compile(r'^(?P<base>.+)-frame-\d+(?:\.[A-Za-z0-9]+)?$')
PROGRESSION = 10


def _code(exc: Exception) -> str:
    code = getattr(exc, 'status_code', None)
    return f'HTTP {code}' if code else 'storage injoignable'


class Command(BaseCommand):
    help = "Range les partages storage de l'app sous son conteneur ; regroupe les extractions en dossiers."

    def add_arguments(self, parser):
        parser.add_argument('--check', action='store_true',
                            help='Lecture seule : affiche ce qui serait fait (code 1 s\'il reste à faire).')

    # ── utilitaires ─────────────────────────────────────────────────────────
    def say(self, msg: str) -> None:
        self.stdout.write(msg)

    @staticmethod
    def _groupes() -> dict[tuple[str, str], list[int]]:
        """{(propriétaire, base): [pk…]} des extractions pas encore rangées."""
        groupes: dict[tuple[str, str], list[int]] = defaultdict(list)
        qs = (Fichier.objects.filter(dossier__isnull=True).exclude(proprietaire='')
              .order_by('pk').values_list('pk', 'proprietaire', 'nom'))
        for pk, proprietaire, nom in qs:
            m = FRAME_RE.match(nom or '')
            if m:
                groupes[(proprietaire, m.group('base')[:200])].append(pk)
        return dict(groupes)

    @staticmethod
    def _a_deplacer():
        return (Fichier.objects.filter(dossier__isnull=False, partages__isnull=True)
                .exclude(storage_namespace='').exclude(fichier_path='')
                .exclude(storage_namespace=F('dossier__storage_namespace'))
                .select_related('dossier').order_by('pk').distinct())

    @staticmethod
    def _parents_voulus(exclure: set[str] = frozenset()) -> dict[str, str]:
        conteneur = storage_client.container_name()
        voulus = {d.storage_namespace: conteneur for d in Dossier.objects.all()}
        for f in Fichier.objects.exclude(storage_namespace='').select_related('dossier'):
            if f.storage_namespace in exclure or f.dans_partage_du_dossier:
                continue
            voulus[f.storage_namespace] = f.dossier.storage_namespace if f.dossier_id else conteneur
        return voulus

    # ── point d'entrée ──────────────────────────────────────────────────────
    def handle(self, *args, check=False, **options):
        try:
            return self._check() if check else self._run()
        except storage_client.StorageClientError as exc:
            raise CommandError(f'storage : lecture de l\'état impossible ({_code(exc)}).')

    # ── --check ─────────────────────────────────────────────────────────────
    def _check(self):
        a_faire = 0
        conteneur = storage_client.container_name()
        statut = storage_client.container_status()
        libelle = {'ok': 'au compte de service', 'absent': 'absent (sera créé)',
                   'indisponible': 'INDISPONIBLE (autre propriétaire ? I0 à appliquer)'}[statut]
        self.say(f'(1) conteneur « {conteneur} » : {libelle}')
        a_faire += statut != 'ok'

        owned = storage_client.owned_shares()

        groupes = self._groupes()
        a_grouper: set[int] = set()
        self.say(f'(a) extractions à ranger en dossier : {len(groupes)}')
        for (proprietaire, base), pks in sorted(groupes.items()):
            existe = Dossier.objects.filter(proprietaire=proprietaire, nom=base).exists()
            self.say(f'    « {base} » ({proprietaire}) : {len(pks)} fichier(s), dossier '
                     f'{"existant, réutilisé" if existe else "à créer"}')
            a_grouper.update(pks)
        a_faire += len(groupes)
        manquants = [d for d in Dossier.objects.all() if d.storage_namespace not in owned]
        if manquants:
            self.say(f'    dossiers existants sans partage storage : {len(manquants)} (à créer)')
            a_faire += len(manquants)

        # Fichiers qui seront déplacés : ceux d'un dossier déjà, plus ceux des
        # groupes ci-dessus (sans Partage, avec contenu).
        deplaces = list(self._a_deplacer())
        futurs = list(Fichier.objects.filter(pk__in=a_grouper, partages__isnull=True)
                      .exclude(storage_namespace='').exclude(fichier_path='').distinct())
        a_deplacer = deplaces + futurs
        octets = sum(float(f.taille_fichier) for f in a_deplacer)
        self.say(f'(b) fichiers à déplacer dans le partage de leur dossier : {len(a_deplacer)} '
                 f'(≈ {octets:.1f} Mo ; autant d\'anciens partages supprimés)')
        a_faire += len(a_deplacer)

        partant = {f.storage_namespace for f in a_deplacer}
        futurs_enfants = set(Fichier.objects.filter(pk__in=a_grouper, partages__isnull=False)
                             .exclude(storage_namespace='').values_list('storage_namespace', flat=True))
        voulus = self._parents_voulus(exclure=partant | futurs_enfants)
        # Fichier d'un futur dossier gardant son partage (il a un Partage) :
        # son parent sera ce dossier, inconnu tant qu'il n'est pas créé.
        a_rattacher = absents = 0
        for ns, parent in voulus.items():
            if ns not in owned:
                absents += 1
            elif owned[ns] != parent:
                a_rattacher += 1
        deja = len(voulus) - a_rattacher - absents
        a_rattacher += len(futurs_enfants)
        self.say(f'(2) partages à rattacher : {a_rattacher} ; déjà bien rangés : {deja} ; '
                 f'absents de storage (ignorés) : {absents}')
        a_faire += a_rattacher

        if a_faire:
            raise CommandError(f'Il reste {a_faire} élément(s) à traiter.')
        self.say('Rien à faire.')

    # ── exécution ───────────────────────────────────────────────────────────
    def _run(self):
        echecs = 0
        conteneur = storage_client.container_name()
        if not storage_client.ensure_container():
            raise CommandError(f'Conteneur « {conteneur} » indisponible (n\'appartient pas au compte '
                               'de service ? I0 à appliquer). Rien n\'a été modifié.')
        self.say(f'(1) conteneur « {conteneur} » : prêt')

        owned = storage_client.owned_shares()

        # (a) regroupement en dossiers
        for (proprietaire, base), pks in sorted(self._groupes().items()):
            with transaction.atomic():
                dossier = (Dossier.objects.filter(proprietaire=proprietaire, nom=base).order_by('pk').first()
                           or Dossier.objects.create(
                               nom=base, proprietaire=proprietaire,
                               storage_namespace=f'{settings.STORAGE_NAMESPACE_PREFIX}d-{uuid4().hex}'))
                Fichier.objects.filter(pk__in=pks, dossier__isnull=True).update(dossier=dossier)
            self.say(f'(a) « {base} » ({proprietaire}) : {len(pks)} fichier(s) rangé(s)')

        dossiers_prets: set[int] = set()
        for dossier in Dossier.objects.order_by('pk'):
            try:
                if dossier.storage_namespace not in owned:
                    storage_client.create_share(dossier.storage_namespace)
                    owned[dossier.storage_namespace] = None
                storage_client.add_member(dossier.storage_namespace, dossier.proprietaire, role='read')
                dossiers_prets.add(dossier.pk)
            except storage_client.StorageClientError as exc:
                echecs += 1
                self.say(f'    échec : partage du dossier #{dossier.pk} ({_code(exc)})')

        # (b) déplacements
        a_deplacer = [f for f in self._a_deplacer() if f.dossier_id in dossiers_prets]
        total = len(a_deplacer)
        self.say(f'(b) fichiers à déplacer : {total}')
        listings: dict[str, dict[str, int]] = {}
        faits = 0
        for i, fichier in enumerate(a_deplacer, 1):
            try:
                self._deplacer(fichier, owned, listings)
                faits += 1
            except storage_client.StorageClientError as exc:
                echecs += 1
                self.say(f'    échec : fichier #{fichier.pk} « {fichier.nom} » ({_code(exc)}) — laissé en place')
            if i % PROGRESSION == 0 or i == total:
                self.say(f'    [{i}/{total}] déplacés : {faits}, échecs : {i - faits}')

        # (2) rattachement — état relu par UN appel
        owned = storage_client.owned_shares()
        rattaches = deja = absents = 0
        for ns, parent in sorted(self._parents_voulus().items()):
            if ns not in owned:
                absents += 1
                continue
            if owned[ns] == parent:
                deja += 1
                continue
            try:
                if storage_client.set_parent(ns, parent):
                    rattaches += 1
                else:
                    absents += 1
            except storage_client.StorageClientError as exc:
                echecs += 1
                self.say(f'    échec : rattachement de {ns} ({_code(exc)})')
        self.say(f'(2) rattachés : {rattaches} ; déjà bien rangés : {deja} ; absents (ignorés) : {absents}')

        if echecs:
            raise CommandError(f'{echecs} échec(s) : relancer la commande (elle reprend où elle s\'est arrêtée).')
        self.say('Terminé, aucun échec.')

    def _deplacer(self, fichier: Fichier, owned: dict, listings: dict) -> None:
        dossier = fichier.dossier
        ancien = fichier.storage_namespace
        chemin = chemin_libre(dossier.storage_namespace, _safe_name(fichier.nom), exclude_pk=fichier.pk)

        if ancien not in owned:
            # Reprise : ancien partage déjà supprimé, ligne pas encore enregistrée.
            if dossier.storage_namespace not in listings:
                listings[dossier.storage_namespace] = storage_client.list_files(dossier.storage_namespace)
            if listings[dossier.storage_namespace].get(chemin, 0) <= 0:
                raise storage_client.StorageClientError('Ancien partage absent, aucune copie dans le dossier.')
            Fichier.objects.filter(pk=fichier.pk).update(
                storage_namespace=dossier.storage_namespace, fichier_path=chemin)
            return

        resp = storage_client.download_from(ancien, fichier.fichier_path)
        try:
            octets = b''.join(resp.iter_content(65536))
            annonce = resp.headers.get('Content-Length')
        finally:
            resp.close()
        if annonce is not None and annonce.isdigit() and int(annonce) != len(octets):
            raise storage_client.StorageClientError('Téléchargement incomplet.')
        result = storage_client.upload_to(
            dossier.storage_namespace, chemin, io.BytesIO(octets), chemin,
            fichier.fichier_type_mime or 'application/octet-stream',
        )
        if int(result.get('size', -1)) != len(octets):
            raise storage_client.StorageClientError('Taille déposée différente : ancien partage conservé.')
        # Ligne et suppression de l'ancien partage ensemble : si la suppression
        # échoue, la ligne reste sur l'ancien partage (copie réécrite à la reprise).
        with transaction.atomic():
            Fichier.objects.filter(pk=fichier.pk).update(
                storage_namespace=dossier.storage_namespace, fichier_path=result['relative_path'])
            storage_client.delete_share(ancien)
        owned.pop(ancien, None)
