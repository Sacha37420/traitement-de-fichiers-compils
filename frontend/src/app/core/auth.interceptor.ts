import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { from, switchMap, catchError } from 'rxjs';
import { KeycloakService } from './keycloak.service';

export const authInterceptor: HttpInterceptorFn = (req, next) => {
  const kc = inject(KeycloakService);

  if (!kc.isAuthenticated) return next(req);

  if (!kc.isTokenExpired(30)) {
    return next(req.clone({ setHeaders: { Authorization: `Bearer ${kc.getToken()}` } }));
  }

  return from(kc.updateToken(-1)).pipe(
    switchMap(() => {
      const fresh = kc.getToken();
      if (fresh) req = req.clone({ setHeaders: { Authorization: `Bearer ${fresh}` } });
      return next(req);
    }),
    catchError(() => next(req)),
  );
};
