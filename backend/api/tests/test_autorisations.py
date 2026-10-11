"""Qui lit, partage et supprime quoi.

L'autorisation est portée par les modèles de l'app — ``Fichier.proprietaire``
(un email) et ``Partage`` — et décidée par ``_owned`` / ``_accessible``
(api/views.py). ``storage`` n'en reçoit qu'une réplique (ShareMember), tenue
par le compte de service : c'est elle qui ouvre la lecture directe des octets.
Un refus se dit toujours 404 : l'existence d'un fichier d'autrui ne fuit pas.
"""

from api.models import Fichier, Partage
from .socle import JETON_SERVICE, SocleTestCase, client_de


class LectureTests(SocleTestCase):

    def setUp(self):
        super().setUp()
        self.f_alice = self.fichier_de(self.alice, nom='alice.pdf')
        self.f_bob = self.fichier_de(self.bob, nom='bob.pdf')

    def ids(self, resp):
        self.assertEqual(resp.status_code, 200)
        return [f['id'] for f in resp.json()['results']]

    def test_la_liste_ne_rend_que_mes_fichiers(self):
        self.assertEqual(self.ids(self.alice.get('/api/fichiers/')), [self.f_alice.pk])
        self.assertEqual(self.ids(self.bob.get('/api/fichiers/')), [self.f_bob.pk])
        self.assertEqual(self.ids(self.carol.get('/api/fichiers/')), [])

    def test_le_detail_d_un_fichier_d_autrui_est_un_404(self):
        self.assertEqual(self.alice.get(f'/api/fichiers/{self.f_alice.pk}/').status_code, 200)
        self.assertEqual(self.bob.get(f'/api/fichiers/{self.f_alice.pk}/').status_code, 404)
        # Même réponse que pour un fichier qui n'existe pas.
        self.assertEqual(self.bob.get('/api/fichiers/999999/').status_code, 404)

    def test_un_partage_ouvre_le_detail_au_destinataire_et_a_lui_seul(self):
        self.assertEqual(self.partager(self.alice, self.f_alice, 'bob@exemple.org').status_code, 201)
        self.assertEqual(self.bob.get(f'/api/fichiers/{self.f_alice.pk}/').status_code, 200)
        self.assertEqual(self.carol.get(f'/api/fichiers/{self.f_alice.pk}/').status_code, 404)
        # Le partage ne fait pas du fichier « un de mes fichiers ».
        self.assertEqual(self.ids(self.bob.get('/api/fichiers/')), [self.f_bob.pk])
        self.assertEqual(self.ids(self.bob.get('/api/fichiers/partages/')), [self.f_alice.pk])
        self.assertEqual(self.ids(self.carol.get('/api/fichiers/partages/')), [])
        self.assertEqual(self.ids(self.alice.get('/api/fichiers/partages/')), [])

    def test_le_partage_ne_donne_aucun_droit_sur_les_autres_fichiers_du_proprietaire(self):
        autre = self.fichier_de(self.alice, nom='secret.pdf')
        self.partager(self.alice, self.f_alice, 'bob@exemple.org')
        self.assertEqual(self.bob.get(f'/api/fichiers/{autre.pk}/').status_code, 404)
        # Un Share storage PAR fichier : Bob n'est membre que de celui du fichier partagé.
        self.assertIn('bob@exemple.org', self.reseau.membres(self.f_alice.storage_namespace))
        self.assertNotIn('bob@exemple.org', self.reseau.membres(autre.storage_namespace))
        self.assertNotEqual(autre.storage_namespace, self.f_alice.storage_namespace)

    def test_la_liste_des_destinataires_n_est_visible_que_du_proprietaire(self):
        self.partager(self.alice, self.f_alice, 'bob@exemple.org')
        self.partager(self.alice, self.f_alice, 'carol@exemple.org')
        chez_alice = self.alice.get(f'/api/fichiers/{self.f_alice.pk}/').json()
        chez_bob = self.bob.get(f'/api/fichiers/{self.f_alice.pk}/').json()
        self.assertEqual(chez_alice['partages'], ['bob@exemple.org', 'carol@exemple.org'])
        self.assertEqual(chez_bob['partages'], [])
        self.assertEqual(self.bob.get('/api/fichiers/partages/').json()['results'][0]['partages'], [])

    def test_le_destinataire_est_reconnu_quelle_que_soit_la_casse_de_son_adresse(self):
        self.partager(self.alice, self.f_alice, '  Bob@Exemple.ORG ')
        self.assertEqual(Partage.objects.get().destinataire, 'bob@exemple.org')
        majuscule = client_de('Bob@Exemple.org')
        self.assertEqual(majuscule.get(f'/api/fichiers/{self.f_alice.pk}/').status_code, 200)
        self.assertEqual(self.ids(majuscule.get('/api/fichiers/partages/')), [self.f_alice.pk])


class EcritureTests(SocleTestCase):

    def setUp(self):
        super().setUp()
        self.f = self.fichier_de(self.alice, nom='alice.pdf')
        self.ns = self.f.storage_namespace

    def test_seul_le_proprietaire_supprime(self):
        self.partager(self.alice, self.f, 'bob@exemple.org')
        for intrus in (self.bob, self.carol):          # destinataire, puis étranger
            self.assertEqual(intrus.delete(f'/api/fichiers/{self.f.pk}/').status_code, 404)
        self.assertTrue(Fichier.objects.filter(pk=self.f.pk).exists())
        self.assertIn(self.ns, self.reseau.partages)
        self.assertEqual(self.reseau.appels('DELETE'), [])

        self.assertEqual(self.alice.delete(f'/api/fichiers/{self.f.pk}/').status_code, 204)
        self.assertFalse(Fichier.objects.filter(pk=self.f.pk).exists())
        self.assertFalse(Partage.objects.exists())
        self.assertNotIn(self.ns, self.reseau.partages)      # octets ET membres purgés
        self.assertEqual(self.bob.get(f'/api/fichiers/{self.f.pk}/').status_code, 404)

    def test_seul_le_proprietaire_partage(self):
        avant = len(self.reseau.journal)
        # Bob tente de s'ouvrir le fichier d'Alice, puis de l'ouvrir à Carol.
        for email in ('bob@exemple.org', 'carol@exemple.org'):
            self.assertEqual(self.partager(self.bob, self.f, email).status_code, 404)
        self.assertFalse(Partage.objects.exists())
        self.assertEqual(self.reseau.journal[avant:], [])     # storage n'a rien reçu
        self.assertEqual(self.reseau.membres(self.ns), {'alice@exemple.org': 'read'})

    def test_un_destinataire_ne_repartage_pas(self):
        self.partager(self.alice, self.f, 'bob@exemple.org')
        self.assertEqual(self.partager(self.bob, self.f, 'carol@exemple.org').status_code, 404)
        self.assertNotIn('carol@exemple.org', self.reseau.membres(self.ns))
        self.assertEqual(self.carol.get(f'/api/fichiers/{self.f.pk}/').status_code, 404)

    def test_seul_le_proprietaire_retire_un_partage(self):
        self.partager(self.alice, self.f, 'bob@exemple.org')
        self.partager(self.alice, self.f, 'carol@exemple.org')
        # Carol (destinataire) tente d'évincer Bob ; un étranger aussi.
        for intrus in (self.carol, client_de('dan@exemple.org')):
            resp = intrus.delete(f'/api/fichiers/{self.f.pk}/partages/?email=bob@exemple.org')
            self.assertEqual(resp.status_code, 404)
        self.assertEqual(Partage.objects.count(), 2)
        self.assertIn('bob@exemple.org', self.reseau.membres(self.ns))

    def test_retirer_un_partage_referme_tout(self):
        self.partager(self.alice, self.f, 'bob@exemple.org')
        resp = self.alice.delete(f'/api/fichiers/{self.f.pk}/partages/', {'email': 'Bob@exemple.org'}, format='json')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()['partages'], [])
        self.assertEqual(self.bob.get(f'/api/fichiers/{self.f.pk}/').status_code, 404)
        self.assertEqual(self.bob.get('/api/fichiers/partages/').json()['count'], 0)
        # La réplique côté storage — celle qui ouvre les octets — est retirée aussi.
        self.assertEqual(self.reseau.membres(self.ns), {'alice@exemple.org': 'read'})

    def test_le_proprietaire_est_celui_du_jeton_jamais_celui_de_la_requete(self):
        resp = self.deposer(self.bob, nom='b.pdf', proprietaire='alice@exemple.org')
        self.assertEqual(resp.status_code, 201)
        self.assertEqual(resp.json()['proprietaire'], 'bob@exemple.org')
        self.assertEqual(Fichier.objects.get(pk=resp.json()['id']).proprietaire, 'bob@exemple.org')

    def test_aucune_route_ne_modifie_un_fichier(self):
        for methode in ('put', 'patch'):
            resp = getattr(self.alice, methode)(f'/api/fichiers/{self.f.pk}/', {'proprietaire': 'bob@exemple.org'},
                                                format='json')
            self.assertEqual(resp.status_code, 405)

    def test_storage_ne_voit_jamais_le_jeton_de_l_utilisateur(self):
        # Écritures par le compte de service uniquement (CLAUDE.md : l'autorisation
        # est décidée par l'app, le compte de service transporte).
        self.partager(self.alice, self.f, 'bob@exemple.org')
        self.alice.delete(f'/api/fichiers/{self.f.pk}/partages/?email=bob@exemple.org')
        self.alice.delete(f'/api/fichiers/{self.f.pk}/')
        self.assertGreaterEqual(len(self.reseau.autorisations), 5)
        self.assertEqual(set(self.reseau.autorisations), {f'Bearer {JETON_SERVICE}'})
        self.assertEqual(self.reseau.jetons_emis, 1)          # et il est mis en cache


class TraverseeDeCheminTests(SocleTestCase):
    """L'adresse retirée d'un partage est collée telle quelle dans l'URL de storage."""

    def setUp(self):
        super().setUp()
        self.victime = self.fichier_de(self.alice, nom='alice.pdf')
        self.partager(self.alice, self.victime, 'bob@exemple.org')
        self.a_bob = self.fichier_de(self.bob, nom='bob.pdf')
        # Bob connaît le nom du Share de la victime : il est dans `fichier_url`.
        url = self.bob.get(f'/api/fichiers/{self.victime.pk}/').json()['fichier_url']
        self.assertIn(self.victime.storage_namespace, url)
        self.avant = len(self.reseau.journal)

    def emis(self):
        return self.reseau.journal[self.avant:]

    # Corrigé : l'adresse était collée telle quelle dans le chemin
    # `/api/shares/<ns>/members/<email>/` et `requests` normalise les `..` —
    # `../../<Share d'autrui>` faisait émettre par le compte de service un
    # `DELETE /api/shares/<Share d'autrui>/`. Désormais validée (400) et encodée.
    def test_retirer_un_partage_ne_peut_pas_supprimer_le_share_d_autrui(self):
        cible = self.victime.storage_namespace
        for email in (f'../../{cible}', f'x@y/../../../{cible}', f'x@y%2F..%2F..%2F..%2F{cible}'):
            resp = self.bob.delete(f'/api/fichiers/{self.a_bob.pk}/partages/', {'email': email}, format='json')
            self.assertEqual(resp.status_code, 400, email)
        self.assertEqual(self.emis(), [])                      # storage n'a rien reçu
        self.assertNotIn(('DELETE', f'/api/shares/{cible}/'), self.emis())
        self.assertIn(cible, self.reseau.partages)

    # Même chemin, autre cible : retirer au propriétaire l'accès à son propre fichier.
    def test_retirer_un_partage_ne_peut_pas_evincer_un_membre_d_un_autre_share(self):
        cible = self.victime.storage_namespace
        self.bob.delete(f'/api/fichiers/{self.a_bob.pk}/partages/',
                        {'email': f'../../{cible}/members/alice@exemple.org'}, format='json')
        self.assertIn('alice@exemple.org', self.reseau.membres(cible))

    def test_l_ajout_d_un_partage_ne_sort_pas_de_son_share(self):
        # À l'ajout, l'adresse voyage dans le CORPS de la requête, pas dans l'URL.
        cible = self.victime.storage_namespace
        resp = self.partager(self.bob, self.a_bob, f'x@y/../../{cible}/members/')
        self.assertEqual(resp.status_code, 400)
        for methode, chemin in self.emis():
            self.assertTrue(chemin.startswith(f'/api/shares/{self.a_bob.storage_namespace}/'), chemin)
        self.assertEqual(self.reseau.membres(cible), {'alice@exemple.org': 'read', 'bob@exemple.org': 'read'})

    def test_le_client_storage_encode_l_adresse_meme_sans_validation_en_amont(self):
        # Seconde barrière, indépendante de la vue : le segment est encodé en entier.
        from api import storage_client
        cible = self.victime.storage_namespace
        storage_client.remove_member(self.a_bob.storage_namespace, f'../../{cible}')
        self.assertIn(cible, self.reseau.partages)
        self.assertEqual(self.reseau.membres(cible), {'alice@exemple.org': 'read', 'bob@exemple.org': 'read'})
        self.assertEqual(self.reseau.appels('DELETE')[-1], (
            'DELETE', f'/api/shares/{self.a_bob.storage_namespace}/members/..%2F..%2F{cible}/'))
