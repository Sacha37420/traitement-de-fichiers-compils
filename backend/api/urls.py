from django.urls import path
from . import views

urlpatterns = [
    # Collection : liste de mes fichiers (GET) / upload (POST)
    path('fichiers/', views.FichiersView.as_view()),
    # Ressource : détail (GET) / suppression (DELETE)
    path('fichiers/<int:pk>/', views.FichierDetailView.as_view()),
    # Binaire
    path('fichiers/<int:pk>/download/', views.FichierDownloadView.as_view()),
]
