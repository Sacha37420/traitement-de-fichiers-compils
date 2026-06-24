import { Component, OnInit, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { FichierService, Fichier, Modification } from '../../core/fichier.service';
import { NavbarComponent } from '../../shared/navbar/navbar';

@Component({
  selector: 'app-historique-modifications',
  standalone: true,
  imports: [CommonModule, RouterLink, NavbarComponent],
  templateUrl: './historique-modifications.html',
  styleUrl: './historique-modifications.scss',
})
export class HistoriqueModificationsComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private fichierService = inject(FichierService);

  fichierId!: number;
  fichier: Fichier | null = null;
  modifications: Modification[] = [];
  loading = true;
  error = '';
  total = 0;
  page = 1;

  ngOnInit(): void {
    this.fichierId = +this.route.snapshot.paramMap.get('id')!;
    this.fichierService.getFichier(this.fichierId).subscribe({
      next: (f) => { this.fichier = f; },
    });
    this.loadHistorique();
  }

  loadHistorique(): void {
    this.loading = true;
    this.fichierService.getModifications(this.fichierId).subscribe({
      next: (resp) => {
        this.modifications = resp.results;
        this.total = resp.count;
        this.loading = false;
      },
      error: () => { this.error = 'Erreur lors du chargement.'; this.loading = false; },
    });
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleString('fr-FR', { dateStyle: 'medium', timeStyle: 'short' });
  }
}
