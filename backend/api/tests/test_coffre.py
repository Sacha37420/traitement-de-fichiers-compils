"""Coffre de la clé Mistral et OCR par le serveur (contrat « failles », I3).

Avant : le navigateur appelait Mistral lui-même avec une clé gardée en
localStorage. Maintenant la clé est saisie une fois, gardée chiffrée ici
(`VAULT_ENCRYPTION_KEY`), jamais rendue ; le backend appelle Mistral.

Les jetons passent par la vraie classe d'authentification (socle) ; l'appel à
Mistral est simulé en remplaçant `requests.post` du module de vue — tout autre
appel réseau tomberait sur le faux réseau du socle, qui le refuse.
"""
import base64
from unittest import mock

import requests
from cryptography.fernet import Fernet
from django.conf import settings
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import override_settings
from rest_framework.test import APIClient

from api import views
from api.models import OcrKeyVault

from .socle import SocleTestCase, jeton

CLE = 'mistral-SECRETE-de-alice'
PDF = b'%PDF-1.4 un petit document'
PNG = b'\x89PNG\r\n\x1a\n une image'


def _reponse_mistral(status=200, data=None):
    r = mock.MagicMock()
    r.status_code = status
    r.ok = 200 <= status < 300
    r.json.return_value = data if data is not None else {}
    r.text = 'corps du fournisseur qui ne doit jamais sortir'
    return r


MISTRAL_OK = {
    'pages': [
        {'index': 0, 'markdown': '# Titre\n![img-0.jpeg](img-0.jpeg)',
         'images': [{'id': 'img-0.jpeg', 'image_base64': 'data:image/jpeg;base64,AAAA',
                     'top_left_x': 1, 'bottom_right_y': 2}],
         'dimensions': {'dpi': 200}},
        {'index': 1, 'markdown': 'Suite', 'images': []},
    ],
    'model': 'mistral-ocr-latest',
    'usage_info': {'pages_processed': 2, 'doc_size_bytes': 42},
}


class CoffreOcrTests(SocleTestCase):

    # ── gestes ────────────────────────────────────────────────────────────────
    def deposer_cle(self, client=None, corps=None):
        corps = {'mistral_key': CLE} if corps is None else corps
        return (client or self.alice).put('/api/ocr-key/', corps, format='json')

    def etat(self, client=None):
        resp = (client or self.alice).get('/api/ocr-key/')
        self.assertEqual(resp.status_code, 200)
        return resp.json()

    def ocr(self, client=None, contenu=PDF, mime='application/pdf', nom='doc.pdf', **extra):
        data = {'file': SimpleUploadedFile(nom, contenu, content_type=mime)}
        return (client or self.alice).post('/api/ocr/', data, format='multipart', **extra)

    def brut(self, email='alice@exemple.org'):
        with connection.cursor() as cur:
            cur.execute('SELECT mistral_key FROM ocr_key_vault WHERE owner_email = %s', [email])
            ligne = cur.fetchone()
        return ligne[0] if ligne else None

    def avec(self, tok):
        c = APIClient()
        c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        return c

    # ── forme de l'API du coffre ─────────────────────────────────────────────
    def test_get_ne_rend_que_configured_jamais_la_valeur(self):
        self.assertEqual(self.etat(), {'mistral_key_configured': False})
        resp = self.deposer_cle()
        self.assertEqual(resp.status_code, 204)
        self.assertEqual(resp.content, b'')
        resp = self.alice.get('/api/ocr-key/')
        self.assertEqual(resp.json(), {'mistral_key_configured': True})
        self.assertNotIn('SECRETE', resp.content.decode())
        self.assertNotIn(CLE[:8], resp.content.decode())

    def test_suppression_par_chaine_vide(self):
        self.deposer_cle()
        self.assertEqual(self.deposer_cle(corps={'mistral_key': '   '}).status_code, 204)
        self.assertEqual(self.etat(), {'mistral_key_configured': False})
        self.assertFalse(OcrKeyVault.objects.exists())
        # Retirer une clé absente : sans effet, pas d'erreur.
        self.assertEqual(self.deposer_cle(corps={'mistral_key': ''}).status_code, 204)

    def test_remplacement(self):
        self.deposer_cle()
        self.deposer_cle(corps={'mistral_key': 'nouvelle-cle'})
        self.assertEqual(OcrKeyVault.objects.get().mistral_key, 'nouvelle-cle')
        self.assertEqual(OcrKeyVault.objects.count(), 1)

    def test_corps_refuses(self):
        for corps in ({}, {'autre': 'x'}, {'mistral_key': CLE, 'autre': 'x'}, {'mistral_key': 12},
                      {'mistral_key': None}, {'mistral_key': ['x']}, {'mistral_key': 'deux mots'},
                      {'mistral_key': 'x' * 513}, {'mistral_key': 'a\nb'}, {'mistral_key': 'a\x00b'},
                      {'mistral_key': 'a​b'}):
            with self.subTest(corps=corps):
                self.assertEqual(self.alice.put('/api/ocr-key/', corps, format='json').status_code, 400)
        self.assertEqual(self.alice.put('/api/ocr-key/', ['mistral_key'], format='json').status_code, 400)
        self.assertEqual(self.alice.put('/api/ocr-key/', '', content_type='application/json').status_code, 400)
        self.assertFalse(OcrKeyVault.objects.exists())
        # 512 caractères : accepté.
        self.assertEqual(self.deposer_cle(corps={'mistral_key': 'k' * 512}).status_code, 204)

    # ── chiffrement au repos ─────────────────────────────────────────────────
    def test_chiffree_en_base_avec_la_cle_du_coffre_et_non_secret_key(self):
        self.deposer_cle()
        brut = self.brut()
        self.assertTrue(brut.startswith('gAAAAA'))
        self.assertNotIn('SECRETE', brut)
        self.assertEqual(Fernet(settings.VAULT_ENCRYPTION_KEY.encode()).decrypt(brut.encode()).decode(), CLE)
        with override_settings(SECRET_KEY='une-toute-autre-cle-django'):
            self.assertEqual(OcrKeyVault.objects.get().mistral_key, CLE)
            self.assertEqual(self.etat(), {'mistral_key_configured': True})

    def test_valeur_indechiffrable_traitee_comme_absente_jamais_envoyee(self):
        self.deposer_cle()
        brut = self.brut()
        with override_settings(VAULT_ENCRYPTION_KEY=Fernet.generate_key().decode()), \
                self.assertLogs('api.fields', 'WARNING') as journal, \
                mock.patch.object(views.requests, 'post') as post:
            self.assertEqual(self.etat(), {'mistral_key_configured': False})
            resp = self.ocr()
            self.assertEqual(resp.status_code, 400)
            self.assertEqual(resp.json()['code'], 'key_not_configured')
            post.assert_not_called()
        sortie = '\n'.join(journal.output)
        self.assertNotIn(brut, sortie)
        self.assertNotIn(CLE, sortie)

    # ── cloisonnement ────────────────────────────────────────────────────────
    def test_un_autre_compte_ne_voit_ni_n_utilise_la_cle_d_autrui(self):
        self.deposer_cle()
        self.assertEqual(self.etat(self.bob), {'mistral_key_configured': False})
        with mock.patch.object(views.requests, 'post') as post:
            resp = self.ocr(self.bob)
        self.assertEqual(resp.status_code, 400)
        self.assertEqual(resp.json()['code'], 'key_not_configured')
        post.assert_not_called()
        # Bob qui retire « sa » clé ne touche pas à celle d'Alice.
        self.deposer_cle(self.bob, {'mistral_key': ''})
        self.assertEqual(OcrKeyVault.objects.get(owner_email='alice@exemple.org').mistral_key, CLE)
        # Bob dépose la sienne : c'est elle qui part pour lui.
        self.deposer_cle(self.bob, {'mistral_key': 'cle-de-bob'})
        with mock.patch.object(views.requests, 'post', return_value=_reponse_mistral(200, MISTRAL_OK)) as post:
            self.assertEqual(self.ocr(self.bob).status_code, 200)
        self.assertEqual(post.call_args.kwargs['headers']['Authorization'], 'Bearer cle-de-bob')

    def test_jeton_d_un_autre_client_ou_sans_jeton_refuse(self):
        self.deposer_cle()
        with mock.patch.object(views.requests, 'post') as post:
            for azp in ('admin-cli', 'storage', None):
                client = self.avec(jeton('alice@exemple.org', azp=azp))
                with self.subTest(azp=azp):
                    resp = client.get('/api/ocr-key/')
                    self.assertIn(resp.status_code, (401, 403))
                    self.assertNotIn('configured', resp.content.decode())
                    self.assertIn(client.put('/api/ocr-key/', {'mistral_key': 'pirate'},
                                             format='json').status_code, (401, 403))
                    self.assertIn(self.ocr(client).status_code, (401, 403))
            anonyme = APIClient()
            self.assertIn(anonyme.get('/api/ocr-key/').status_code, (401, 403))
            self.assertIn(anonyme.put('/api/ocr-key/', {'mistral_key': 'x'}, format='json').status_code, (401, 403))
            self.assertIn(self.ocr(anonyme).status_code, (401, 403))
            hors_groupe = self.avec(jeton('alice@exemple.org', ['amis']))
            self.assertIn(self.ocr(hors_groupe).status_code, (401, 403))
            post.assert_not_called()
        self.assertEqual(OcrKeyVault.objects.get().mistral_key, CLE)

    # ── OCR ──────────────────────────────────────────────────────────────────
    def test_ocr_pdf_mistral_recoit_la_cle_du_coffre_et_la_reponse_est_filtree(self):
        self.deposer_cle()
        with mock.patch.object(views.requests, 'post', return_value=_reponse_mistral(200, MISTRAL_OK)) as post:
            resp = self.ocr()
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(post.call_count, 1)
        self.assertEqual(post.call_args.args[0], 'https://api.mistral.ai/v1/ocr')
        kw = post.call_args.kwargs
        self.assertEqual(kw['headers'], {'Authorization': f'Bearer {CLE}', 'Content-Type': 'application/json'})
        self.assertEqual(kw['timeout'], (10, 110))
        self.assertEqual(kw['json']['model'], 'mistral-ocr-latest')
        self.assertTrue(kw['json']['include_image_base64'])
        self.assertEqual(kw['json']['document'], {
            'type': 'document_url',
            'document_url': 'data:application/pdf;base64,' + base64.b64encode(PDF).decode(),
        })
        self.assertEqual(resp.json(), {'pages': [
            {'markdown': '# Titre\n![img-0.jpeg](img-0.jpeg)',
             'images': [{'id': 'img-0.jpeg', 'image_base64': 'data:image/jpeg;base64,AAAA'}]},
            {'markdown': 'Suite', 'images': []},
        ]})
        self.assertNotIn('SECRETE', resp.content.decode())
        self.assertNotIn('usage_info', resp.content.decode())

    def test_ocr_image_part_en_image_url(self):
        self.deposer_cle()
        with mock.patch.object(views.requests, 'post', return_value=_reponse_mistral(200, MISTRAL_OK)) as post:
            resp = self.ocr(contenu=PNG, mime='image/png', nom='scan.png')
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(post.call_args.kwargs['json']['document'], {
            'type': 'image_url', 'image_url': 'data:image/png;base64,' + base64.b64encode(PNG).decode(),
        })

    def test_reponse_mistral_mal_formee_filtree_sans_erreur(self):
        self.deposer_cle()
        bizarre = {'pages': [{'markdown': 3, 'images': [{'id': 1}, 'x', {'id': 'a', 'image_base64': 'b', 'z': 1}]},
                             'pas une page'], 'autre': 'x'}
        with mock.patch.object(views.requests, 'post', return_value=_reponse_mistral(200, bizarre)):
            resp = self.ocr()
        self.assertEqual(resp.json(), {'pages': [{'markdown': '', 'images': [{'id': 'a', 'image_base64': 'b'}]}]})

    def test_type_refuse(self):
        self.deposer_cle()
        with mock.patch.object(views.requests, 'post') as post:
            for mime in ('image/svg+xml', 'text/html', 'video/mp4', 'application/octet-stream', 'image/bmp'):
                with self.subTest(mime=mime):
                    self.assertEqual(self.ocr(mime=mime, nom='x').status_code, 400)
            sans_fichier = self.alice.post('/api/ocr/', {}, format='multipart')
            self.assertEqual(sans_fichier.status_code, 400)
            post.assert_not_called()

    @override_settings(OCR_MAX_OCTETS=1000)
    def test_trop_gros_refuse_413_sans_appel(self):
        self.deposer_cle()
        with mock.patch.object(views.requests, 'post') as post:
            # Annonce (Content-Length) au-delà de la limite + marge multipart : refus avant lecture.
            resp = self.ocr(contenu=b'x' * (1000 + 70 * 1024))
            self.assertEqual(resp.status_code, 413)
            resp = self.ocr(CONTENT_LENGTH=str(10 ** 9))
            self.assertEqual(resp.status_code, 413)
            # Dans la marge, mais le fichier lui-même dépasse : refusé aussi.
            resp = self.ocr(contenu=b'%PDF' + b'x' * 2000)
            self.assertEqual(resp.status_code, 413)
            post.assert_not_called()
        with mock.patch.object(views.requests, 'post', return_value=_reponse_mistral(200, MISTRAL_OK)):
            self.assertEqual(self.ocr(contenu=b'%PDF' + b'x' * 900).status_code, 200)

    def test_cle_refusee_par_mistral_502_key_rejected(self):
        self.deposer_cle()
        for code in (401, 403):
            with self.subTest(code=code), \
                    mock.patch.object(views.requests, 'post',
                                      return_value=_reponse_mistral(code, {'message': 'Unauthorized SECRETE'})):
                resp = self.ocr()
                self.assertEqual(resp.status_code, 502)
                self.assertEqual(resp.json()['code'], 'key_rejected')
                self.assertNotIn('SECRETE', resp.content.decode())
                self.assertNotIn('Unauthorized', resp.content.decode())

    def test_autre_erreur_mistral_502_generique(self):
        self.deposer_cle()
        with mock.patch.object(views.requests, 'post',
                               return_value=_reponse_mistral(500, {'message': 'détail interne'})):
            resp = self.ocr()
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn('code', resp.json())
        self.assertNotIn('détail interne', resp.content.decode())
        self.assertNotIn('corps du fournisseur', resp.content.decode())

        with mock.patch.object(views.requests, 'post',
                               side_effect=requests.ConnectionError(f'échec avec Bearer {CLE}')), \
                self.assertLogs('api.views', 'WARNING') as journal:
            resp = self.ocr()
        self.assertEqual(resp.status_code, 502)
        self.assertNotIn('SECRETE', resp.content.decode())
        self.assertNotIn('SECRETE', '\n'.join(journal.output))

        reponse_illisible = _reponse_mistral(200)
        reponse_illisible.json.side_effect = ValueError('pas du JSON')
        with mock.patch.object(views.requests, 'post', return_value=reponse_illisible):
            self.assertEqual(self.ocr().status_code, 502)

    def test_delai_depasse_504(self):
        self.deposer_cle()
        with mock.patch.object(views.requests, 'post', side_effect=requests.Timeout('lent')):
            resp = self.ocr()
        self.assertEqual(resp.status_code, 504)
        self.assertNotIn('lent', resp.content.decode())
