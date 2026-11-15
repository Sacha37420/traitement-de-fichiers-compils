"""Commande `rattacher_partages_storage` (contrat storage-hierarchie, I3) :
l'existant — un partage par fichier, la plupart à la racine — rangé sous le
conteneur, les extractions d'images regroupées en dossiers.

Les données d'avant le chantier sont posées directement (lignes en base,
partages dans le faux storage) : c'est l'état réel, pas un état produit par
le code d'aujourd'hui.
"""
from io import StringIO

from django.core.management import call_command
from django.core.management.base import CommandError

from api.models import Dossier, Fichier, Partage
from .socle import CONTENEUR, JETON_SERVICE, SocleTestCase

ALICE = 'alice@exemple.org'


class RattacherTests(SocleTestCase):

    def ancien(self, nom, proprietaire=ALICE, contenu=b'octets', parent=None, partage_a=None):
        """Un fichier tel que déposé avant le chantier : un partage à lui, `nom`."""
        ns = f'tdfc-{len(self.reseau.partages):032x}'
        membres = {proprietaire: 'read'} if proprietaire else {}
        if partage_a:
            membres[partage_a] = 'read'
        self.reseau.creer(ns, parent=parent, fichiers={nom: contenu}, membres=membres)
        f = Fichier.objects.create(nom=nom, type='Image', taille_fichier=0.001, fichier_path=nom,
                                   storage_namespace=ns, fichier_type_mime='image/png',
                                   proprietaire=proprietaire)
        if partage_a:
            Partage.objects.create(fichier=f, destinataire=partage_a)
        return f

    def setUp(self):
        super().setUp()
        self.reseau.creer(CONTENEUR)                     # I0 appliqué : au compte de service
        self.frames = [self.ancien(f'VID1-frame-{i}', contenu=b'F%d' % i) for i in (1, 2, 3)]
        self.frame_partagee = self.ancien('VID1-frame-4', partage_a='bob@exemple.org')
        self.isole = self.ancien('rapport')
        self.sans_proprio = self.ancien('VID9-frame-1', proprietaire='', parent=CONTENEUR)
        self.deja_range = self.ancien('note', parent=CONTENEUR)
        self.autre = self.ancien('VID1-frame-1', proprietaire='bob@exemple.org')

    def lancer(self, *args):
        out = StringIO()
        try:
            call_command('rattacher_partages_storage', *args, stdout=out)
            code = 0
        except CommandError as exc:
            out.write(str(exc))
            code = 1
        sortie = out.getvalue()
        self.assertNotIn('storage.test', sortie)
        self.assertNotIn('http', sortie)
        self.assertNotIn(JETON_SERVICE, sortie)
        return code, sortie

    def ecritures(self):
        return [a for a in self.reseau.appels() if a[0] != 'GET']

    def test_check_ne_touche_a_rien_et_dit_ce_qui_reste(self):
        code, sortie = self.lancer('--check')
        self.assertEqual(code, 1)
        self.assertEqual(self.ecritures(), [])
        self.assertFalse(Dossier.objects.exists())
        self.assertIn('« VID1 » (alice@exemple.org) : 4 fichier(s), dossier à créer', sortie)
        self.assertIn('« VID1 » (bob@exemple.org) : 1 fichier(s)', sortie)
        self.assertIn('(b) fichiers à déplacer dans le partage de leur dossier : 4', sortie)
        # frame partagée (futur enfant du dossier) + fichier isolé à la racine
        self.assertIn('(2) partages à rattacher : 2 ; déjà bien rangés : 2', sortie)

    def test_migration_complete_puis_rien_a_faire(self):
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        d = Dossier.objects.get(proprietaire=ALICE)
        self.assertEqual(d.nom, 'VID1')
        self.assertEqual(self.reseau.parent(d.storage_namespace), CONTENEUR)
        self.assertEqual(self.reseau.membres(d.storage_namespace), {ALICE: 'read'})
        # Les trois frames non partagées sont dans le partage du dossier, noms lisibles.
        self.assertEqual(self.reseau.partages[d.storage_namespace]['fichiers'],
                         {'VID1-frame-1': b'F1', 'VID1-frame-2': b'F2', 'VID1-frame-3': b'F3'})
        for f in self.frames:
            ancien = f.storage_namespace
            f.refresh_from_db()
            self.assertEqual((f.dossier_id, f.storage_namespace), (d.pk, d.storage_namespace))
            self.assertNotIn(ancien, self.reseau.partages)            # ancien partage supprimé
        # La frame partagée garde son partage (cloisonnement), rattaché au dossier.
        fp = self.frame_partagee
        fp.refresh_from_db()
        self.assertEqual(fp.dossier_id, d.pk)
        self.assertEqual(self.reseau.parent(fp.storage_namespace), d.storage_namespace)
        self.assertNotIn('bob@exemple.org', self.reseau.membres(d.storage_namespace))
        # Isolés et sans propriétaire : leur partage, sous le conteneur.
        for f in (self.isole, self.sans_proprio, self.deja_range):
            f.refresh_from_db()
            self.assertIsNone(f.dossier_id)
            self.assertEqual(self.reseau.parent(f.storage_namespace), CONTENEUR)
        # Les extractions d'un autre propriétaire ont leur propre dossier.
        self.assertEqual(Dossier.objects.get(proprietaire='bob@exemple.org').nom, 'VID1')
        self.assertIn('[4/4]', sortie)

        code, sortie = self.lancer('--check')
        self.assertEqual(code, 0, sortie)
        self.assertIn('Rien à faire.', sortie)
        self.reseau.journal.clear()
        self.assertEqual(self.lancer()[0], 0)
        # Rejouée : rien d'autre que des lectures et l'inscription (idempotente) du propriétaire.
        self.assertEqual({c for m, c in self.ecritures()},
                         {f'/api/shares/{d.storage_namespace}/members/' for d in Dossier.objects.all()})

    def test_conteneur_d_un_autre_arret_sans_rien_toucher(self):
        self.reseau.partages[CONTENEUR]['owner'] = 'sacha'
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn('indisponible', sortie)
        self.assertEqual(self.ecritures(), [])
        self.assertFalse(Dossier.objects.exists())
        self.assertIn('INDISPONIBLE', self.lancer('--check')[1])

    def test_conteneur_absent_il_est_cree(self):
        del self.reseau.partages[CONTENEUR]
        for f in (self.sans_proprio, self.deja_range):
            self.reseau.partages[f.storage_namespace]['parent'] = None
        self.assertEqual(self.lancer()[0], 0)
        self.assertIsNone(self.reseau.parent(CONTENEUR))
        self.assertEqual(self.reseau.parent(self.isole.storage_namespace), CONTENEUR)

    def test_interruption_a_la_suppression_reprise_sans_perte_ni_doublon(self):
        self.reseau.pannes.add('delete_share')
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn('échec : fichier', sortie)
        d = Dossier.objects.get(proprietaire=ALICE)
        for f in self.frames:                         # lignes inchangées, anciens partages intacts
            ancien = f.storage_namespace
            f.refresh_from_db()
            self.assertEqual(f.storage_namespace, ancien)
            self.assertIn(ancien, self.reseau.partages)
        self.reseau.pannes.clear()
        self.assertEqual(self.lancer()[0], 0)
        self.assertEqual(len(self.reseau.partages[d.storage_namespace]['fichiers']), 3)
        self.assertEqual(Fichier.objects.filter(storage_namespace=d.storage_namespace).count(), 3)

    def test_reprise_apres_suppression_de_l_ancien_partage(self):
        # Interruption entre la suppression de l'ancien partage et l'écriture de
        # la ligne : la copie déposée dans le dossier est adoptée.
        self.lancer()                                  # état final, puis on recrée l'interruption
        d = Dossier.objects.get(proprietaire=ALICE)
        f = self.frames[0]
        Fichier.objects.filter(pk=f.pk).update(storage_namespace='tdfc-' + 'f' * 32)
        code, sortie = self.lancer()
        self.assertEqual(code, 0, sortie)
        f.refresh_from_db()
        self.assertEqual((f.storage_namespace, f.fichier_path), (d.storage_namespace, 'VID1-frame-1'))
        # Si la copie manque aussi, le fichier est signalé, jamais inventé.
        Fichier.objects.filter(pk=f.pk).update(storage_namespace='tdfc-' + 'e' * 32)
        del self.reseau.partages[d.storage_namespace]['fichiers']['VID1-frame-1']
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn(f'échec : fichier #{f.pk}', sortie)
        f.refresh_from_db()
        self.assertEqual(f.storage_namespace, 'tdfc-' + 'e' * 32)

    def test_taille_deposee_fausse_l_ancien_partage_reste(self):
        self.reseau.taille_menteuse = True
        self.assertEqual(self.lancer()[0], 1)
        for f in self.frames:
            ancien = f.storage_namespace
            f.refresh_from_db()
            self.assertEqual(f.storage_namespace, ancien)
            self.assertIn(ancien, self.reseau.partages)

    def test_un_dossier_existant_du_meme_nom_est_reutilise(self):
        d = Dossier.objects.create(nom='VID1', proprietaire=ALICE, storage_namespace='tdfc-d-' + 'a' * 32)
        self.assertEqual(self.lancer()[0], 0)
        self.assertEqual(Dossier.objects.filter(proprietaire=ALICE).count(), 1)
        self.assertEqual(Fichier.objects.filter(storage_namespace=d.storage_namespace).count(), 3)
        self.assertEqual(self.reseau.parent(d.storage_namespace), CONTENEUR)   # partage créé

    def test_nom_deja_pris_dans_le_dossier_suffixe(self):
        d = Dossier.objects.create(nom='VID1', proprietaire=ALICE, storage_namespace='tdfc-d-' + 'b' * 32)
        self.reseau.creer(d.storage_namespace, parent=CONTENEUR, fichiers={'VID1-frame-1': b'autre'},
                          membres={ALICE: 'read'})
        Fichier.objects.create(nom='VID1-frame-1', type='Image', taille_fichier=0, fichier_path='VID1-frame-1',
                               storage_namespace=d.storage_namespace, fichier_type_mime='image/png',
                               proprietaire=ALICE, dossier=d)
        self.assertEqual(self.lancer()[0], 0)
        f = self.frames[0]
        f.refresh_from_db()
        self.assertEqual(f.fichier_path, 'VID1-frame-1-2')
        self.assertEqual(self.reseau.partages[d.storage_namespace]['fichiers']['VID1-frame-1'], b'autre')

    def test_rattachement_refuse_compte_en_echec(self):
        self.reseau.pannes.add('patch')
        code, sortie = self.lancer()
        self.assertEqual(code, 1)
        self.assertIn('échec : rattachement', sortie)
