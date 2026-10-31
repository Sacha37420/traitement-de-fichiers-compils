# Traitement de fichiers compilés

Atelier de fichiers du lab : importer des images, des PDF et des vidéos, les
transformer, puis les télécharger ou les garder sur le serveur et les partager.

## Ce qui se passe où

- **Traitements dans le navigateur.** Recadrage, conversion, pages d'un PDF,
  fusion, images d'une vidéo, vectorisation… : tout est fait dans la page, sans
  envoyer le fichier. L'atelier est utilisable **sans connexion** pour ces
  opérations.
- **OCR par le serveur.** L'opération « OCR → HTML (Mistral) » demande d'être
  connecté. Le navigateur envoie le document à l'API de l'app
  (`POST /api/ocr/`), qui appelle Mistral avec **la clé de l'utilisateur**, et
  la page met le résultat en forme (HTML autonome, images en ligne).
  - Coffre par utilisateur : la clé est envoyée une fois
    (`PUT /api/ocr-key/`), gardée **chiffrée** en base (`VAULT_ENCRYPTION_KEY`
    dans le `.env`) et **jamais renvoyée** — `GET /api/ocr-key/` ne dit que si
    elle est enregistrée. Une chaîne vide la retire. Le navigateur ne garde
    aucune clé.
  - Limite : 20 Mo par document (`OCR_MAX_OCTETS`). Types : PDF, PNG, JPEG,
    WebP, GIF.
- **Fichiers gardés sur le serveur.** Les octets vivent dans le service
  `storage` du lab ; cette app ne garde que les métadonnées et les droits.
- **Partage par email.** Le propriétaire d'un fichier le partage avec une
  adresse ; le destinataire le voit dans « Partagés avec moi » et peut le lire.
  Seul le propriétaire supprime ou retire un partage.

L'API est réservée aux membres du groupe requis de l'app (contrôle du client
émetteur du jeton et des groupes dans `backend/api/authentication.py`).

## Tests

```bash
cd backend
python manage.py test
```

Les tests n'appellent ni Keycloak, ni `storage`, ni Mistral : le réseau est
simulé (`backend/api/tests/socle.py`).
