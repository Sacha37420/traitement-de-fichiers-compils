import { Component, OnInit, computed, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { Router, RouterLink } from '@angular/router';
import { FichierService, Fichier } from '../../core/fichier.service';
import { WorkFileStore } from '../../core/workfile-store.service';
import { KeycloakService } from '../../core/keycloak.service';
import { workFileFromBlob } from '../../core/work-file.model';
import { NavbarComponent } from '../../shared/navbar/navbar';

type Mode = 'mine' | 'shared';

/**
 * Gestionnaire de fichiers backend : « Mes fichiers » (liste, télécharger, rouvrir
 * dans l'atelier, supprimer, partager par email) et « Partagés avec moi » (fichiers
 * que d'autres m'ont partagés — lecture seule). Nécessite l'authentification.
 */
@Component({
  selector: 'app-mes-fichiers',
  standalone: true,
  imports: [NavbarComponent, RouterLink, FormsModule],
  templateUrl: './mes-fichiers.html',
  styleUrl: './mes-fichiers.scss',
})
export class MesFichiersComponent implements OnInit {
  private fichierService = inject(FichierService);
  private store = inject(WorkFileStore);
  private kc = inject(KeycloakService);
  private router = inject(Router);

  mode = signal<Mode>('mine');
  fichiers = signal<Fichier[]>([]);
  loading = signal(false);
  error = signal('');
  message = signal('');
  page = signal(1);
  count = signal(0);
  readonly pageSize = 12;

  private pendingDelete = signal<number | null>(null);
  private sharing = signal<number | null>(null);
  shareEmail = signal('');

  totalPages = computed(() => Math.max(1, Math.ceil(this.count() / this.pageSize)));

  get isAuthenticated(): boolean { return this.kc.isAuthenticated; }

  ngOnInit(): void {
    if (this.isAuthenticated) this.load();
  }

  setMode(m: Mode): void {
    if (this.mode() === m) return;
    this.mode.set(m);
    this.page.set(1);
    this.pendingDelete.set(null);
    this.sharing.set(null);
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set('');
    const req = this.mode() === 'mine'
      ? this.fichierService.getMesFichiers({ page: this.page() })
      : this.fichierService.getPartagesAvecMoi({ page: this.page() });
    req.subscribe({
      next: (res) => {
        this.fichiers.set(res.results);
        this.count.set(res.count);
        this.loading.set(false);
      },
      error: () => {
        this.error.set('Impossible de charger les fichiers.');
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

  // ── Suppression ─────────────────────────────────────────────────────────
  askDelete(f: Fichier): void { this.pendingDelete.set(f.id); this.sharing.set(null); }
  cancelDelete(): void { this.pendingDelete.set(null); }
  isPendingDelete(id: number): boolean { return this.pendingDelete() === id; }

  confirmDelete(f: Fichier): void {
    this.pendingDelete.set(null);
    this.error.set('');
    this.fichierService.deleteFichier(f.id).subscribe({
      next: () => {
        this.flash(`« ${f.nom} » supprimé.`);
        if (this.fichiers().length === 1 && this.page() > 1) this.page.set(this.page() - 1);
        this.load();
      },
      error: () => this.error.set(`Suppression de « ${f.nom} » impossible.`),
    });
  }

  // ── Partage ─────────────────────────────────────────────────────────────
  isSharing(id: number): boolean { return this.sharing() === id; }
  openShare(f: Fichier): void { this.sharing.set(f.id); this.shareEmail.set(''); this.pendingDelete.set(null); }
  closeShare(): void { this.sharing.set(null); this.shareEmail.set(''); }

  addShare(f: Fichier): void {
    const email = this.shareEmail().trim();
    if (!email || !email.includes('@')) { this.error.set('Adresse email invalide.'); return; }
    this.error.set('');
    this.fichierService.partager(f.id, email).subscribe({
      next: (updated) => { this.replaceFile(updated); this.shareEmail.set(''); this.flash(`Partagé avec ${email}.`); },
      error: () => this.error.set('Partage impossible.'),
    });
  }

  removeShare(f: Fichier, email: string): void {
    this.error.set('');
    this.fichierService.retirerPartage(f.id, email).subscribe({
      next: (updated) => { this.replaceFile(updated); this.flash(`Partage retiré (${email}).`); },
      error: () => this.error.set('Retrait du partage impossible.'),
    });
  }

  private replaceFile(f: Fichier): void {
    this.fichiers.update((list) => list.map((x) => (x.id === f.id ? f : x)));
  }

  // ── Formatage ────────────────────────────────────────────────────────────
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
