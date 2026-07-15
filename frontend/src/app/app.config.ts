import { ApplicationConfig, APP_INITIALIZER } from '@angular/core';
import { provideRouter } from '@angular/router';
import { provideHttpClient, withInterceptors } from '@angular/common/http';
import { routes } from './app.routes';
import { KeycloakService } from './core/keycloak.service';
import { authInterceptor } from './core/auth.interceptor';

function initKeycloak(kc: KeycloakService): () => Promise<boolean> {
  // Ne jamais bloquer le bootstrap : l'atelier doit rester accessible hors
  // connexion (Keycloak injoignable ⇒ simplement non authentifié).
  return () => kc.init().catch(() => false);
}

export const appConfig: ApplicationConfig = {
  providers: [
    provideRouter(routes),
    provideHttpClient(withInterceptors([authInterceptor])),
    {
      provide: APP_INITIALIZER,
      useFactory: initKeycloak,
      deps: [KeycloakService],
      multi: true,
    },
  ],
};
