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

## Lot 2 — Contrôle des destinataires existants   ·   statut : à faire
**Objectif :** aucun partage déjà en base n'est refusé par la nouvelle validation des adresses.
**Tâches :**
- [ ] Jouer en lecture seule la requête SQL fournie dans `chantiers/tests/rapports/lora-fichiers.md` §(2) ; si elle rend des lignes, normaliser ces adresses
**Tests à passer avant de clore le lot :**
- [ ] La requête rend 0 ligne
**Vérifié le :**

## Lot 3 — Recette en navigateur réel   ·   statut : à faire
**Objectif :** prouver ce qui n'a jamais été vu en vrai navigateur : recadrage, filtres, rendu pdfjs,
aperçus vidéo, OCR, partage entre deux comptes.
**Tâches :**
- [ ] Parcours scripté dans `lab-runner`, avec `e2e_member` et `e2edev` : déposer, partager, ouvrir chez le destinataire, retirer le partage
**Tests à passer avant de clore le lot :**
- [ ] Le destinataire ouvre le fichier, puis reçoit 403 une fois le partage retiré
- [ ] Recadrage, filtres et rendu PDF produisent un fichier téléchargeable
**Vérifié le :**

## Lot 4 — Gabarit front et documentation   ·   statut : à faire
**Objectif :** même comportement que le gabarit corrigé (T3), et un README.
**Tâches :**
- [ ] Polices en chemin relatif (`styles.scss:3-11`) ; `pkceMethod: 'S256'`
- [ ] `tokenBases()` dans l'intercepteur — utile ici, l'app appelle un tiers (Mistral)
- [ ] `README.md` : but, traitements, OCR (clé gardée dans le navigateur, risque XSS accepté), partage, tests
**Tests à passer avant de clore le lot :**
- [ ] Interception Playwright : aucun en-tête `Authorization` vers une autre origine que l'API
- [ ] WOFF2 en 200
**Vérifié le :**

## Lot 5 — Évolutions possibles   ·   statut : à faire
**Objectif :** pistes notées pendant la refonte, à confirmer par l'usage (Ⓟ).
**Tâches :**
- [ ] Partage à un groupe LDAP
- [ ] « Tout télécharger » en zip
- [ ] Aperçu HTML/SVG (jamais rendu dans la page : passer par un bac à sable)
**Tests à passer avant de clore le lot :**
- [ ] À définir avec chaque tâche retenue
**Vérifié le :**
