import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpParams } from '@angular/common/http';
import { Observable } from 'rxjs';
import { PaginatedResponse } from './fichier.service';

interface EnvWindow { __env?: { apiUrl?: string } }

export interface Tag { id: number; nom: string; }

@Injectable({ providedIn: 'root' })
export class TagService {
  private http = inject(HttpClient);

  private get base(): string {
    return (window as unknown as EnvWindow).__env?.apiUrl ?? 'http://localhost:8089';
  }

  getTags(search?: string): Observable<PaginatedResponse<Tag>> {
    let params = new HttpParams();
    if (search) params = params.set('search', search);
    return this.http.get<PaginatedResponse<Tag>>(`${this.base}/api/tags/`, { params });
  }
}
