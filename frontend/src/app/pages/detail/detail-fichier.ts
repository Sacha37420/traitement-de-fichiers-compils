import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FichierService, Fichier, Modification } from '../../core/fichier.service';
import { NavbarComponent } from '../../shared/navbar/navbar';

@Component({
  selector: 'app-detail-fichier',
  standalone: true,
  imports: [CommonModule, RouterLink, NavbarComponent],
  templateUrl: './detail-fichier.html',
  styleUrl: './detail-fichier.scss',
})
export class DetailFichierComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private fichierService = inject(FichierService);

  fichier: Fichier | null = null;
  modifications: Modification[] = [];
  loading = true;
  error = '';

  ngOnInit(): void {
    const id = +this.route.snapshot.paramMap.get('id')!;
    this.fichierService.getFichier(id).subscribe({
      next: (f) => {
        this.fichier = f;
        this.loading = false;
        this.loadModifications(id);
      },
      error: () => { this.error = 'Fichier introuvable.'; this.loading = false; },
    });
  }

  private loadModifications(id: number): void {
    this.fichierService.getModifications(id).subscribe({
      next: (resp) => { this.modifications = resp.results; },
    });
  }

  download(): void {
    if (!this.fichier) return;
    window.open(this.fichierService.downloadUrl(this.fichier.id), '_blank');
  }

  openEditor(): void {
    if (!this.fichier) return;
    this.router.navigate(['/editeur', this.fichier.type, this.fichier.id]);
  }

  viewHistorique(): void {
    if (!this.fichier) return;
    this.router.navigate(['/fichiers', this.fichier.id, 'historique']);
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleString('fr-FR', { dateStyle: 'short', timeStyle: 'short' });
  }

  get downloadUrl(): string {
    return this.fichier ? this.fichierService.downloadUrl(this.fichier.id) : '';
  }
}
