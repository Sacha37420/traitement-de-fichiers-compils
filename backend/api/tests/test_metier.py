"""Règles métier : dépôt (limite de poids, type, nom, chemin dans storage),
ordre des écritures entre storage et la base, et ce qui arrive quand storage
ou Keycloak ne répond pas."""
import unittest
from decimal import Decimal

from django.test import override_settings

from api.models import Fichier, Partage
from api.views import _safe_name, _type_depuis_mime
from .socle import SocleTestCase


class DepotTests(SocleTestCase):

    def test_un_depot_cree_son_share_et_y_inscrit_le_proprietaire(self):
        resp = self.deposer(self.alice, nom='rapport.pdf', contenu=b'%PDF-1.4 abc')
        self.assertEqual(resp.status_code, 201)
        f = Fichier.objects.get()
        self.assertRegex(f.storage_namespace, r'^tdfc-[0-9a-f]{32}$')
        self.assertEqual(self.reseau.partages[f.storage_namespace], {
            'fichiers': {'rapport.pdf': b'%PDF-1.4 abc'},
            # Sans cette ligne, le propriétaire lui-même ne lirait pas son fichier.
            'membres': {'alice@exemple.org': 'read'},
        })
        self.assertEqual((f.proprietaire, f.type, f.fichier_type_mime, f.fichier_path),
                         ('alice@exemple.org', 'PDF', 'application/pdf', 'rapport.pdf'))
        self.assertEqual(resp.json()['fichier_url'],
                         f'https://lab.test/storage-api/api/files/{f.storage_namespace}/content/rapport.pdf')

    def test_deux_depots_du_meme_nom_ne_se_marchent_pas_dessus(self):
        a = self.fichier_de(self.alice, nom='x.pdf', contenu=b'un')
        b = self.fichier_de(self.alice, nom='x.pdf', contenu=b'deux')
        self.assertNotEqual(a.storage_namespace, b.storage_namespace)
        self.assertEqual(self.reseau.partages[a.storage_namespace]['fichiers'], {'x.pdf': b'un'})
        self.assertEqual(self.reseau.partages[b.storage_namespace]['fichiers'], {'x.pdf': b'deux'})

    def test_champ_fichier_absent(self):
        resp = self.alice.post('/api/fichiers/', {'nom': 'x'}, format='multipart')
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.reseau.journal, [])

    def test_limite_de_poids(self):
        # MAX_FICHIER_OCTETS=1024 dans le socle : la limite est incluse.
        self.assertEqual(self.deposer(self.alice, contenu=b'x' * 1024).status_code, 201)
        resp = self.deposer(self.alice, contenu=b'x' * 1025)
        self.assertEqual(resp.status_code, 413)
        self.assertEqual(Fichier.objects.count(), 1)
        self.assertEqual(len(self.reseau.partages), 1)        # rien n'est parti vers storage

    @override_settings(MAX_FICHIER_OCTETS=4 * 1024 * 1024)
    def test_la_taille_est_enregistree_en_mo(self):
        f = self.fichier_de(self.alice, contenu=b'x' * (1024 * 1024 + 524288))
        self.assertEqual(f.taille_fichier, Decimal('1.5'))
        self.assertEqual(self.fichier_de(self.alice, contenu=b'x' * 1536).taille_fichier, Decimal('0.001'))

    def test_type_deduit_du_mime(self):
        for mime, attendu in (('application/pdf', 'PDF'), ('image/png', 'Image'), ('video/mp4', 'Video'),
                              ('audio/ogg', 'Audio'), ('application/zip', 'PDF'), ('text/html', 'PDF')):
            self.assertEqual(_type_depuis_mime(mime), attendu, mime)

    def test_un_type_fourni_hors_liste_est_ignore(self):
        self.assertEqual(self.fichier_de(self.alice, mime='image/png', type='Audio').type, 'Audio')
        self.assertEqual(self.fichier_de(self.alice, mime='image/png', type='Executable').type, 'Image')
        self.assertEqual(self.fichier_de(self.alice, mime='image/png').type, 'Image')

    def test_filtre_par_type_et_pagination(self):
        for i in range(13):
            self.fichier_de(self.alice, nom=f'{i}.png', mime='image/png')
        self.fichier_de(self.alice, nom='a.pdf')
        page = self.alice.get('/api/fichiers/').json()
        self.assertEqual((page['count'], len(page['results'])), (14, 12))
        self.assertEqual(self.alice.get('/api/fichiers/?type=PDF').json()['count'], 1)
        self.assertEqual(self.alice.get('/api/fichiers/?type=Image').json()['count'], 13)

    def test_nom_sur_pour_un_chemin_storage(self):
        # Ni '/', ni segment vide, ni '.'/'..' : jamais de sortie du Share.
        for nom, attendu in (('rapport final.pdf', 'rapport_final.pdf'), ('../../etc/passwd', '_.._etc_passwd'),
                             ('..', 'fichier'), ('.', 'fichier'), ('', 'fichier'), ('   ', 'fichier'),
                             ('a/b\\c.pdf', 'a_b_c.pdf'), ('été.png', '_t_.png'), ('.cache.', 'cache'),
                             ('///', '_'), (None, 'fichier')):
            with self.subTest(nom=nom):
                sur = _safe_name(nom)
                self.assertEqual(sur, attendu)
                self.assertNotIn('/', sur)
                self.assertNotIn(sur, ('', '.', '..'))

    def test_le_nom_d_origine_est_garde_le_chemin_est_assaini(self):
        resp = self.deposer(self.alice, nom='x.pdf', nom_saisi='../../autre/été 2026.pdf')
        self.assertEqual(resp.status_code, 201)
        f = Fichier.objects.get()
        self.assertEqual(f.nom, '../../autre/été 2026.pdf')
        self.assertEqual(f.fichier_path, '_.._autre_t_2026.pdf')
        # La requête réellement émise est restée dans le Share du fichier.
        self.assertEqual(self.reseau.appels('POST')[0], ('POST', f'/api/files/{f.storage_namespace}/'))
        self.assertEqual(list(self.reseau.partages), [f.storage_namespace])

    # DÉFAUT (I4) — `nom` (champ libre du formulaire) n'est pas borné avant
    # l'écriture : au-delà des 200 caractères de Fichier.nom, les octets sont
    # déjà dans storage et le propriétaire déjà membre quand l'INSERT échoue
    # (DataError → 500). Il reste un Share orphelin que rien ne purgera.
    @unittest.expectedFailure
    def test_un_nom_trop_long_est_refuse_sans_laisser_d_orphelin(self):
        self.alice.raise_request_exception = False
        resp = self.deposer(self.alice, nom='x.pdf', nom_saisi='n' * 201)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.reseau.partages, {})


class PannesTests(SocleTestCase):
    """storage ou Keycloak en défaut : l'app répond 502 et ne ment pas sur l'état."""

    def test_depot_storage_injoignable(self):
        self.reseau.coupe = True
        resp = self.deposer(self.alice)
        self.assertEqual(resp.status_code, 502)
        self.assertFalse(Fichier.objects.exists())             # pas de fichier fantôme

    def test_depot_compte_de_service_refuse_par_keycloak(self):
        self.reseau.pannes.add('token')
        self.assertEqual(self.deposer(self.alice).status_code, 502)
        self.assertFalse(Fichier.objects.exists())
        self.assertEqual(self.reseau.appels(), [])              # storage jamais appelé sans jeton

    @override_settings(KEYCLOAK_ADMIN_CLIENT_SECRET='')
    def test_depot_sans_secret_de_compte_de_service(self):
        self.assertEqual(self.deposer(self.alice).status_code, 502)
        self.assertEqual(self.reseau.journal, [])

    def test_depot_refuse_par_storage(self):
        self.reseau.pannes.add('upload')
        self.assertEqual(self.deposer(self.alice).status_code, 502)
        self.assertFalse(Fichier.objects.exists())

    def test_depot_annule_si_le_proprietaire_ne_peut_pas_etre_inscrit(self):
        # Les octets sont déposés, l'inscription du propriétaire échoue : l'app
        # retire le Share plutôt que de laisser un fichier que personne ne lirait.
        self.reseau.pannes.add('add_member')
        self.assertEqual(self.deposer(self.alice).status_code, 502)
        self.assertFalse(Fichier.objects.exists())
        self.assertEqual(self.reseau.partages, {})
        self.assertEqual([m for m, _ in self.reseau.appels()], ['POST', 'POST', 'DELETE'])

    def test_partage_storage_d_abord_la_ligne_ensuite(self):
        f = self.fichier_de(self.alice)
        self.reseau.pannes.add('add_member')
        resp = self.partager(self.alice, f, 'bob@exemple.org')
        self.assertEqual(resp.status_code, 502)
        # Pas de Partage sans ShareMember : le propriétaire croirait à tort avoir partagé.
        self.assertFalse(Partage.objects.exists())
        self.assertEqual(self.bob.get(f'/api/fichiers/{f.pk}/').status_code, 404)

    def test_retrait_refuse_par_storage_la_ligne_reste(self):
        f = self.fichier_de(self.alice)
        self.partager(self.alice, f, 'bob@exemple.org')
        self.reseau.pannes.add('remove_member')
        resp = self.alice.delete(f'/api/fichiers/{f.pk}/partages/?email=bob@exemple.org')
        self.assertEqual(resp.status_code, 502)
        # L'accès direct aux octets est encore ouvert côté storage : l'app ne
        # doit pas afficher le partage comme retiré.
        self.assertIn('bob@exemple.org', self.reseau.membres(f.storage_namespace))
        self.assertEqual(Partage.objects.count(), 1)
        self.assertEqual(self.alice.get(f'/api/fichiers/{f.pk}/').json()['partages'], ['bob@exemple.org'])

    def test_retrait_d_un_membre_deja_absent_de_storage(self):
        f = self.fichier_de(self.alice)
        self.partager(self.alice, f, 'bob@exemple.org')
        del self.reseau.membres(f.storage_namespace)['bob@exemple.org']     # 404 côté storage
        resp = self.alice.delete(f'/api/fichiers/{f.pk}/partages/?email=bob@exemple.org')
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(Partage.objects.exists())

    def test_suppression_meme_si_storage_ne_repond_pas(self):
        f = self.fichier_de(self.alice)
        self.partager(self.alice, f, 'bob@exemple.org')
        self.reseau.coupe = True
        self.assertEqual(self.alice.delete(f'/api/fichiers/{f.pk}/').status_code, 204)
        self.assertFalse(Fichier.objects.exists())
        self.assertFalse(Partage.objects.exists())


class PartageReglesTests(SocleTestCase):

    def setUp(self):
        super().setUp()
        self.f = self.fichier_de(self.alice)
        self.avant = len(self.reseau.journal)

    def test_adresses_refusees(self):
        for email in ('', '   ', 'pas-une-adresse', None):
            with self.subTest(email=email):
                resp = self.alice.post(f'/api/fichiers/{self.f.pk}/partages/',
                                       {} if email is None else {'email': email}, format='json')
                self.assertEqual(resp.status_code, 400)
        self.assertEqual(self.reseau.journal[self.avant:], [])
        self.assertFalse(Partage.objects.exists())

    def test_on_ne_partage_pas_avec_soi_meme(self):
        for email in ('alice@exemple.org', ' ALICE@exemple.org '):
            self.assertEqual(self.partager(self.alice, self.f, email).status_code, 400)
        self.assertFalse(Partage.objects.exists())

    def test_partager_deux_fois_ne_cree_qu_une_ligne(self):
        for email in ('bob@exemple.org', 'BOB@exemple.org'):
            resp = self.partager(self.alice, self.f, email)
            self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['partages'], ['bob@exemple.org'])
        self.assertEqual(Partage.objects.count(), 1)

    def test_fichier_sans_share_storage_non_partageable(self):
        # Ligne d'avant la migration 0005 restée sans Share : rien à ouvrir.
        vieux = Fichier.objects.create(nom='vieux.pdf', type='PDF', taille_fichier=1,
                                       fichier_type_mime='application/pdf', proprietaire='alice@exemple.org')
        self.assertEqual(self.partager(self.alice, vieux, 'bob@exemple.org').status_code, 409)
        self.assertFalse(Partage.objects.exists())
        self.assertIsNone(self.alice.get(f'/api/fichiers/{vieux.pk}/').json()['fichier_url'])
        # Et sa suppression n'appelle pas storage.
        self.assertEqual(self.alice.delete(f'/api/fichiers/{vieux.pk}/').status_code, 204)
        self.assertEqual(self.reseau.journal[self.avant:], [])
