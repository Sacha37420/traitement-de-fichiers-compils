"""Verrou 2 — la serrure de l'API (CLAUDE.md, « Sécurité — cloisonnement »).

De vrais jetons RS256 passent par ``KeycloakJWTAuthentication`` ; seul le
téléchargement du JWKS est remplacé. Le lab est exposé sur Internet : chaque
refus ci-dessous ferme un chemin d'entrée réel.
"""
import time
import unittest

import jwt
from rest_framework.test import APIClient

from api import urls as api_urls
from .socle import AUTRE_RSA, CLIENT, KID, SocleTestCase, _RSA, jeton

ROUTES = ['/api/fichiers/', '/api/fichiers/partages/', '/api/fichiers/1/', '/api/fichiers/1/partages/']


class SerrureTests(SocleTestCase):

    def appel(self, tok: str | None, path='/api/fichiers/', methode='get'):
        c = APIClient()
        if tok is not None:
            c.credentials(HTTP_AUTHORIZATION=f'Bearer {tok}')
        return getattr(c, methode)(path)

    def test_un_membre_du_groupe_entre(self):
        resp = self.appel(jeton('alice@exemple.org', ['amis', 'developers']))
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(self.jwks_fetch.call_count, 1)   # la clé vient bien du JWKS (simulé)

    def test_sans_jeton_rien_ne_repond(self):
        # Inventaire tiré de api/urls.py : une route ajoutée doit passer par ici.
        self.assertEqual(len(ROUTES), len(api_urls.urlpatterns))
        for path in ROUTES:
            for methode in ('get', 'post', 'put', 'patch', 'delete'):
                with self.subTest(path=path, methode=methode):
                    self.assertIn(self.appel(None, path, methode).status_code, (401, 403))

    def test_entete_qui_n_est_pas_un_bearer(self):
        for entete in ('Basic YWxpY2U6eA==', 'bearer ' + jeton(), jeton()):
            with self.subTest(entete=entete[:12]):
                c = APIClient()
                c.credentials(HTTP_AUTHORIZATION=entete)
                self.assertIn(c.get('/api/fichiers/').status_code, (401, 403))

    def test_jeton_d_un_autre_client_refuse(self):
        # admin-cli : client public du realm, password grant — tout compte du
        # realm en obtient un jeton sans jamais croiser le flow du navigateur.
        for azp in ('admin-cli', 'storage', f'{CLIENT}-admin', 'account', '', None):
            with self.subTest(azp=azp):
                resp = self.appel(jeton(azp=azp))
                self.assertEqual(resp.status_code, 403)
                self.assertIn('autre client', resp.json()['detail'])

    def test_jeton_sans_azp_refuse(self):
        tok = jwt.encode({'email': 'alice@exemple.org', 'groups': ['developers'],
                          'exp': int(time.time()) + 300}, _RSA, algorithm='RS256', headers={'kid': KID})
        self.assertEqual(self.appel(tok).status_code, 403)

    def test_hors_du_groupe_requis_refuse(self):
        # Un nouvel inscrit n'a aucun groupe : il n'entre nulle part.
        for groups in ([], None, ['amis'], ['famille', 'admins'], ['Developers'], ['developers-x'], 'developers-x'):
            with self.subTest(groups=groups):
                resp = self.appel(jeton(groups=groups))
                self.assertEqual(resp.status_code, 403)
                self.assertIn('groupe(s)', resp.json()['detail'])

    def test_jeton_expire_refuse(self):
        resp = self.appel(jeton(exp=-30))
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Token invalide', resp.json()['detail'])

    def test_signature_d_une_autre_cle_refusee(self):
        # Même kid, mêmes claims, clé privée de l'attaquant.
        resp = self.appel(jeton(cle=AUTRE_RSA))
        self.assertEqual(resp.status_code, 403)
        self.assertIn('Token invalide', resp.json()['detail'])

    def test_charge_utile_modifiee_apres_signature_refusee(self):
        entete, _, signature = jeton(groups=['amis']).split('.')
        _, charge, _ = jeton(groups=['developers']).split('.')
        self.assertEqual(self.appel(f'{entete}.{charge}.{signature}').status_code, 403)

    def test_algorithmes_detournes_refuses(self):
        claims = {'azp': CLIENT, 'email': 'alice@exemple.org', 'groups': ['developers'],
                  'exp': int(time.time()) + 300}
        sans_signature = jwt.encode(claims, None, algorithm='none', headers={'kid': KID})
        hs256 = jwt.encode(claims, 'x' * 48, algorithm='HS256', headers={'kid': KID})
        for nom, tok in (('none', sans_signature), ('HS256', hs256), ('charabia', 'pas.un.jeton'), ('vide', '')):
            with self.subTest(cas=nom):
                self.assertEqual(self.appel(tok).status_code, 403)

    def test_jeton_sans_email_refuse(self):
        # Compte de service ou compte sans adresse : toute l'autorisation de
        # l'app repose sur l'email (Fichier.proprietaire, Partage.destinataire).
        for email in (None, ''):
            with self.subTest(email=email):
                resp = self.appel(jeton(email=email))
                self.assertEqual(resp.status_code, 403)
                self.assertIn('email', resp.json()['detail'])

    def test_cle_inconnue_ne_donne_aucun_acces(self):
        c = APIClient(raise_request_exception=False)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {jeton(kid='cle-inconnue')}")
        self.assertNotIn(c.get('/api/fichiers/').status_code, range(200, 400))

    # DÉFAUT (I4) — api/authentication.py n'intercepte que InvalidTokenError ;
    # PyJWKClient lève PyJWKClientError (clé `kid` absente du JWKS, ou Keycloak
    # injoignable), qui n'en hérite pas : la requête finit en erreur 500 non
    # gérée au lieu d'un refus 401/403. L'accès reste fermé (test ci-dessus),
    # mais n'importe qui provoque des 500 à volonté avec un jeton forgé.
    @unittest.expectedFailure
    def test_cle_inconnue_repond_un_refus_propre(self):
        c = APIClient(raise_request_exception=False)
        c.credentials(HTTP_AUTHORIZATION=f"Bearer {jeton(kid='cle-inconnue')}")
        self.assertIn(c.get('/api/fichiers/').status_code, (401, 403))
