"""Socle commun des tests : vrais jetons RS256 et faux réseau.

Deux remplacements, tous deux au plus bas niveau possible :

* ``PyJWKClient.fetch_data`` — le TÉLÉCHARGEMENT du JWKS de Keycloak rend une clé
  publique locale. Recherche de la clé par ``kid``, signature, expiration, ``azp``,
  groupes, email : tout le reste de ``KeycloakJWTAuthentication`` tourne pour de vrai.
* ``HTTPAdapter.send`` — l'envoi d'une requête par ``requests``. ``storage_client``
  prépare donc réellement ses requêtes (URL normalisée, en-têtes, corps) ; elles
  arrivent dans ``FauxReseau``, qui joue Keycloak (jeton du compte de service) et
  l'API de ``storage`` (routes de ``storage/backend/api/urls.py``).
"""
from __future__ import annotations

import json
import re
import time
from unittest import mock
from urllib.parse import parse_qs, unquote, urlsplit

import jwt
import requests
from cryptography.hazmat.primitives.asymmetric import rsa
from django.test import TestCase, override_settings
from rest_framework.test import APIClient

from api import storage_client
from api.authentication import KeycloakJWTAuthentication
from api.models import Fichier

CLIENT = 'traitement-de-fichiers-compils'
GROUPE = 'developers'
KID = 'cle-locale-de-test'
JETON_SERVICE = 'jeton-du-compte-de-service'
SECRET_SERVICE = 'secret-de-test'

_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)
AUTRE_RSA = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks() -> dict:
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(_RSA.public_key())
    jwk = json.loads(jwk) if isinstance(jwk, str) else dict(jwk)
    jwk.update({'kid': KID, 'use': 'sig', 'alg': 'RS256'})
    return {'keys': [jwk]}


_ABSENT = object()


def jeton(email=_ABSENT, groups=_ABSENT, *, azp=CLIENT, exp=300, cle=None, kid=KID, **claims) -> str:
    """Un jeton d'accès comme Keycloak en émet, signé par la clé locale."""
    payload = {'azp': azp, 'exp': int(time.time()) + exp, 'iat': int(time.time()) - 1}
    if email is _ABSENT:
        email = 'alice@exemple.org'
    if email is not None:
        payload['email'] = email
        payload['preferred_username'] = email.split('@')[0]
    if groups is _ABSENT:
        groups = [GROUPE]
    if groups is not None:
        payload['groups'] = groups
    payload.update(claims)
    return jwt.encode(payload, cle or _RSA, algorithm='RS256', headers={'kid': kid})


def client_de(email: str, groups=_ABSENT) -> APIClient:
    c = APIClient()
    c.credentials(HTTP_AUTHORIZATION=f'Bearer {jeton(email, groups)}')
    return c


def _reponse(request, status: int, data=None) -> requests.Response:
    r = requests.Response()
    r.status_code = status
    r._content = b'' if data is None else json.dumps(data).encode()
    r.headers['Content-Type'] = 'application/json'
    r.url = request.url
    r.request = request
    return r


class FauxReseau:
    """Keycloak (jeton de service) + API de storage, en mémoire.

    ``partages`` : {nom du Share: {'fichiers': {chemin: octets}, 'membres': {email: rôle}}}.
    ``journal`` : (méthode, chemin) de chaque requête reçue, dans l'ordre.
    ``pannes`` : noms d'opération qui répondent 500 (``upload``, ``add_member``,
    ``remove_member``, ``delete_share``, ``token``) ; ``coupe`` : tout lève
    ``ConnectionError`` (service injoignable).
    """

    def __init__(self) -> None:
        self.partages: dict[str, dict] = {}
        self.journal: list[tuple[str, str]] = []
        self.autorisations: list[str] = []
        self.pannes: set[str] = set()
        self.coupe = False
        self.jetons_emis = 0

    # ── lecture commode pour les assertions ──────────────────────────────────
    def membres(self, namespace: str) -> dict:
        return self.partages[namespace]['membres']

    def appels(self, methode: str | None = None) -> list[tuple[str, str]]:
        return [a for a in self.journal
                if not a[1].startswith('/realms/') and (methode is None or a[0] == methode)]

    # ── le transport ─────────────────────────────────────────────────────────
    def send(self, adapter, request, **kwargs):
        if self.coupe:
            raise requests.ConnectionError('réseau fermé (simulé)')
        url = urlsplit(request.url)
        chemin = url.path          # brut : un `%2F` reste un caractère du segment, comme côté serveur
        self.journal.append((request.method, chemin))
        corps = request.body or b''
        if isinstance(corps, str):
            corps = corps.encode()
        elif not isinstance(corps, bytes):
            corps = corps.read()

        if url.netloc == 'keycloak.test':
            form = parse_qs(corps.decode())
            ok = (chemin == '/realms/ssolab/protocol/openid-connect/token'
                  and form.get('grant_type') == ['client_credentials']
                  and form.get('client_id') == [f'{CLIENT}-admin']
                  and form.get('client_secret') == [SECRET_SERVICE])
            if 'token' in self.pannes or not ok:
                return _reponse(request, 401, {'error': 'unauthorized_client'})
            self.jetons_emis += 1
            return _reponse(request, 200, {'access_token': JETON_SERVICE, 'expires_in': 300})

        if url.netloc != 'storage.test':
            raise AssertionError(f'appel réseau inattendu : {request.method} {request.url}')
        self.autorisations.append(request.headers.get('Authorization', ''))
        if request.headers.get('Authorization') != f'Bearer {JETON_SERVICE}':
            return _reponse(request, 403, {'detail': 'jeton refusé'})

        m = re.fullmatch(r'/api/files/([^/]+)/', chemin)
        if m and request.method == 'POST':
            if 'upload' in self.pannes:
                return _reponse(request, 500)
            ns = m.group(1)
            if not ns.startswith('tdfc-'):        # write_prefix du compte de service
                return _reponse(request, 403, {'detail': 'hors préfixe'})
            rp = re.search(rb'name="relative_path"\r\n\r\n(.*?)\r\n', corps).group(1).decode()
            contenu = re.search(rb'name="file"; filename="[^"]*"\r\n(?:[^\r\n]+\r\n)*\r\n(.*)\r\n--',
                                corps, re.S).group(1)
            share = self.partages.setdefault(ns, {'fichiers': {}, 'membres': {}})
            share['fichiers'][rp] = contenu
            return _reponse(request, 201, {'relative_path': rp, 'size': len(contenu)})

        m = re.fullmatch(r'/api/shares/([^/]+)/members/', chemin)
        if m and request.method == 'POST':
            if 'add_member' in self.pannes:
                return _reponse(request, 500)
            if m.group(1) not in self.partages:
                return _reponse(request, 404)
            form = parse_qs(corps.decode())
            email = form['member_email'][0].strip().lower()
            self.partages[m.group(1)]['membres'][email] = form.get('role', ['read'])[0]
            return _reponse(request, 201, {'member_email': email})

        m = re.fullmatch(r'/api/shares/([^/]+)/members/([^/]+)/', chemin)
        if m and request.method == 'DELETE':
            if 'remove_member' in self.pannes:
                return _reponse(request, 500)
            share = self.partages.get(m.group(1))
            membre = unquote(m.group(2))
            if share is None or membre not in share['membres']:
                return _reponse(request, 404)
            del share['membres'][membre]
            return _reponse(request, 204)

        m = re.fullmatch(r'/api/shares/([^/]+)/', chemin)
        if m and request.method == 'DELETE':
            if 'delete_share' in self.pannes:
                return _reponse(request, 500)
            if self.partages.pop(m.group(1), None) is None:
                return _reponse(request, 404)
            return _reponse(request, 204)

        return _reponse(request, 404, {'detail': f'route inconnue du faux storage : {chemin}'})


@override_settings(
    KEYCLOAK_CLIENT_ID=CLIENT,
    KEYCLOAK_REQUIRED_GROUPS=GROUPE,
    KEYCLOAK_ISSUER_URI='http://keycloak.test/realms/ssolab',
    KEYCLOAK_ADMIN_CLIENT_ID=f'{CLIENT}-admin',
    KEYCLOAK_ADMIN_CLIENT_SECRET=SECRET_SERVICE,
    STORAGE_INTERNAL_URL='http://storage.test',
    STORAGE_PUBLIC_BASE_URL='https://lab.test/storage-api',
    STORAGE_NAMESPACE_PREFIX='tdfc-',
    MAX_FICHIER_OCTETS=1024,
)
class SocleTestCase(TestCase):
    """Jetons réels + faux réseau, pour toutes les classes de test de l'app."""

    def setUp(self) -> None:
        super().setUp()
        # JWKS : seule la récupération est remplacée ; le client est recréé pour
        # que rien ne survive d'un test à l'autre (il est mis en cache sur la classe).
        KeycloakJWTAuthentication._jwks_client = None
        self.addCleanup(setattr, KeycloakJWTAuthentication, '_jwks_client', None)
        p = mock.patch('jwt.PyJWKClient.fetch_data', autospec=True, side_effect=lambda _self: _jwks())
        self.jwks_fetch = p.start()
        self.addCleanup(p.stop)

        self.reseau = FauxReseau()
        p = mock.patch('requests.adapters.HTTPAdapter.send', autospec=True, side_effect=self.reseau.send)
        p.start()
        self.addCleanup(p.stop)
        # Le jeton du compte de service est mis en cache dans le module.
        storage_client._token_cache.update({'value': '', 'exp': 0.0})
        self.addCleanup(storage_client._token_cache.update, {'value': '', 'exp': 0.0})

        self.alice = client_de('alice@exemple.org')
        self.bob = client_de('bob@exemple.org')
        self.carol = client_de('carol@exemple.org')

    # ── gestes d'utilisateur, par l'API réelle ───────────────────────────────
    def deposer(self, client, nom='rapport.pdf', contenu=b'%PDF-1.4 essai', mime='application/pdf',
                nom_saisi=None, **champs):
        """`nom` : nom du fichier envoyé ; `nom_saisi` : champ `nom` du formulaire."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        data = {'fichier': SimpleUploadedFile(nom, contenu, content_type=mime), **champs}
        if nom_saisi is not None:
            data['nom'] = nom_saisi
        return client.post('/api/fichiers/', data, format='multipart')

    def fichier_de(self, client, **kw) -> Fichier:
        resp = self.deposer(client, **kw)
        self.assertEqual(resp.status_code, 201, resp.content)
        return Fichier.objects.get(pk=resp.json()['id'])

    def partager(self, client, fichier, email):
        return client.post(f'/api/fichiers/{fichier.pk}/partages/', {'email': email}, format='json')
