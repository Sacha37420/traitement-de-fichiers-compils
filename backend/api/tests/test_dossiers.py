"""Dossiers et hiérarchie des partages storage (chantier « storage-hierarchie »,
contrat I1 et I2).

Arborescence voulue dans storage :
  traitement-de-fichiers-compils        conteneur (au compte de service)
   ├─ tdfc-<hex>                        fichier isolé
   └─ tdfc-d-<hex>                      dossier : ses fichiers non partagés
       └─ tdfc-<hex>                    fichier du dossier partagé à quelqu'un
"""
from api import storage_client
from api.models import Dossier, Fichier, Partage
from .socle import CONTENEUR, SERVICE, SocleTestCase


class CreationDePartageTests(SocleTestCase):
    """I1 : création explicite, rattachée, qui ne fait jamais échouer un dépôt."""

    def test_conteneur_absent_il_est_cree_puis_memorise(self):
        a = self.fichier_de(self.alice, nom='a.pdf')
        self.assertEqual(self.reseau.partages[CONTENEUR]['owner'], SERVICE)
        self.assertIsNone(self.reseau.parent(CONTENEUR))
        self.assertEqual(self.reseau.parent(a.storage_namespace), CONTENEUR)
        avant = len(self.reseau.journal)
        b = self.fichier_de(self.alice, nom='b.pdf')
        self.assertEqual(self.reseau.parent(b.storage_namespace), CONTENEUR)
        # Conteneur prêt mémorisé : plus de vérification au second dépôt.
        self.assertNotIn(('GET', f'/api/shares/{CONTENEUR}/members/'), self.reseau.journal[avant:])

    def test_conteneur_d_un_autre_proprietaire_le_depot_passe_a_la_racine(self):
        self.reseau.creer(CONTENEUR, owner='sacha')
        with self.assertLogs('api.storage_client', 'WARNING') as logs:
            f = self.fichier_de(self.alice)
        self.assertIsNone(self.reseau.parent(f.storage_namespace))
        self.assertEqual(self.reseau.partages[CONTENEUR]['owner'], 'sacha')    # jamais touché
        # Message fixe : ni jeton ni adresse.
        self.assertNotIn('http', ' '.join(logs.output))
        self.assertNotIn('jeton-du-compte', ' '.join(logs.output))

    def test_parent_refuse_le_depot_passe_a_la_racine(self):
        self.reseau.pannes.add('refus_parent')
        with self.assertLogs('api.storage_client', 'WARNING'):
            f = self.fichier_de(self.alice)
        self.assertIsNone(self.reseau.parent(f.storage_namespace))
        self.assertEqual(self.reseau.membres(f.storage_namespace), {'alice@exemple.org': 'read'})

    def test_un_partage_qui_existe_deja_est_un_succes(self):
        self.reseau.creer('tdfc-deja')
        storage_client.create_share('tdfc-deja')            # ne lève rien (400 « name »)
        self.assertIsNone(self.reseau.parent('tdfc-deja'))  # son rattachement relève de I3

    def test_creation_refusee_pas_d_octets_envoyes(self):
        self.reseau.pannes.add('create_share')
        self.assertEqual(self.deposer(self.alice).status_code, 502)
        self.assertFalse(Fichier.objects.exists())
        self.assertFalse([a for a in self.reseau.appels('POST') if a[1].startswith('/api/files/')])

    def test_envoi_en_echec_le_partage_cree_est_retire(self):
        self.reseau.pannes.add('upload')
        self.assertEqual(self.deposer(self.alice).status_code, 502)
        self.assertEqual(list(self.reseau.partages), [CONTENEUR])


class DossierApiTests(SocleTestCase):

    def creer_dossier(self, client, nom='Vacances'):
        resp = client.post('/api/dossiers/', {'nom': nom}, format='json')
        self.assertEqual(resp.status_code, 201, resp.content)
        return Dossier.objects.get(pk=resp.json()['id'])

    def deposer_dans(self, client, dossier, nom='photo.png', contenu=b'PNG', **kw):
        return self.deposer(client, nom=nom, contenu=contenu, mime='image/png', dossier=dossier.pk, **kw)

    def test_creer_un_dossier_cree_son_partage_rattache_au_conteneur(self):
        d = self.creer_dossier(self.alice)
        self.assertRegex(d.storage_namespace, r'^tdfc-d-[0-9a-f]{32}$')
        self.assertEqual(d.proprietaire, 'alice@exemple.org')
        self.assertEqual(self.reseau.parent(d.storage_namespace), CONTENEUR)
        self.assertEqual(self.reseau.membres(d.storage_namespace), {'alice@exemple.org': 'read'})

    def test_nom_de_dossier_requis_et_borne(self):
        for nom in ('', '   ', 'x' * 201):
            with self.subTest(n=len(nom)):
                self.assertEqual(self.alice.post('/api/dossiers/', {'nom': nom}, format='json').status_code, 400)
        self.assertEqual(self.alice.post('/api/dossiers/', {}, format='json').status_code, 400)
        self.assertFalse(Dossier.objects.exists())

    def test_dossier_storage_indisponible(self):
        self.reseau.pannes.add('add_member')
        self.assertEqual(self.alice.post('/api/dossiers/', {'nom': 'x'}, format='json').status_code, 502)
        self.assertFalse(Dossier.objects.exists())
        self.assertEqual(list(self.reseau.partages), [CONTENEUR])   # partage du dossier retiré

    def test_la_liste_ne_rend_que_mes_dossiers_avec_leur_nombre_de_fichiers(self):
        d = self.creer_dossier(self.alice)
        self.creer_dossier(self.bob, 'Bob')
        self.deposer_dans(self.alice, d, nom='1.png')
        self.deposer_dans(self.alice, d, nom='2.png')
        liste = self.alice.get('/api/dossiers/').json()
        self.assertEqual([(x['id'], x['nom'], x['nb_fichiers']) for x in liste], [(d.pk, 'Vacances', 2)])
        self.assertIn('date_creation', liste[0])
        self.assertEqual(self.carol.get('/api/dossiers/').json(), [])

    def test_depot_dans_un_dossier_meme_partage_nom_lisible(self):
        d = self.creer_dossier(self.alice)
        partages_avant = set(self.reseau.partages)
        r1 = self.deposer_dans(self.alice, d, nom='photo.png', contenu=b'un')
        r2 = self.deposer_dans(self.alice, d, nom='photo.png', contenu=b'deux')
        r3 = self.deposer_dans(self.alice, d, nom='photo.png', contenu=b'trois')
        self.assertEqual([r.status_code for r in (r1, r2, r3)], [201, 201, 201])
        self.assertEqual(set(self.reseau.partages), partages_avant)       # aucun partage de plus
        self.assertEqual(self.reseau.partages[d.storage_namespace]['fichiers'],
                         {'photo.png': b'un', 'photo-2.png': b'deux', 'photo-3.png': b'trois'})
        self.assertEqual(r2.json()['dossier'], {'id': d.pk, 'nom': 'Vacances'})
        self.assertEqual(r2.json()['fichier_url'],
                         f'https://lab.test/storage-api/api/files/{d.storage_namespace}/content/photo-2.png')
        self.assertTrue(all(f.dossier_id == d.pk for f in Fichier.objects.all()))

    def test_le_dossier_d_un_autre_est_refuse(self):
        d = self.creer_dossier(self.bob, 'De Bob')
        avant = list(self.reseau.journal)
        resp = self.deposer_dans(self.alice, d)
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.reseau.journal, avant)          # rien n'est parti vers storage
        self.assertEqual(self.reseau.partages[d.storage_namespace]['fichiers'], {})
        self.assertFalse(Fichier.objects.exists())
        for valeur in ('abc', '-1', '1.5'):
            with self.subTest(valeur=valeur):
                self.assertEqual(self.deposer(self.alice, dossier=valeur).status_code, 400)
        self.assertEqual(self.deposer(self.alice, dossier=999999).status_code, 404)

    def test_filtre_par_dossier(self):
        d = self.creer_dossier(self.alice)
        dans = Fichier.objects.get(pk=self.deposer_dans(self.alice, d).json()['id'])
        hors = self.fichier_de(self.alice, nom='seul.pdf')
        ids = lambda q: [f['id'] for f in self.alice.get(f'/api/fichiers/{q}').json()['results']]
        self.assertEqual(ids(f'?dossier={d.pk}'), [dans.pk])
        self.assertEqual(ids('?dossier=aucun'), [hors.pk])
        self.assertEqual(sorted(ids('')), sorted([dans.pk, hors.pk]))
        self.assertEqual(self.alice.get('/api/fichiers/?dossier=x').status_code, 400)
        # Le dossier d'Alice ne montre rien à Bob.
        self.assertEqual(self.bob.get(f'/api/fichiers/?dossier={d.pk}').json()['count'], 0)

    def test_supprimer_un_fichier_du_dossier_ne_retire_que_son_contenu(self):
        d = self.creer_dossier(self.alice)
        a = self.deposer_dans(self.alice, d, nom='a.png').json()['id']
        self.deposer_dans(self.alice, d, nom='b.png')
        self.assertEqual(self.alice.delete(f'/api/fichiers/{a}/').status_code, 204)
        self.assertEqual(self.reseau.partages[d.storage_namespace]['fichiers'], {'b.png': b'PNG'})

    def test_partager_un_fichier_du_dossier_le_sort_dans_un_partage_enfant(self):
        d = self.creer_dossier(self.alice)
        f = Fichier.objects.get(pk=self.deposer_dans(self.alice, d, nom='a.png', contenu=b'AAA').json()['id'])
        self.deposer_dans(self.alice, d, nom='b.png', contenu=b'BBB')
        self.assertEqual(self.partager(self.alice, f, 'bob@exemple.org').status_code, 201)
        f.refresh_from_db()
        self.assertRegex(f.storage_namespace, r'^tdfc-[0-9a-f]{32}$')
        self.assertEqual(f.dossier_id, d.pk)                          # reste dans le dossier
        self.assertEqual(self.reseau.parent(f.storage_namespace), d.storage_namespace)
        self.assertEqual(self.reseau.partages[f.storage_namespace]['fichiers'], {'a.png': b'AAA'})
        self.assertEqual(self.reseau.membres(f.storage_namespace),
                         {'alice@exemple.org': 'read', 'bob@exemple.org': 'read'})
        # Le destinataire n'est JAMAIS membre du partage du dossier : il lirait tout le dossier.
        self.assertEqual(self.reseau.membres(d.storage_namespace), {'alice@exemple.org': 'read'})
        self.assertEqual(self.reseau.partages[d.storage_namespace]['fichiers'], {'b.png': b'BBB'})
        # Second partage du même fichier : pas de second déplacement.
        partages = set(self.reseau.partages)
        self.assertEqual(self.partager(self.alice, f, 'carol@exemple.org').status_code, 201)
        self.assertEqual(set(self.reseau.partages), partages)
        # Révoquer ne le remet pas dans le dossier.
        self.alice.delete(f'/api/fichiers/{f.pk}/partages/', {'email': 'bob@exemple.org'}, format='json')
        self.alice.delete(f'/api/fichiers/{f.pk}/partages/', {'email': 'carol@exemple.org'}, format='json')
        f.refresh_from_db()
        self.assertNotEqual(f.storage_namespace, d.storage_namespace)
        self.assertEqual(self.reseau.membres(f.storage_namespace), {'alice@exemple.org': 'read'})

    def test_le_destinataire_ne_voit_pas_le_dossier(self):
        d = self.creer_dossier(self.alice)
        f = Fichier.objects.get(pk=self.deposer_dans(self.alice, d).json()['id'])
        self.partager(self.alice, f, 'bob@exemple.org')
        self.assertIsNone(self.bob.get(f'/api/fichiers/{f.pk}/').json()['dossier'])
        self.assertEqual(self.alice.get(f'/api/fichiers/{f.pk}/').json()['dossier'], {'id': d.pk, 'nom': 'Vacances'})

    def test_deplacement_en_echec_rien_ne_change(self):
        d = self.creer_dossier(self.alice)
        f = Fichier.objects.get(pk=self.deposer_dans(self.alice, d).json()['id'])
        avant = set(self.reseau.partages)
        self.reseau.pannes.add('download')
        self.assertEqual(self.partager(self.alice, f, 'bob@exemple.org').status_code, 502)
        f.refresh_from_db()
        self.assertEqual(f.storage_namespace, d.storage_namespace)
        self.assertFalse(Partage.objects.exists())
        self.assertEqual(set(self.reseau.partages), avant)            # partage provisoire retiré
        self.assertNotIn('bob@exemple.org', self.reseau.membres(d.storage_namespace))

    def test_supprimer_un_dossier_supprime_ses_fichiers_enfants_d_abord(self):
        d = self.creer_dossier(self.alice)
        f = Fichier.objects.get(pk=self.deposer_dans(self.alice, d, nom='a.png').json()['id'])
        self.deposer_dans(self.alice, d, nom='b.png')
        self.partager(self.alice, f, 'bob@exemple.org')
        f.refresh_from_db()
        enfant = f.storage_namespace
        hors = self.fichier_de(self.alice, nom='seul.pdf')
        self.assertEqual(self.bob.delete(f'/api/dossiers/{d.pk}/').status_code, 404)
        self.assertEqual(self.alice.delete(f'/api/dossiers/{d.pk}/').status_code, 204)
        self.assertFalse(Dossier.objects.exists())
        self.assertEqual(list(Fichier.objects.values_list('pk', flat=True)), [hors.pk])
        self.assertFalse(Partage.objects.exists())
        self.assertNotIn(enfant, self.reseau.partages)
        self.assertNotIn(d.storage_namespace, self.reseau.partages)
        suppressions = [c for m, c in self.reseau.appels('DELETE') if c.startswith('/api/shares/')]
        self.assertEqual(suppressions, [f'/api/shares/{enfant}/', f'/api/shares/{d.storage_namespace}/'])
        self.assertIn(hors.storage_namespace, self.reseau.partages)
