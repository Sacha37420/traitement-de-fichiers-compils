/**
 * Configuration injectée au démarrage du conteneur (`assets/env.js`, écrit par
 * `nginx-entrypoint.sh`).
 */
export interface LabEnv {
  keycloakUrl?: string;
  keycloakRealm?: string;
  keycloakClientId?: string;
  appUrl?: string;
  apiUrl?: string;
  storageUrl?: string;
}

export function labEnv(): LabEnv {
  return (window as unknown as { __env?: LabEnv }).__env ?? {};
}

/** Base de l'API de cette app, sans barre finale. */
export function apiUrl(): string {
  return (labEnv().apiUrl ?? 'http://localhost:8089').replace(/\/+$/, '');
}

/** Base de l'API `storage` vue du navigateur, sans barre finale. */
export function storageUrl(): string {
  return (labEnv().storageUrl ?? 'http://localhost:8093').replace(/\/+$/, '');
}

/**
 * Les SEULES adresses auxquelles le jeton de l'utilisateur est joint
 * (`auth.interceptor.ts`, `token-scope.ts`) : l'API de cette app, et les
 * fichiers de `storage`, que le navigateur lit directement (`fichier_url`,
 * `FichierService.downloadBlob`). L'OCR passe par l'API de l'app : le
 * navigateur ne joint plus Mistral.
 */
export function tokenBases(): string[] {
  return [apiUrl(), `${storageUrl()}/api/files`];
}
