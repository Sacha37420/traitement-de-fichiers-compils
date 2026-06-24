import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';

interface EnvWindow { __env?: { apiUrl?: string } }

export interface Fichier {
  id: number;
  nom: string;
  type: string;
  tags: string[];
  metadonnees: Record<string, unknown>;
  taille_fichier: number;
  fichier_type_mime: string;
  droits_acces: string;
  date_upload?: string;
  utilisateur: string | null;
}

export interface Modification {
  id: number;
  date: string;
  action: string;
  details: Record<string, unknown> | null;
  utilisateur: string | null;
}

export interface PaginatedResponse<T> {
  count: number;
  next: string | null;
  previous: string | null;
  results: T[];
}

@Injectable({ providedIn: 'root' })
export class FichierService {
  private http = inject(HttpClient);

  private get base(): string {
    return (window as unknown as EnvWindow).__env?.apiUrl ?? 'http://localhost:8089';
  }

  uploadFichier(formData: FormData): Observable<Fichier> {
    return this.http.post<Fichier>(`${this.base}/api/fichiers/`, formData);
  }

  enregistrerFichier(data: { nom: string; fichier_id?: number; tags?: string[]; metadonnees?: Record<string, unknown> }): Observable<Fichier> {
    return this.http.post<Fichier>(`${this.base}/api/fichiers/enregistrer/`, data);
  }

  getMesFichiers(params: { type?: string; tag?: string; page?: number } = {}): Observable<PaginatedResponse<Fichier>> {
    let httpParams = new HttpParams();
    if (params.type) httpParams = httpParams.set('type', params.type);
    if (params.tag) httpParams = httpParams.set('tag', params.tag);
    if (params.page) httpParams = httpParams.set('page', params.page);
    return this.http.get<PaginatedResponse<Fichier>>(`${this.base}/api/fichiers/mes-fichiers/`, { params: httpParams });
  }

  getFichier(id: number): Observable<Fichier> {
    return this.http.get<Fichier>(`${this.base}/api/fichiers/${id}/`);
  }

  downloadUrl(id: number): string {
    return `${this.base}/api/fichiers/${id}/download/`;
  }

  getModifications(fichierId: number): Observable<PaginatedResponse<Modification>> {
    return this.http.get<PaginatedResponse<Modification>>(`${this.base}/api/fichiers/${fichierId}/modifications/`);
  }

  appliquerAction(fichierId: number, action: string, details: Record<string, unknown> = {}, preview = false): Observable<unknown> {
    return this.http.post<unknown>(`${this.base}/api/fichiers/${fichierId}/actions/`, { action, details, preview });
  }
}
