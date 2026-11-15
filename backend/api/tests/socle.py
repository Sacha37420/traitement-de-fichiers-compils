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


CONTENEUR = 'traitement-de-fichiers-compils'
SERVICE = 'service:traitement-de-fichiers-compils-admin'


class FauxReseau:
    """Keycloak (jeton de service) + API de storage, en mémoire.

    ``partages`` : {nom du Share: {'fichiers': {chemin: octets}, 'membres': {email: rôle},
    'parent': nom ou None, 'owner': propriétaire}} — le compte de service est ``SERVICE``.
    Règles reprises de storage (``api/views.py``, ``api/permissions.py``) : création
    explicite (``POST /api/shares/``, 400 ``name`` si pris, 400 ``parent`` si le parent
    manque ou n'est pas au même propriétaire), création implicite d'un partage préfixé
    ``tdfc-`` au premier accès fichier du compte de service, gestion réservée au
    propriétaire (403), suppression refusée (400) tant qu'il reste des enfants.
    ``journal`` : (méthode, chemin) de chaque requête reçue, dans l'ordre.
    ``pannes`` : noms d'opération qui répondent 500 (``upload``, ``add_member``,
    ``remove_member``, ``delete_share``, ``create_share``, ``patch``, ``download``,
    ``delete_file``, ``token``, ``refus_parent`` : 400 ``parent`` à toute création
    avec parent) ; ``coupe`` : tout lève ``ConnectionError``.
    ``taille_menteuse`` : l'upload rend une taille fausse (vérification de la commande).
    """

    def __init__(self) -> None:
        self.partages: dict[str, dict] = {}
        self.journal: list[tuple[str, str]] = []
        self.autorisations: list[str] = []
        self.pannes: set[str] = set()
        self.coupe = False
        self.jetons_emis = 0
        self.taille_menteuse = False

    # ── lecture commode pour les assertions ──────────────────────────────────
    def membres(self, namespace: str) -> dict:
        return self.partages[namespace]['membres']

    def parent(self, namespace: str):
        return self.partages[namespace]['parent']

    def appels(self, methode: str | None = None) -> list[tuple[str, str]]:
        return [a for a in self.journal
                if not a[1].startswith('/realms/') and (methode is None or a[0] == methode)]

    def creer(self, nom: str, *, owner: str = SERVICE, parent=None, fichiers=None, membres=None) -> dict:
        """Pose un partage tel qu'il existe déjà en service (données d'avant le chantier)."""
        self.partages[nom] = {'fichiers': dict(fichiers or {}), 'membres': dict(membres or {}),
                              'parent': parent, 'owner': owner}
        return self.partages[nom]

    def _implicite(self, ns: str):
        """resolve_namespace côté storage pour le compte de service : get_or_create
        sous le préfixe, 403 hors préfixe."""
        if not ns.startswith('tdfc-'):
            return None
        return self.partages.setdefault(ns, {'fichiers': {}, 'membres': {}, 'parent': None, 'owner': SERVICE})

    def _possede(self, request, nom):
        share = self.partages.get(nom)
        if share is None:
            return None, _reponse(request, 404)
        if share['owner'] != SERVICE:
            return None, _reponse(request, 403, {'detail': 'Seul le propriétaire du partage peut faire ceci.'})
        return share, None

    def _parent_valide(self, request, nom, parent):
        if not parent:
            return None, None
        p = self.partages.get(parent)
        if p is None:
            return None, _reponse(request, 400, {'parent': ['introuvable']})
        if parent == nom:
            return None, _reponse(request, 400, {'parent': ['soi-même']})
        if p['owner'] != SERVICE:
            return None, _reponse(request, 400, {'parent': ['Le partage parent doit appartenir au même propriétaire.']})
        return parent, None

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

        # ── partages ─────────────────────────────────────────────────────────
        if chemin == '/api/shares/' and request.method == 'POST':
            if 'create_share' in self.pannes:
                return _reponse(request, 500)
            form = parse_qs(corps.decode())
            nom = form.get('name', [''])[0].strip().lower()
            if nom in self.partages:
                return _reponse(request, 400, {'name': ['Ce nom de partage est déjà pris.']})
            demande = form.get('parent', [''])[0].strip().lower()
            if demande and 'refus_parent' in self.pannes:
                return _reponse(request, 400, {'parent': ['refusé (simulé)']})
            parent, err = self._parent_valide(request, nom, demande)
            if err is not None:
                return err
            self.creer(nom, parent=parent)
            return _reponse(request, 201, {'name': nom, 'owner_username': SERVICE, 'parent': parent})

        if chemin == '/api/shares/' and request.method == 'GET':
            owned = [{'name': n, 'owner_username': SERVICE, 'parent': sh['parent'], 'required_groups': ''}
                     for n, sh in self.partages.items() if sh['owner'] == SERVICE]
            return _reponse(request, 200, {'owned': owned, 'member_of': [], 'tree': []})

        m = re.fullmatch(r'/api/shares/([^/]+)/members/', chemin)
        if m and request.method == 'GET':
            share, err = self._possede(request, m.group(1))
            if err is not None:
                return err
            return _reponse(request, 200, [{'member_email': e, 'role': r} for e, r in share['membres'].items()])

        if m and request.method == 'POST':
            if 'add_member' in self.pannes:
                return _reponse(request, 500)
            share, err = self._possede(request, m.group(1))
            if err is not None:
                return err
            form = parse_qs(corps.decode())
            email = form['member_email'][0].strip().lower()
            share['membres'][email] = form.get('role', ['read'])[0]
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
        if m and request.method == 'PATCH':
            if 'patch' in self.pannes:
                return _reponse(request, 500)
            share, err = self._possede(request, m.group(1))
            if err is not None:
                return err
            form = parse_qs(corps.decode())
            if 'parent' not in form:
                return _reponse(request, 400, {'parent': ['Requis.']})
            parent, err = self._parent_valide(request, m.group(1), form['parent'][0].strip().lower())
            if err is not None:
                return err
            share['parent'] = parent
            return _reponse(request, 200, {'name': m.group(1), 'parent': parent})

        if m and request.method == 'DELETE':
            if 'delete_share' in self.pannes:
                return _reponse(request, 500)
            share, err = self._possede(request, m.group(1))
            if err is not None:
                return err
            if any(sh['parent'] == m.group(1) for sh in self.partages.values()):
                return _reponse(request, 400, {'detail': ['Ce partage a des enfants.']})
            del self.partages[m.group(1)]
            return _reponse(request, 204)

        # ── fichiers ─────────────────────────────────────────────────────────
        m = re.fullmatch(r'/api/files/([^/]+)/', chemin)
        if m and request.method == 'POST':
            if 'upload' in self.pannes:
                return _reponse(request, 500)
            share = self._implicite(m.group(1))
            if share is None:
                return _reponse(request, 403, {'detail': 'hors préfixe'})
            rp = re.search(rb'name="relative_path"\r\n\r\n(.*?)\r\n', corps).group(1).decode()
            contenu = re.search(rb'name="file"; filename="[^"]*"\r\n(?:[^\r\n]+\r\n)*\r\n(.*)\r\n--',
                                corps, re.S).group(1)
            share['fichiers'][rp] = contenu
            taille = len(contenu) + (1 if self.taille_menteuse else 0)
            return _reponse(request, 201, {'relative_path': rp, 'size': taille})

        if m and request.method == 'GET':
            share = self._implicite(m.group(1))
            if share is None:
                return _reponse(request, 403)
            return _reponse(request, 200, [{'relative_path': p, 'size': len(o)}
                                           for p, o in share['fichiers'].items()])

        m = re.fullmatch(r'/api/files/([^/]+)/content/(.+)', chemin)
        if m and request.method in ('GET', 'DELETE'):
            if request.method == 'GET' and 'download' in self.pannes:
                return _reponse(request, 500)
            if request.method == 'DELETE' and 'delete_file' in self.pannes:
                return _reponse(request, 500)
            share = self._implicite(m.group(1))
            if share is None:
                return _reponse(request, 403)
            rp = unquote(m.group(2))
            if rp not in share['fichiers']:
                return _reponse(request, 404)
            if request.method == 'DELETE':
                del share['fichiers'][rp]
                return _reponse(request, 204)
            r = requests.Response()
            r.status_code = 200
            r._content = share['fichiers'][rp]
            r._content_consumed = True
            r.headers['Content-Type'] = 'application/octet-stream'
            r.url = request.url
            r.request = request
            return r

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
    STORAGE_NAMESPACE=CONTENEUR,
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
        # Conteneur prêt : mémorisé par processus, remis à zéro à chaque test.
        storage_client._container_ready['ok'] = False
        self.addCleanup(storage_client._container_ready.update, {'ok': False})

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
