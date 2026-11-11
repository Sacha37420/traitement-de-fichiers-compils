import { Injectable } from '@angular/core';
import Keycloak from 'keycloak-js';
import { LabEnv, labEnv } from './env';
import { loginRedirectUri } from './redirect-uri';

@Injectable({ providedIn: 'root' })
export class KeycloakService {
  private kc!: Keycloak;
  private env: LabEnv = {};

  async init(): Promise<boolean> {
    const env = labEnv();
    this.env = env;
    this.kc = new Keycloak({
      url:      env.keycloakUrl      ?? (window.location.protocol + '//' + window.location.hostname + ':8080'),
      realm:    env.keycloakRealm    ?? 'ssolab',
      clientId: env.keycloakClientId ?? 'traitement-de-fichiers-compils',
    });
    // Page publique : `check-sso` (silencieux, par iframe) est gardé tel quel —
    // aucun `redirectUri` ici, il ne sert qu'au bouton de connexion (`login()`).
    return this.kc.init({
      onLoad: 'check-sso',
      checkLoginIframe: false,
      silentCheckSsoRedirectUri: document.baseURI + 'assets/silent-check-sso.html',
      pkceMethod: 'S256',
    });
  }

  get username(): string {
    return (this.kc?.tokenParsed as Record<string, unknown>)?.['preferred_username'] as string ?? '';
  }

  get email(): string {
    return (this.kc?.tokenParsed as Record<string, unknown>)?.['email'] as string ?? '';
  }

  get isAuthenticated(): boolean { return this.kc?.authenticated ?? false; }

  /** Connexion, puis retour sur la page courante (si elle est sous l'app), sinon sur l'accueil. */
  login(): void {
    this.kc.login({ redirectUri: loginRedirectUri(window.location.href, this.env.appUrl, window.location.origin) });
  }

  getToken(): string | undefined {
    return this.kc?.token;
  }

  isTokenExpired(minValidity = 0): boolean {
    return this.kc?.isTokenExpired(minValidity) ?? true;
  }

  async updateToken(minValidity: number): Promise<boolean> {
    try {
      return await this.kc.updateToken(minValidity);
    } catch {
      return false;
    }
  }

  logout(): void {
    // Retour sous le préfixe de l'app (<base href>, ex. /<app>/) : la racine du domaine
    // n'est pas une URI de retour du client depuis --prune-uris (LOGOUT_ERROR
    // invalid_redirect_uri, constaté sur peripheriques le 2026-11-08).
    this.kc.logout({ redirectUri: document.baseURI });
  }
}
