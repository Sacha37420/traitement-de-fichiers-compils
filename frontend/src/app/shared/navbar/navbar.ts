import { Component, inject } from '@angular/core';
import { RouterLink, RouterLinkActive } from '@angular/router';
import { KeycloakService } from '../../core/keycloak.service';

@Component({
  selector: 'app-navbar',
  standalone: true,
  imports: [RouterLink, RouterLinkActive],
  templateUrl: './navbar.html',
  styleUrl: './navbar.scss',
})
export class NavbarComponent {
  private kc = inject(KeycloakService);

  get username(): string { return this.kc.username || this.kc.email; }
  get isAuthenticated(): boolean { return this.kc.isAuthenticated; }

  login(): void { this.kc.login(); }
  logout(): void { this.kc.logout(); }
}
