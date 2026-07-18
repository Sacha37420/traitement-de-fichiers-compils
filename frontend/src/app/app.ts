import { Component, ElementRef, HostListener, inject, signal, ViewChild } from '@angular/core';
import { NgTemplateOutlet } from '@angular/common';
import { RouterOutlet, RouterLink, RouterLinkActive } from '@angular/router';
import { KeycloakService } from './core/keycloak.service';
import { ThemeService } from './core/theme.service';

interface NavItem {
  label: string;
  abbr: string;
  path: string;
  exact?: boolean;
  authOnly?: boolean;
}

const MOBILE_CLOSE_ANIM_MS = 220;

@Component({
  selector: 'app-root',
  imports: [RouterOutlet, RouterLink, RouterLinkActive, NgTemplateOutlet],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected kc = inject(KeycloakService);
  protected theme = inject(ThemeService);

  collapsed = signal(false);
  mobileOpen = signal(false);
  mobileClosing = signal(false);

  protected noop = (): void => {};
  protected closeMobileFn = (): void => this.closeMobile();

  private readonly allNavItems: NavItem[] = [
    { path: '/atelier',      label: 'Atelier',      abbr: 'At' },
    { path: '/mes-fichiers', label: 'Mes fichiers', abbr: 'Mf', authOnly: true },
  ];

  get navItems(): NavItem[] {
    return this.allNavItems.filter(i => !i.authOnly || this.kc.isAuthenticated);
  }

  @ViewChild('closeBtn') private closeBtnRef?: ElementRef<HTMLButtonElement>;
  @ViewChild('burgerBtn') private burgerBtnRef?: ElementRef<HTMLButtonElement>;

  toggleCollapsed(): void {
    this.collapsed.update(v => !v);
  }

  openMobile(): void {
    this.mobileOpen.set(true);
    this.mobileClosing.set(false);
    document.body.style.overflow = 'hidden';
    setTimeout(() => this.closeBtnRef?.nativeElement.focus());
  }

  closeMobile(): void {
    if (!this.mobileOpen() || this.mobileClosing()) return;
    this.mobileClosing.set(true);
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    setTimeout(() => {
      this.mobileOpen.set(false);
      this.mobileClosing.set(false);
      document.body.style.overflow = '';
      this.burgerBtnRef?.nativeElement.focus();
    }, reduced ? 0 : MOBILE_CLOSE_ANIM_MS);
  }

  @HostListener('document:keydown.escape')
  onEscape(): void {
    if (this.mobileOpen()) this.closeMobile();
  }

  get username(): string {
    return this.kc.username || this.kc.email;
  }

  login(): void {
    this.kc.login();
  }

  logout(): void {
    this.kc.logout();
  }
}
