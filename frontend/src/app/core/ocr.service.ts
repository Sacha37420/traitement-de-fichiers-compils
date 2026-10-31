import { Injectable, inject } from '@angular/core';
import { HttpClient, HttpErrorResponse } from '@angular/common/http';
import { firstValueFrom, Observable } from 'rxjs';
import { apiUrl } from './env';
import { OcrResponse } from './mistral-ocr.util';

/** Poids maximal d'un document envoyé à l'OCR (même limite que le serveur, OCR_MAX_OCTETS). */
export const OCR_MAX_OCTETS = 20 * 1024 * 1024;

/**
 * OCR par le serveur et coffre de la clé Mistral.
 *
 * La clé est envoyée une fois (`PUT /api/ocr-key/`), gardée chiffrée par le
 * serveur et jamais renvoyée : `GET` ne dit que si elle est enregistrée. L'OCR
 * part du serveur (`POST /api/ocr/`), avec la clé du coffre de l'utilisateur
 * connecté ; le navigateur ne joint jamais Mistral. Le jeton est joint par
 * `authInterceptor`.
 */
@Injectable({ providedIn: 'root' })
export class OcrService {
  private http = inject(HttpClient);

  keyStatus(): Observable<{ mistral_key_configured: boolean }> {
    return this.http.get<{ mistral_key_configured: boolean }>(`${apiUrl()}/api/ocr-key/`);
  }

  /** Enregistre la clé ; chaîne vide ⇒ la retire. */
  setKey(key: string): Observable<void> {
    return this.http.put<void>(`${apiUrl()}/api/ocr-key/`, { mistral_key: key });
  }

  /** OCR d'un document par le serveur. Rejette avec un message lisible. */
  async run(blob: Blob, mime: string, name: string): Promise<OcrResponse> {
    if (blob.size > OCR_MAX_OCTETS) {
      throw new Error('Document trop volumineux pour l\'OCR (limite 20 Mo).');
    }
    const fd = new FormData();
    fd.append('file', new File([blob], name, { type: mime }));
    try {
      return await firstValueFrom(this.http.post<OcrResponse>(`${apiUrl()}/api/ocr/`, fd));
    } catch (e) {
      throw new Error(ocrErrorMessage(e));
    }
  }
}

function ocrErrorMessage(e: unknown): string {
  if (!(e instanceof HttpErrorResponse)) return 'OCR impossible.';
  const code = (e.error && typeof e.error === 'object') ? e.error.code : undefined;
  if (code === 'key_not_configured') return 'Clé API Mistral non enregistrée.';
  if (code === 'key_rejected') return 'Clé API Mistral refusée par Mistral (invalide ou expirée).';
  switch (e.status) {
    case 0: return 'Serveur injoignable.';
    case 401: case 403: return 'Connexion requise (ou accès refusé).';
    case 413: return 'Document trop volumineux pour l\'OCR (limite 20 Mo).';
    case 504: return 'Mistral n\'a pas répondu à temps. Réessayez.';
  }
  const msg = (e.error && typeof e.error === 'object') ? e.error.error : undefined;
  return typeof msg === 'string' && msg ? msg : `Erreur du serveur (${e.status}).`;
}
