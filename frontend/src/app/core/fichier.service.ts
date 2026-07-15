import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

interface EnvWindow { __env?: { apiUrl?: string } }

/** Fichier tel que renvoyé par le backend (stockage propriétaire, sans traitement). */
export interface Fichier {
  id: number;
  nom: string;
  type: string;
  taille_fichier: number;
  date_upload: string;
  fichier_type_mime: string;
  proprietaire: string;
  /** Destinataires du partage — renseigné pour le propriétaire uniquement. */
  partages: string[];
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

/**
 * Accès au stockage backend des fichiers. Toutes les routes exigent une
 * authentification (le token est ajouté par authInterceptor) et sont cloisonnées
 * aux fichiers de l'utilisateur courant côté serveur.
 */
@Injectable({ providedIn: 'root' })
export class FichierService {
  private http = inject(HttpClient);

  private get base(): string {
    return (window as unknown as EnvWindow).__env?.apiUrl ?? 'http://localhost:8089';
  }

  /** Liste mes fichiers stockés sur le serveur. */
  getMesFichiers(params: { type?: string; page?: number } = {}): Observable<PaginatedResponse<Fichier>> {
    let httpParams = new HttpParams();
    if (params.type) httpParams = httpParams.set('type', params.type);
    if (params.page) httpParams = httpParams.set('page', params.page);
    return this.http.get<PaginatedResponse<Fichier>>(`${this.base}/api/fichiers/`, { params: httpParams });
  }

  /** Envoie un fichier (issu de l'atelier) au stockage backend. */
  uploadFichier(formData: FormData): Observable<Fichier> {
    return this.http.post<Fichier>(`${this.base}/api/fichiers/`, formData);
  }

  /** Récupère le binaire d'un de mes fichiers. */
  downloadBlob(id: number): Observable<Blob> {
    return this.http.get(`${this.base}/api/fichiers/${id}/download/`, { responseType: 'blob' });
  }

  /** Supprime un de mes fichiers. */
  deleteFichier(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/api/fichiers/${id}/`);
  }

  /** Fichiers que d'autres ont partagés avec moi. */
  getPartagesAvecMoi(params: { page?: number } = {}): Observable<PaginatedResponse<Fichier>> {
    let httpParams = new HttpParams();
    if (params.page) httpParams = httpParams.set('page', params.page);
    return this.http.get<PaginatedResponse<Fichier>>(`${this.base}/api/fichiers/partages/`, { params: httpParams });
  }

  /** Partage un de mes fichiers avec un email. */
  partager(id: number, email: string): Observable<Fichier> {
    return this.http.post<Fichier>(`${this.base}/api/fichiers/${id}/partages/`, { email });
  }

  /** Retire un partage d'un de mes fichiers. */
  retirerPartage(id: number, email: string): Observable<Fichier> {
    return this.http.delete<Fichier>(`${this.base}/api/fichiers/${id}/partages/`, { body: { email } });
  }
}
