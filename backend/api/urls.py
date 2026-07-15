from django.urls import path
from . import views

urlpatterns = [
    # Collection : liste de mes fichiers (GET) / upload (POST)
    path('fichiers/', views.FichiersView.as_view()),
    # Fichiers partagés avec moi (littéral avant <int:pk>)
    path('fichiers/partages/', views.PartagesAvecMoiView.as_view()),
    # Ressource : détail (GET, propriétaire ou destinataire) / suppression (DELETE, propriétaire)
    path('fichiers/<int:pk>/', views.FichierDetailView.as_view()),
    # Binaire (propriétaire ou destinataire)
    path('fichiers/<int:pk>/download/', views.FichierDownloadView.as_view()),
    # Partages d'un fichier : ajouter (POST) / retirer (DELETE) — propriétaire uniquement
    path('fichiers/<int:pk>/partages/', views.FichierPartagesView.as_view()),
]
