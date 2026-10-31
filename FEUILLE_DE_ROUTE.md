# Feuille de route — traitement-de-fichiers-compils

Ce fichier est lu par une machine : `validate-app.sh` refuse de déployer s'il manque ou s'il ne
contient aucun lot au format ci-dessous, et `app-test.sh` lit la commande de test. Garder les titres
tels quels.

App livrée avant l'obligation de feuille de route : le Lot 1 résume l'existant. Les lots suivants
viennent de l'analyse du 2026-10-31 ; la vue d'ensemble est dans `to_do_global.md`, à la racine du
dépôt du lab. Légende : [C] constaté, [D] déduit.

**Pas de test de cloisonnement navigateur, à dessein** : la page est publique (`check-sso`) et
l'atelier tourne dans le navigateur. La protection tient dans l'API (groupe `developers`, propriétaire
et destinataires des partages), et ses tests backend la vérifient. Une exemption déclarée est à
ajouter à `validate-app.sh` (chantier T1).

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

## Lot 4 — Gabarit front et documentation   ·   statut : en cours
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
- [ ] Interception Playwright : aucun en-tête `Authorization` vers une autre origine que l'API
- [ ] WOFF2 en 200
**Vérifié le :** 2026-11-01 — `bash chantiers/tests/essai.sh traitement-de-fichiers-compils` : 73 tests, OK ; `npx ng build` sans erreur — non déployé ; vérifications navigateur à faire après déploiement.

## Lot 5 — Évolutions possibles   ·   statut : à faire
**Objectif :** pistes notées pendant la refonte, à confirmer par l'usage (Ⓟ).
**Tâches :**
- [ ] Partage à un groupe LDAP
- [ ] « Tout télécharger » en zip
- [ ] Aperçu HTML/SVG (jamais rendu dans la page : passer par un bac à sable)
**Tests à passer avant de clore le lot :**
- [ ] À définir avec chaque tâche retenue
**Vérifié le :**
