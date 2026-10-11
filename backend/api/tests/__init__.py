"""Tests backend de traitement-de-fichiers-compils (chantier « tests », contrat v1).

Lancer, comme le fait le lanceur officiel (`scripts/app-test.sh`) :

    python manage.py test

Rien ne sort du conteneur : le JWKS de Keycloak, le point de jeton du compte de
service et l'API de `storage` sont remplacés au niveau du TRANSPORT (voir
`socle.py`) — le code de l'app (authentification, vues, `storage_client`)
s'exécute réellement.
"""
