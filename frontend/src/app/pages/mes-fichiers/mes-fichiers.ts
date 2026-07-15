import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { FichierService, Fichier } from '../../core/fichier.service';
import { WorkFileStore } from '../../core/workfile-store.service';
import { KeycloakService } from '../../core/keycloak.service';
import { workFileFromBlob } from '../../core/work-file.model';
import { NavbarComponent } from '../../shared/navbar/navbar';

/**
 * Gestionnaire de fichiers backend : liste les fichiers de l'utilisateur stockés
 * sur le serveur, permet de les télécharger, les rouvrir dans l'atelier ou les
 * supprimer. Nécessite l'authentification (sinon invite à se connecter).
 */
@Component({
  selector: 'app-mes-fichiers',
  standalone: true,
  imports: [NavbarComponent, RouterLink],
  templateUrl: './mes-fichiers.html',
  styleUrl: './mes-fichiers.scss',
})
export class MesFichiersComponent implements OnInit {
  private fichierService = inject(FichierService);
  private store = inject(WorkFileStore);
  private kc = inject(KeycloakService);
  private router = inject(Router);

  fichiers = signal<Fichier[]>([]);
  loading = signal(false);
  error = signal('');
  message = signal('');
  page = signal(1);
  count = signal(0);
  readonly pageSize = 12;
  private pendingDelete = signal<number | null>(null);

  totalPages = computed(() => Math.max(1, Math.ceil(this.count() / this.pageSize)));

  get isAuthenticated(): boolean { return this.kc.isAuthenticated; }

  ngOnInit(): void {
    if (this.isAuthenticated) this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set('');
    this.fichierService.getMesFichiers({ page: this.page() }).subscribe({
      next: (res) => {
        this.fichiers.set(res.results);
        this.count.set(res.count);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de charger vos fichiers.');
        this.loading.set(false);
      },
    });
  }

  goto(p: number): void {
    if (p < 1 || p > this.totalPages() || p === this.page()) return;
    this.page.set(p);
    this.load();
  }

  login(): void { this.kc.login(); }

  download(f: Fichier): void {
    this.fichierService.downloadBlob(f.id).subscribe({
      next: (blob) => saveBlob(blob, f.nom),
      error: () => this.error.set(`Téléchargement de « ${f.nom} » impossible.`),
    });
  }

  openInAtelier(f: Fichier): void {
    this.fichierService.downloadBlob(f.id).subscribe({
      next: (blob) => {
        const mime = f.fichier_type_mime || blob.type || 'application/octet-stream';
        this.store.addFiles([workFileFromBlob(blob, f.nom, mime, { origin: 'backend', backendId: f.id })]);
        this.router.navigate(['/atelier']);
      },
      error: () => this.error.set(`Ouverture de « ${f.nom} » impossible.`),
    });
  }

  askDelete(f: Fichier): void { this.pendingDelete.set(f.id); }
  cancelDelete(): void { this.pendingDelete.set(null); }
  isPendingDelete(id: number): boolean { return this.pendingDelete() === id; }

  confirmDelete(f: Fichier): void {
    this.pendingDelete.set(null);
    this.error.set('');
    this.fichierService.deleteFichier(f.id).subscribe({
      next: () => {
        this.flash(`« ${f.nom} » supprimé.`);
        // Reculer d'une page si on vient de vider la dernière.
        if (this.fichiers().length === 1 && this.page() > 1) this.page.set(this.page() - 1);
        this.load();
      },
      error: () => this.error.set(`Suppression de « ${f.nom} » impossible.`),
    });
  }

  formatSize(mo: number | string): string {
    const v = Number(mo);
    if (!Number.isFinite(v)) return '—';
    if (v < 1) return `${Math.round(v * 1024)} Ko`;
    return `${v.toFixed(2)} Mo`;
  }

  formatDate(iso: string): string {
    const d = new Date(iso);
    return Number.isNaN(d.getTime()) ? '—' : d.toLocaleString('fr-FR');
  }

  private flash(msg: string): void {
    this.message.set(msg);
    setTimeout(() => this.message.set(''), 4000);
  }
}

function saveBlob(blob: Blob, name: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
