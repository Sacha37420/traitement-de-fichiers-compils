from django.urls import path
from . import views

urlpatterns = [
    # Fichiers
    path('fichiers/', views.FichierUploadView.as_view()),
    path('fichiers/enregistrer/', views.FichierEnregistrerView.as_view()),
    path('fichiers/mes-fichiers/', views.MesFichiersView.as_view()),
    path('fichiers/<int:pk>/', views.FichierDetailView.as_view()),
    path('fichiers/<int:pk>/download/', views.FichierDownloadView.as_view()),
    path('fichiers/<int:pk>/modifications/', views.FichierModificationsView.as_view()),
    path('fichiers/<int:pk>/actions/', views.FichierActionsView.as_view()),
    # Preview temporaire
    path('preview/<str:token>/', views.PreviewDownloadView.as_view()),
    # Tags
    path('tags/', views.TagListView.as_view()),
    # Actions
    path('actions/', views.ActionListView.as_view()),
    # Workspace
    path('workspace/', views.WorkspaceView.as_view()),
    path('workspace/<int:pk>/finaliser/', views.WorkspaceFinaliserView.as_view()),
]
