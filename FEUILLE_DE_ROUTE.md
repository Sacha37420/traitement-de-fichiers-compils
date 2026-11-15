# Feuille de route — traitement-de-fichiers-compils

Ce fichier est lu par une machine : `validate-app.sh` refuse de déployer s'il manque ou s'il ne
contient aucun lot au format ci-dessous, et `app-test.sh` lit la commande de test. Garder les titres
tels quels.

App livrée avant l'obligation de feuille de route : le Lot 1 résume l'existant. Les lots suivants
viennent de l'analyse du 2026-10-31 ; la vue d'ensemble est dans `to_do_global.md`, à la racine du
dépôt du lab. Légende : [C] constaté, [D] déduit.

**Pas de test de cloisonnement navigateur, à dessein** : la page est publique (`check-sso`) et
l'atelier tourne dans le navigateur. La protection tient dans l'API (groupe `developers`, propriétaire
et destinataires des partages), et ses tests backend la vérifient. La ligne suivante est l'exemption
déclarée que lit `validate-app.sh` (réservée aux apps du superutilisateur) :

cloisonnement : aucun — page publique en check-sso, protection dans l'API, tenue par ses tests backend

## Commande de test
python manage.py test

## Lot 1 — Existant : atelier dans le navigateur, dépôt et partage par email   ·   statut : livré
**Objectif :** traitements d'images, de PDF et de vidéo dans le navigateur, OCR par Mistral appelé
depuis le navigateur. Le backend ne sert qu'au dépôt et au partage par email (octets dans `storage`,
compte de service).
**Tâches :**
- [x] Refonte « client-first » (lot 1 du projet) ; fichiers migrés vers `storage` (migration `0004`)
- [x] Huit correctifs du chantier tests : traversée de chemin, nom trop long, type MIME trop long, `kid`…
**Tests à passer avant de clore le lot :**
- [x] 57 tests backend
**Vérifié le :** 2026-10-31 — relevé par lecture (version en service = `18b8ab7`), tests non rejoués.

## Lot 2 — Contrôle des destinataires existants   ·   statut : livré
**Objectif :** aucun partage déjà en base n'est refusé par la nouvelle validation des adresses.
**Tâches :**
- [x] Jouer en lecture seule la requête SQL fournie dans `chantiers/tests/rapports/lora-fichiers.md` §(2) ; si elle rend des lignes, normaliser ces adresses
**Tests à passer avant de clore le lot :**
- [x] La requête rend 0 ligne
**Vérifié le :** 2026-11-01 — jouée dans une transaction `READ ONLY` sur `dev_sacha`, schéma `traitement_de_fichiers_compils` : 0 ligne, la table `partages` étant vide (0 partage en base). Expression contrôlée sur un écart provoqué : `a/b@c` et `a\b@c` refusées, `x@y.fr` acceptée. Rien à normaliser.

## Lot 3 — Recette en navigateur réel   ·   statut : à faire
**Objectif :** prouver ce qui n'a jamais été vu en vrai navigateur : recadrage, filtres, rendu pdfjs,
aperçus vidéo, OCR, partage entre deux comptes.
**Tâches :**
- [ ] Parcours scripté dans `lab-runner`, avec `e2e_member` et `e2edev` : déposer, partager, ouvrir chez le destinataire, retirer le partage
**Tests à passer avant de clore le lot :**
- [ ] Le destinataire ouvre le fichier, puis reçoit 403 une fois le partage retiré
- [ ] Recadrage, filtres et rendu PDF produisent un fichier téléchargeable
**Vérifié le :**

## Lot 4 — Gabarit front et documentation   ·   statut : livré
**Objectif :** même comportement que le gabarit corrigé (T3), et un README.
**Tâches :**
- [x] Polices en chemin relatif (`styles.scss:3-11`) ; `pkceMethod: 'S256'`
- [x] `tokenBases()` dans l'intercepteur : API de l'app et `…/storage-api/api/files` (lus directement par le navigateur) ; `storageUrl` ajouté à `env.js`
- [x] `check-sso` gardé tel quel (page publique) ; `login()` revient sur la page courante (`redirect-uri.ts` de lab-admin)
- [x] Clé Mistral hors du navigateur (chantier « failles », I3) : coffre par compte (`ocr_key_vault`, migration `0006`, `VAULT_ENCRYPTION_KEY`) ; `GET`/`PUT /api/ocr-key/` (`mistral_key_configured` seulement) ; OCR par `POST /api/ocr/` (20 Mo au plus, 413 avant lecture ; PDF, PNG, JPEG, WebP, GIF), le serveur appelle Mistral ; ancienne entrée `mistral_api_key` effacée de `localStorage`. L'OCR demande désormais d'être connecté ; les autres opérations restent anonymes
- [x] Ports liés à `${LAB_BIND_ADDR:-127.0.0.1}`
- [x] `README.md` : but, traitements, OCR (par le serveur, coffre chiffré), partage, tests
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test api.tests.test_coffre` passe (configured seul, chiffré en base, clé d'autrui ni lue ni utilisée, autre `azp` refusé, Mistral simulé recevant la clé du coffre, 413, 502/504)
- [x] Interception Playwright : aucun en-tête `Authorization` vers une autre origine que l'API — vérifié le 2026-11-01 (lab-runner, `e2e_member`)
- [x] WOFF2 en 200 — vérifié le 2026-11-01 (lab-runner, `e2e_member`)
**Vérifié le :** 2026-11-01 — `bash chantiers/tests/essai.sh traitement-de-fichiers-compils` : 73 tests, OK ; `npx ng build` sans erreur — non déployé ; vérifications navigateur à faire après déploiement.
Statut passé à « livré » le 2026-11-08 (relecture de nuit) : toutes les tâches et tous les tests cochés (navigateur le 2026-11-01, commit `6e12c17`), mis en service le 2026-11-01 (section « Mise en service » ; `scripts/app-status.sh` : déploiement `3feb3bc`, backend `ok`). README relu contre `backend/api/urls.py` et `config/settings.py:156,163` : juste.

## Lot 5 — Évolutions possibles   ·   statut : à faire
**Objectif :** pistes notées pendant la refonte, à confirmer par l'usage (Ⓟ).
**Tâches :**
- [ ] Partage à un groupe LDAP
- [ ] « Tout télécharger » en zip
- [ ] Aperçu HTML/SVG (jamais rendu dans la page : passer par un bac à sable)
**Tests à passer avant de clore le lot :**
- [ ] À définir avec chaque tâche retenue
**Vérifié le :**

## Lot 6 — Dossiers et hiérarchie storage   ·   statut : en cours
**Objectif :** chantier « storage-hierarchie » (contrat v2, `chantiers/storage-hierarchie/` du lab) :
plus de centaines de partages `tdfc-…` à la racine de storage. Tout partage de l'app est rangé sous
le conteneur `traitement-de-fichiers-compils` (au compte de service) ; les images extraites d'une
vidéo vont dans un **Dossier** (un seul partage `tdfc-d-<hex>`, noms lisibles) ; un fichier isolé
ou partagé garde un partage à lui (partager un fichier n'ouvre jamais les autres).
**Tâches :**
- [x] Modèle `Dossier` (table `dossiers`), `Fichier.dossier` (PROTECT), migration `0007` sans appel réseau
- [x] `storage_client.create_share` : création explicite avant l'upload, rattachée au conteneur ou au partage du dossier ; jamais un dépôt en échec à cause du rattachement (racine + avertissement)
- [x] API : `GET`/`POST /api/dossiers/`, `DELETE /api/dossiers/<id>/` (partages enfants d'abord) ; `dossier` à l'envoi (le mien seulement) ; `?dossier=<id>|aucun` ; partager un fichier d'un dossier le sort dans un partage enfant du dossier
- [x] Commande `python manage.py rattacher_partages_storage [--check]` (regroupe `<base>-frame-<N>`, déplace les octets, rattache), rejouable après interruption
- [x] Frontend : extraction d'images marquée d'un groupe (nom de la vidéo) → un dossier par groupe et par session à l'envoi ; « Mes fichiers » : colonne et filtre Dossier, suppression d'un dossier
- [ ] Après déploiement (architecte) : transfert du conteneur au compte de service (I0), `--check`, puis la commande
**Tests à passer avant de clore le lot :**
- [x] `python manage.py test` : 101 tests (dont `test_dossiers`, `test_rattacher` : dossier d'autrui refusé, destinataire jamais membre du dossier, reprise après interruption sans perte ni doublon, taille vérifiée)
- [x] `npx ng build` (production) sans erreur
- [ ] `rattacher_partages_storage --check` conclut « Rien à faire » sur les données réelles après la commande
**Vérifié le :** 2026-11-15 — `chantiers/tests/essai.sh` (clone `host/storage-hierarchie`) : 101 tests OK ; `makemigrations --check` : rien ; `ng build` OK. Non déployé, commande non jouée sur les données réelles.

## Mise en service — chantier « failles » (2026-11-01)
Les mentions « non déployé » ci-dessus datent d'avant cette mise en service. Image construite pendant
que l'ancienne tournait, `scripts/app-test.sh` : 73 tests OK, puis `up -d --no-build` ; ports
publiés sur `127.0.0.1` ; client Keycloak passé en PKCE S256 exigé, URI de retour réduites à celles de
l'app (`create-app-client.sh --pkce --prune-uris`) ; cloisonnement : aucun test navigateur à dessein (protection dans l'API).
Restent les vérifications en navigateur réel notées dans les lots (images, coffres de clés, envois).
