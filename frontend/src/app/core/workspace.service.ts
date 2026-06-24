import { Injectable, inject } from '@angular/core';
import { HttpClient } from '@angular/common/http';
import { Observable } from 'rxjs';
import { Fichier } from './fichier.service';

interface EnvWindow { __env?: { apiUrl?: string } }

export interface FichierWorkspace {
  id: number;
  fichier_temporaire_id: string;
  etat: string;
  nom_temporaire: string | null;
  historique_local: HistoriqueEntry[];
  tags_temporaires: string[];
  fichier_id: number | null;
}

export interface WorkspaceResponse {
  id: number;
  fichiers: FichierWorkspace[];
}

export interface HistoriqueEntry {
  action: string;
  details?: Record<string, unknown>;
  date?: string;
}

@Injectable({ providedIn: 'root' })
export class WorkspaceService {
  private http = inject(HttpClient);

  private get base(): string {
    return (window as unknown as EnvWindow).__env?.apiUrl ?? 'http://localhost:8089';
  }

  getWorkspace(): Observable<WorkspaceResponse> {
    return this.http.post<WorkspaceResponse>(`${this.base}/api/workspace/`, {});
  }

  addFichierToWorkspace(fichierId: number): Observable<WorkspaceResponse> {
    return this.http.post<WorkspaceResponse>(`${this.base}/api/workspace/`, { fichier_id: fichierId });
  }

  finaliser(workspaceId: number, payload: {
    fichier_temporaire_id: string;
    nom?: string;
    tags?: string[];
    historique?: HistoriqueEntry[];
    metadonnees?: Record<string, unknown>;
  }): Observable<Fichier> {
    return this.http.post<Fichier>(`${this.base}/api/workspace/${workspaceId}/finaliser/`, payload);
  }
}
