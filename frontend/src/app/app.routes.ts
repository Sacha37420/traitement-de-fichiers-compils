import { Routes } from '@angular/router';

export const routes: Routes = [
  { path: '',        redirectTo: 'atelier', pathMatch: 'full' },
  { path: 'atelier', loadComponent: () => import('./pages/atelier/atelier').then(m => m.AtelierComponent) },
  { path: '**',      redirectTo: 'atelier' },
];
