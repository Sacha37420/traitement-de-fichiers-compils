import { Component, inject } from '@angular/core';
import { CommonModule } from '@angular/common';
import { Router } from '@angular/router';
import { WorkspaceService, WorkspaceItem } from '../../core/workspace.service';
import { FichierService } from '../../core/fichier.service';
import { NavbarComponent } from '../../shared/navbar/navbar';

@Component({
  selector: 'app-traitement-fichiers',
  standalone: true,
  imports: [CommonModule, NavbarComponent],
  templateUrl: './traitement-fichiers.html',
  styleUrl: './traitement-fichiers.scss',
})
export class TraitementFichiersComponent {
  private workspace = inject(WorkspaceService);
  private fichierService = inject(FichierService);
  private router = inject(Router);

  items = this.workspace.items;

  openEditor(item: WorkspaceItem): void {
    this.router.navigate(['/editeur', item.fichier.type, item.fichier.id]);
  }

  remove(fichierId: number): void {
    this.workspace.remove(fichierId);
  }

  download(item: WorkspaceItem): void {
    window.open(this.fichierService.downloadUrl(item.fichier.id), '_blank');
  }

  type(item: WorkspaceItem): string {
    const actions = item.historiqueLocal.length;
    return actions ? `${actions} action${actions > 1 ? 's' : ''} appliquée${actions > 1 ? 's' : ''}` : 'Aucune modification';
  }
}
