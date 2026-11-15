import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable, shareReplay, throwError } from 'rxjs';
import { apiUrl } from './env';

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
  /**
   * URL storage complète (accès direct, cf. FichierService.downloadBlob) —
   * null si le fichier n'a pas (ou plus) de stockage associé. Sécurisée par un
   * ShareMember storage propre à ce fichier, synchronisé par ce backend à
   * chaque partage/révocation (cf. api/views.py côté backend) : pas besoin de
   * repasser par ce backend pour la lire, storage refait le contrôle d'accès.
   */
  fichier_url: string | null;
  /** Dossier du fichier — renseigné pour le propriétaire uniquement (null sinon). */
  dossier: { id: number; nom: string } | null;
}

/** Dossier de fichiers (ex. les images extraites d'une vidéo). */
export interface Dossier {
  id: number;
  nom: string;
  date_creation: string;
  nb_fichiers: number;
}

/** Filtre de la liste : un dossier (id), 'aucun' (hors dossier), ou rien. */
export type FiltreDossier = number | 'aucun' | null;

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
  /** Dossier créé pour chaque groupe pendant cette session (un seul par groupe). */
  private dossiersDeGroupe = new Map<string, Observable<Dossier>>();

  private get base(): string {
    return apiUrl();
  }

  /** Liste mes fichiers stockés sur le serveur. */
  getMesFichiers(params: { type?: string; page?: number; dossier?: FiltreDossier } = {}): Observable<PaginatedResponse<Fichier>> {
    let httpParams = new HttpParams();
    if (params.type) httpParams = httpParams.set('type', params.type);
    if (params.page) httpParams = httpParams.set('page', params.page);
    if (params.dossier !== null && params.dossier !== undefined) httpParams = httpParams.set('dossier', params.dossier);
    return this.http.get<PaginatedResponse<Fichier>>(`${this.base}/api/fichiers/`, { params: httpParams });
  }

  /** Envoie un fichier (issu de l'atelier) au stockage backend. */
  uploadFichier(formData: FormData): Observable<Fichier> {
    return this.http.post<Fichier>(`${this.base}/api/fichiers/`, formData);
  }

  /**
   * Récupère le binaire d'un fichier accessible (propriétaire ou
   * destinataire) — appel DIRECT à storage, pas à ce backend : authInterceptor
   * pose le même token Authorization qu'à toute requête HttpClient (même
   * origine sous Caddy, donc pas de CORS), et c'est storage qui vérifie
   * l'accès via le ShareMember du fichier. Nécessite fichier.fichier_url
   * (absent seulement pour un fichier sans stockage associé).
   */
  downloadBlob(fichier: Pick<Fichier, 'fichier_url'>): Observable<Blob> {
    if (!fichier.fichier_url) {
      return throwError(() => new Error('Ce fichier ne peut pas être téléchargé (stockage indisponible).'));
    }
    return this.http.get(fichier.fichier_url, { responseType: 'blob' });
  }

  /** Mes dossiers, avec leur nombre de fichiers. */
  getDossiers(): Observable<Dossier[]> {
    return this.http.get<Dossier[]>(`${this.base}/api/dossiers/`);
  }

  createDossier(nom: string): Observable<Dossier> {
    return this.http.post<Dossier>(`${this.base}/api/dossiers/`, { nom });
  }

  /** Supprime un dossier ET tous ses fichiers. */
  deleteDossier(id: number): Observable<void> {
    return this.http.delete<void>(`${this.base}/api/dossiers/${id}/`);
  }

  /**
   * Dossier du groupe `nom`, créé au premier envoi d'un fichier de ce groupe
   * pendant la session. Partagé entre envois simultanés (l'atelier envoie tous
   * les fichiers d'un coup) : un seul POST par groupe. Oublié en cas d'échec,
   * pour qu'un nouvel envoi réessaie.
   */
  dossierPourGroupe(nom: string): Observable<Dossier> {
    let d = this.dossiersDeGroupe.get(nom);
    if (!d) {
      d = this.createDossier(nom.slice(0, 200)).pipe(shareReplay(1));
      this.dossiersDeGroupe.set(nom, d);
      d.subscribe({ error: () => this.dossiersDeGroupe.delete(nom) });
    }
    return d;
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
