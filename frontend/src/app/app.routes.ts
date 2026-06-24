import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '',           redirectTo: 'traitement', pathMatch: 'full' },
  { path: 'upload',     loadComponent: () => import('./pages/upload/upload-fichier').then(m => m.UploadFichierComponent) },
  { path: 'traitement', loadComponent: () => import('./pages/traitement/traitement-fichiers').then(m => m.TraitementFichiersComponent) },
  { path: 'mes-fichiers', loadComponent: () => import('./pages/mes-fichiers/mes-fichiers').then(m => m.MesFichiersComponent) },
  { path: 'editeur/:type', loadComponent: () => import('./pages/editeur/editeur-fichier').then(m => m.EditeurFichierComponent) },
  { path: 'editeur/:type/:id', loadComponent: () => import('./pages/editeur/editeur-fichier').then(m => m.EditeurFichierComponent) },
  { path: 'fichiers/:id', loadComponent: () => import('./pages/detail/detail-fichier').then(m => m.DetailFichierComponent) },
  { path: 'fichiers/:id/historique', loadComponent: () => import('./pages/historique/historique-modifications').then(m => m.HistoriqueModificationsComponent) },
  { path: '**', redirectTo: 'upload' },
];
