import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { Router } from '@angular/router';
import { FichierService, Fichier } from '../../core/fichier.service';
import { WorkspaceService } from '../../core/workspace.service';
import { NavbarComponent } from '../../shared/navbar/navbar';

@Component({
  selector: 'app-mes-fichiers',
  standalone: true,
  imports: [CommonModule, FormsModule, NavbarComponent],
  templateUrl: './mes-fichiers.html',
  styleUrl: './mes-fichiers.scss',
})
export class MesFichiersComponent implements OnInit {
  private fichierService = inject(FichierService);
  private workspaceService = inject(WorkspaceService);
  private router = inject(Router);

  fichiers: Fichier[] = [];
  loading = true;
  error = '';
  total = 0;
  page = 1;

  filterType = '';
  filterTag = '';

  readonly typeOptions = ['', 'Image', 'Video', 'Audio', 'PDF'];

  ngOnInit(): void {
    this.loadFichiers();
  }

  loadFichiers(): void {
    this.loading = true;
    this.error = '';
    this.fichierService.getMesFichiers({
      type: this.filterType || undefined,
      tag: this.filterTag || undefined,
      page: this.page,
    }).subscribe({
      next: (resp) => {
        this.fichiers = resp.results;
        this.total = resp.count;
        this.loading = false;
      },
      error: (err) => {
        this.error = err.error?.error || 'Erreur lors du chargement des fichiers.';
        this.loading = false;
      },
    });
  }

  applyFilter(): void {
    this.page = 1;
    this.loadFichiers();
  }

  openEditor(fichier: Fichier): void {
    this.workspaceService.addFichierToWorkspace(fichier.id).subscribe({
      next: () => this.router.navigate(['/editeur', fichier.type, fichier.id]),
      error: () => this.router.navigate(['/editeur', fichier.type, fichier.id]),
    });
  }

  viewDetail(fichier: Fichier): void {
    this.router.navigate(['/fichiers', fichier.id]);
  }

  downloadFichier(fichier: Fichier): void {
    window.open(this.fichierService.downloadUrl(fichier.id), '_blank');
  }

  prevPage(): void {
    if (this.page > 1) { this.page--; this.loadFichiers(); }
  }

  nextPage(): void {
    if (this.page * 10 < this.total) { this.page++; this.loadFichiers(); }
  }

  get totalPages(): number {
    return Math.ceil(this.total / 10);
  }

  formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
  }
}
