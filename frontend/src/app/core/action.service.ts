import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { PaginatedResponse } from './fichier.service';

interface EnvWindow { __env?: { apiUrl?: string } }

export interface Action {
  id: number;
  nom: string;
  description: string | null;
  type_fichier: string;
  parametres_schema: Record<string, string>;
}

@Injectable({ providedIn: 'root' })
export class ActionService {
  private http = inject(HttpClient);

  private get base(): string {
    return (window as unknown as EnvWindow).__env?.apiUrl ?? 'http://localhost:8089';
  }

  getActions(typeFichier?: string): Observable<PaginatedResponse<Action>> {
    let params = new HttpParams();
    if (typeFichier) params = params.set('type_fichier', typeFichier);
    return this.http.get<PaginatedResponse<Action>>(`${this.base}/api/actions/`, { params });
  }
}
