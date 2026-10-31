from django.urls import path
from . import views

urlpatterns = [
    # Collection : liste de mes fichiers (GET) / upload (POST)
    path('fichiers/', views.FichiersView.as_view()),
    # Fichiers partagés avec moi (littéral avant <int:pk>)
    path('fichiers/partages/', views.PartagesAvecMoiView.as_view()),
    # Ressource : détail (GET, propriétaire ou destinataire) / suppression (DELETE, propriétaire)
    path('fichiers/<int:pk>/', views.FichierDetailView.as_view()),
    # Pas de route de téléchargement ici : FichierSerializer.fichier_url pointe
    # désormais directement vers storage (accès direct navigateur → storage,
    # sécurisé par les ShareMember synchronisés dans FichierPartagesView).
    # Partages d'un fichier : ajouter (POST) / retirer (DELETE) — propriétaire uniquement
    path('fichiers/<int:pk>/partages/', views.FichierPartagesView.as_view()),
    # Coffre de la clé Mistral : GET « configurée ? », PUT dépôt / retrait (chaîne vide)
    path('ocr-key/', views.OcrKeyView.as_view()),
    # OCR par le serveur, avec la clé du coffre (multipart, champ « file »)
    path('ocr/', views.OcrView.as_view()),
]
