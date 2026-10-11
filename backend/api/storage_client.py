"""Client minimal de l'API fichiers de l'app storage.

Le backend agit via le **service account** du client confidentiel compagnon
``traitement-de-fichiers-compils-admin`` (flux ``client_credentials``, créé par
la simple présence de ``.keycloak-service-account-roles`` — voir ce fichier :
aucun rôle Keycloak n'y est demandé, cette app n'administre pas le realm).

Pourquoi un compte de service plutôt que le forward du token de l'utilisateur
courant (variante ``carto-lab``) pour les ÉCRITURES : **l'autorisation est
portée par les modèles de cette app**, pas nativement par storage. Un fichier
est modifiable par son seul propriétaire (``Fichier.proprietaire``) — or
storage ne le sait pas. ``api/views.py`` (``_owned`` / ``_accessible``) décide
donc *avant* d'appeler ce module, qui reste un simple transport pour l'upload/
la suppression/la gestion des partages.

Depuis la synchronisation du modèle de partage (un ``Share`` storage PAR
FICHIER, cf. ``Fichier.storage_namespace`` et ``api/views.py``), storage
CONNAÎT en revanche qui peut *lire* un fichier donné (le propriétaire et les
destinataires de ``Partage``, répliqués en ``ShareMember`` à chaque
création/révocation) : la LECTURE ne passe donc plus par ce backend — le
frontend appelle storage directement avec le token de l'utilisateur courant
(cf. ``FichierSerializer.get_fichier_url``). C'est le compte de service qui
crée le Share (implicitement, au premier upload) et gère ses ``ShareMember`` ;
jamais un forward du token d'un utilisateur pour ces opérations d'écriture.

Choix : un ``Share`` par fichier (préfixe ``settings.STORAGE_NAMESPACE_PREFIX``,
``'tdfc-'`` par défaut), pas un par propriétaire ni un seul global. Un Share par
propriétaire regrouperait tous ses fichiers sous les mêmes ShareMember, ce qui
donnerait à n'importe quel destinataire d'UN SEUL fichier partagé un accès direct
à TOUS les fichiers de ce propriétaire (Partage est par fichier, pas par
propriétaire) — inapplicable ici sans perdre le cloisonnement. Le nom complet de
l'app (``traitement-de-fichiers-compils``, 30 caractères) ne laisse quasiment
plus de marge dans le budget de 64 caractères d'un slug storage une fois un
identifiant unique par fichier ajouté (cf. ``validate_namespace_slug``) : on
utilise donc l'abréviation compacte ``tdfc-`` (vérifié sans collision avec les
Share existants au moment de l'écriture).

Le partage PAR FICHIER n'a plus besoin d'exister au préalable : il est créé
automatiquement par storage au premier upload (``get_or_create`` dans
``api.permissions.resolve_namespace`` côté storage), dès lors que le compte de
service a un ``write_prefix`` configuré sur ``tdfc-`` via
``KEYCLOAK_SERVICE_WRITE_PREFIXES=traitement-de-fichiers-compils-admin:tdfc-``
(``storage/.env``).

L'ancien partage global unique (``settings.STORAGE_NAMESPACE`` =
``traitement-de-fichiers-compils``, ``KEYCLOAK_SERVICE_WRITE_SHARES``) reste
référencé ci-dessous par les fonctions historiques (``upload``/``download``/
``delete``, signature à un seul namespace implicite) : elles ne sont plus
utilisées par ``api/views.py`` mais restent nécessaires pour la marche arrière
de la migration ``0004_fichier_storage`` (qui les appelle par leur nom), donc
ne pas changer leur signature. Les nouvelles fonctions à namespace explicite
(``upload_to``/``download_from``/``add_member``/``remove_member``/
``delete_share``) portent le nouveau modèle par fichier.
"""
from __future__ import annotations

import time
from urllib.parse import quote

import requests
from django.conf import settings

_TIMEOUT = 30


class StorageClientError(RuntimeError):
    """Erreur de communication ou de configuration avec l'API storage."""


def _split_issuer() -> tuple[str, str]:
    issuer = (settings.KEYCLOAK_ISSUER_URI or '').rstrip('/')
    if '/realms/' not in issuer:
        raise StorageClientError(
            f"KEYCLOAK_ISSUER_URI invalide : {issuer!r} (attendu …/realms/<realm>)."
        )
    base, realm = issuer.split('/realms/', 1)
    return base, realm.split('/', 1)[0]


# Cache de token au niveau process (chaque worker gunicorn a le sien).
_token_cache: dict[str, float | str] = {'value': '', 'exp': 0.0}


def _token() -> str:
    now = time.time()
    if _token_cache['value'] and float(_token_cache['exp']) > now + 5:
        return str(_token_cache['value'])

    client_id = getattr(settings, 'KEYCLOAK_ADMIN_CLIENT_ID', '') or ''
    secret = getattr(settings, 'KEYCLOAK_ADMIN_CLIENT_SECRET', '') or ''
    if not client_id or not secret:
        raise StorageClientError(
            "KEYCLOAK_ADMIN_CLIENT_ID / KEYCLOAK_ADMIN_CLIENT_SECRET manquants. "
            "Lancez setup2.sh traitement-de-fichiers-compils (provisionne le "
            "client traitement-de-fichiers-compils-admin)."
        )

    base, realm = _split_issuer()
    try:
        resp = requests.post(
            f'{base}/realms/{realm}/protocol/openid-connect/token',
            data={
                'grant_type': 'client_credentials',
                'client_id': client_id,
                'client_secret': secret,
            },
            timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageClientError(f'Keycloak injoignable : {exc}') from exc
    if resp.status_code != 200:
        raise StorageClientError(
            f"Auth service account échouée (HTTP {resp.status_code}) : {resp.text[:200]}"
        )
    data = resp.json()
    _token_cache['value'] = data['access_token']
    _token_cache['exp'] = now + int(data.get('expires_in', 60))
    return str(_token_cache['value'])


def _headers() -> dict[str, str]:
    return {'Authorization': f'Bearer {_token()}'}


def _files_url(suffix: str = '') -> str:
    return (
        f'{settings.STORAGE_INTERNAL_URL}/api/files/'
        f'{settings.STORAGE_NAMESPACE}/{suffix}'
    )


def upload(relative_path: str, fileobj, filename: str, content_type: str = '') -> dict:
    """Dépose `fileobj` sous `relative_path`. Écrase un fichier déjà présent au
    même chemin. Retourne le JSON de StoredFileSerializer (voir
    storage/backend/api/views.py)."""
    files = {'file': (filename, fileobj, content_type or 'application/octet-stream')}
    try:
        resp = requests.post(
            _files_url(), headers=_headers(),
            data={'relative_path': relative_path}, files=files, timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageClientError(f'storage injoignable : {exc}') from exc
    if resp.status_code != 201:
        raise StorageClientError(
            f'Upload storage échoué (HTTP {resp.status_code}) : {resp.text[:200]}'
        )
    return resp.json()


def download(relative_path: str) -> requests.Response:
    """Historique — namespace implicite (`settings.STORAGE_NAMESPACE`). Ne sert
    plus qu'à la marche arrière de la migration 0004_fichier_storage ; le
    chemin de lecture applicatif utilise désormais `download_from` (ou, pour
    l'essentiel des cas, plus aucun appel serveur : cf. FichierSerializer).
    Retourne la réponse streamée (`stream=True`) — à l'appelant de la consommer
    et de la fermer."""
    try:
        resp = requests.get(
            _files_url(f'content/{relative_path}'), headers=_headers(),
            stream=True, timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageClientError(f'storage injoignable : {exc}') from exc
    if resp.status_code != 200:
        raise StorageClientError(f'Téléchargement storage échoué (HTTP {resp.status_code}).')
    return resp


def delete(relative_path: str) -> None:
    try:
        resp = requests.delete(
            _files_url(f'content/{relative_path}'), headers=_headers(), timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageClientError(f'storage injoignable : {exc}') from exc
    if resp.status_code not in (204, 404):
        raise StorageClientError(f'Suppression storage échouée (HTTP {resp.status_code}).')


# ── Modèle par fichier (un Share storage par Fichier) ───────────────────────
# Namespace explicite en premier argument, plutôt qu'implicite via
# settings.STORAGE_NAMESPACE comme les fonctions historiques ci-dessus.

def _files_url_in(namespace: str, suffix: str = '') -> str:
    return f'{settings.STORAGE_INTERNAL_URL}/api/files/{namespace}/{suffix}'


def _shares_url(suffix: str = '') -> str:
    return f'{settings.STORAGE_INTERNAL_URL}/api/shares/{suffix}'


def upload_to(namespace: str, relative_path: str, fileobj, filename: str, content_type: str = '') -> dict:
    """Dépose `fileobj` sous `relative_path` dans le Share `namespace`. Le
    Share est créé automatiquement par storage au premier upload si `namespace`
    commence par `settings.STORAGE_NAMESPACE_PREFIX` (cf. `write_prefix` /
    `KEYCLOAK_SERVICE_WRITE_PREFIXES` côté storage)."""
    files = {'file': (filename, fileobj, content_type or 'application/octet-stream')}
    try:
        resp = requests.post(
            _files_url_in(namespace), headers=_headers(),
            data={'relative_path': relative_path}, files=files, timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageClientError(f'storage injoignable : {exc}') from exc
    if resp.status_code != 201:
        raise StorageClientError(
            f'Upload storage échoué (HTTP {resp.status_code}) : {resp.text[:200]}'
        )
    return resp.json()


def download_from(namespace: str, relative_path: str) -> requests.Response:
    """Retourne la réponse streamée (`stream=True`) — à l'appelant de la
    consommer et de la fermer. Utilisé par la migration de données (relire un
    fichier déjà transféré) ; le chemin de lecture applicatif normal n'appelle
    plus ce module du tout (accès direct navigateur → storage)."""
    try:
        resp = requests.get(
            _files_url_in(namespace, f'content/{relative_path}'), headers=_headers(),
            stream=True, timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageClientError(f'storage injoignable : {exc}') from exc
    if resp.status_code != 200:
        raise StorageClientError(f'Téléchargement storage échoué (HTTP {resp.status_code}).')
    return resp


def delete_share(namespace: str) -> None:
    """Supprime le Share `namespace` en entier — cascade côté storage sur ses
    fichiers ET ses ShareMember (cf. storage/backend/api/views.py,
    ShareDetailView). Utilisé à la suppression d'un Fichier : plus simple et
    plus propre qu'un delete de fichier isolé, puisque le Share est
    dédié à ce seul Fichier."""
    try:
        resp = requests.delete(_shares_url(f'{namespace}/'), headers=_headers(), timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise StorageClientError(f'storage injoignable : {exc}') from exc
    if resp.status_code not in (204, 404):
        raise StorageClientError(f'Suppression storage échouée (HTTP {resp.status_code}).')


def add_member(namespace: str, email: str, role: str = 'read') -> dict:
    """Autorise `email` sur le Share `namespace` (POST .../members/, idempotent
    côté storage : get_or_create). Le compte de service est propriétaire de
    tout Share qu'il a auto-créé via write_prefix, donc habilité à en gérer les
    membres (cf. storage/backend/api/permissions.py, get_owned_share)."""
    try:
        resp = requests.post(
            _shares_url(f'{namespace}/members/'), headers=_headers(),
            data={'member_email': email, 'role': role}, timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageClientError(f'storage injoignable : {exc}') from exc
    if resp.status_code != 201:
        raise StorageClientError(
            f"Ajout du membre '{email}' échoué (HTTP {resp.status_code}) : {resp.text[:200]}"
        )
    return resp.json()


def remove_member(namespace: str, email: str) -> None:
    """Révoque `email` sur le Share `namespace`. 404 toléré (déjà retiré / jamais
    membre) — c'est l'état final recherché, pas une erreur pour l'appelant."""
    try:
        resp = requests.delete(
            # `email` vient de l'appelant : encodé en entier (safe=''), sinon un
            # `/` ou un `..` changerait la ressource visée (requests normalise
            # les segments `..` avant l'envoi).
            _shares_url(f"{namespace}/members/{quote(email, safe='')}/"),
            headers=_headers(), timeout=_TIMEOUT,
        )
    except requests.RequestException as exc:
        raise StorageClientError(f'storage injoignable : {exc}') from exc
    if resp.status_code not in (204, 404):
        raise StorageClientError(
            f"Retrait du membre '{email}' échoué (HTTP {resp.status_code})."
        )
