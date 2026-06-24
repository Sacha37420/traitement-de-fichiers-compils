import { Component, OnInit, inject, signal } from '@angular/core';
import { CommonModule } from '@angular/common';
import { FormsModule } from '@angular/forms';
import { ActivatedRoute, Router, RouterLink } from '@angular/router';
import { FichierService, Fichier } from '../../core/fichier.service';
import { ActionService, Action } from '../../core/action.service';
import { WorkspaceService, HistoriqueEntry } from '../../core/workspace.service';
import { NavbarComponent } from '../../shared/navbar/navbar';

interface ActionCategory { nom: string; actions: Action[]; }
interface ParamField    { key: string; type: string; }

@Component({
  selector: 'app-editeur-fichier',
  standalone: true,
  imports: [CommonModule, FormsModule, RouterLink, NavbarComponent],
  templateUrl: './editeur-fichier.html',
  styleUrl: './editeur-fichier.scss',
})
export class EditeurFichierComponent implements OnInit {
  private route = inject(ActivatedRoute);
  private router = inject(Router);
  private fichierService = inject(FichierService);
  private actionService = inject(ActionService);
  private workspaceService = inject(WorkspaceService);

  fichier: Fichier | null = null;
  fileType = '';
  fileUrl = '';
  historique: HistoriqueEntry[] = [];

  // Actions
  actionCategories: ActionCategory[] = [];
  selectedAction: Action | null = null;
  actionParams: Record<string, unknown> = {};
  paramFields: ParamField[] = [];

  // Preview
  previewUrl = '';
  previewLoading = false;

  // UI state
  loading = true;
  saving = false;
  error = '';
  successMsg = '';
  nomSauvegarde = '';
  tagsSauvegarde = '';

  // CSS filter style pour prévisualisation live (Image uniquement)
  cssFilter = signal('');

  ngOnInit(): void {
    const type = this.route.snapshot.paramMap.get('type') ?? '';
    const id = this.route.snapshot.paramMap.get('id');
    this.fileType = type;

    if (id) {
      this.loadFichier(+id);
    } else {
      this.router.navigate(['/traitement']);
    }
    this.loadActions(type);
  }

  private loadFichier(id: number): void {
    const wsItem = this.workspaceService.get(id);
    if (wsItem) {
      this.fichier = wsItem.fichier;
      this.historique = [...wsItem.historiqueLocal];
      this.nomSauvegarde = wsItem.fichier.nom;
      this.tagsSauvegarde = wsItem.fichier.tags.join(', ');
      this.fileUrl = this.fichierService.downloadUrl(id);
      this.loading = false;
    } else {
      this.fichierService.getFichier(id).subscribe({
        next: (f) => {
          this.fichier = f;
          this.nomSauvegarde = f.nom;
          this.tagsSauvegarde = f.tags.join(', ');
          this.fileUrl = this.fichierService.downloadUrl(f.id);
          this.loading = false;
        },
        error: () => { this.error = 'Impossible de charger le fichier.'; this.loading = false; },
      });
    }
  }

  private loadActions(type: string): void {
    this.actionService.getActions(type).subscribe({
      next: (resp) => {
        this.actionCategories = this.groupByCategory(resp.results);
      },
    });
  }

  private groupByCategory(actions: Action[]): ActionCategory[] {
    const map = new Map<string, Action[]>();
    const categoryOf: Record<string, string> = {
      'Recadrage': 'Géométrie', 'Redimensionnement': 'Géométrie', 'Rotation': 'Géométrie',
      'Noir et Blanc': 'Filtres', 'Sépia': 'Filtres', 'Contraste': 'Filtres', 'Luminosité': 'Filtres',
      'Dessin libre': 'Annotations', 'Texte': 'Annotations', 'Formes': 'Annotations',
      'Calques': 'Calques', 'Stickers': 'Calques',
      'Compression': 'Optimisation', 'Conversion de format': 'Optimisation',
    };

    for (const action of actions) {
      const cat = categoryOf[action.nom] ?? 'Autre';
      if (!map.has(cat)) map.set(cat, []);
      map.get(cat)!.push(action);
    }
    return Array.from(map.entries()).map(([nom, acts]) => ({ nom, actions: acts }));
  }

  selectAction(action: Action): void {
    this.selectedAction = action;
    this.actionParams = {};
    this.previewUrl = '';
    this.paramFields = Object.entries(action.parametres_schema).map(([key, type]) => ({ key, type }));
  }

  preview(): void {
    if (!this.fichier || !this.selectedAction) return;
    this.previewLoading = true;
    this.previewUrl = '';

    this.fichierService.appliquerAction(this.fichier.id, this.selectedAction.nom, this.actionParams, true).subscribe({
      next: (resp: unknown) => {
        const r = resp as { preview_url?: string };
        if (r?.preview_url) {
          this.previewUrl = this.resolvePreviewUrl(r.preview_url);
        }
        this.previewLoading = false;
      },
      error: () => { this.previewLoading = false; },
    });
  }

  private resolvePreviewUrl(url: string): string {
    const envApiUrl = (window as unknown as { __env?: { apiUrl?: string } }).__env?.apiUrl ?? '';
    return url.startsWith('http') ? url : `${envApiUrl}${url}`;
  }

  applyAction(): void {
    if (!this.fichier || !this.selectedAction) return;

    this.updateCssFilter(this.selectedAction.nom, this.actionParams);

    this.fichierService.appliquerAction(this.fichier.id, this.selectedAction.nom, this.actionParams, false).subscribe({
      next: (resp: unknown) => {
        const r = resp as { success?: boolean; modification_id?: number };
        if (r?.success) {
          const entry: HistoriqueEntry = {
            action: this.selectedAction!.nom,
            details: { ...this.actionParams },
            date: new Date().toISOString(),
          };
          this.historique.push(entry);
          this.workspaceService.addHistorique(this.fichier!.id, entry);
          this.fileUrl = this.fichierService.downloadUrl(this.fichier!.id) + '?t=' + Date.now();
          this.selectedAction = null;
          this.actionParams = {};
          this.previewUrl = '';
        }
      },
      error: (err) => { this.error = err.error?.error || 'Erreur lors de l\'action.'; },
    });
  }

  private updateCssFilter(nom: string, params: Record<string, unknown>): void {
    const brightness = nom === 'Luminosité' ? `brightness(${params['niveau'] ?? 1})` : '';
    const contrast = nom === 'Contraste' ? `contrast(${params['niveau'] ?? 1})` : '';
    const grayscale = nom === 'Noir et Blanc' ? 'grayscale(1)' : '';
    const sepia = nom === 'Sépia' ? 'sepia(1)' : '';
    const filters = [brightness, contrast, grayscale, sepia].filter(Boolean).join(' ');
    if (filters) this.cssFilter.set(filters);
  }

  undoLast(): void {
    this.historique.pop();
  }

  save(): void {
    if (!this.fichier) return;
    this.saving = true;
    this.error = '';
    const payload = {
      fichier_id: this.fichier.id,
      nom: this.nomSauvegarde,
      tags: this.tagsSauvegarde.split(',').map(t => t.trim()).filter(Boolean),
      metadonnees: this.fichier.metadonnees,
    };
    this.fichierService.enregistrerFichier(payload).subscribe({
      next: () => { this.saving = false; this.router.navigate(['/mes-fichiers']); },
      error: (err) => {
        this.error = err.error?.error || 'Erreur lors de l\'enregistrement. Êtes-vous connecté ?';
        this.saving = false;
      },
    });
  }

  download(): void {
    if (!this.fichier) return;
    window.open(this.fichierService.downloadUrl(this.fichier.id), '_blank');
  }

  formatDate(iso: string): string {
    return new Date(iso).toLocaleTimeString('fr-FR', { hour: '2-digit', minute: '2-digit' });
  }
}
