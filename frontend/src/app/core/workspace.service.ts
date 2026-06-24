import { Injectable, signal } from '@angular/core';
import { Fichier } from './fichier.service';

export interface HistoriqueEntry {
  action: string;
  details?: Record<string, unknown>;
  date?: string;
}

export interface WorkspaceItem {
  fichier: Fichier;
  historiqueLocal: HistoriqueEntry[];
}

@Injectable({ providedIn: 'root' })
export class WorkspaceService {
  private _items = signal<WorkspaceItem[]>([]);
  readonly items = this._items.asReadonly();

  add(fichier: Fichier): void {
    if (this._items().some(i => i.fichier.id === fichier.id)) return;
    this._items.update(list => [...list, { fichier, historiqueLocal: [] }]);
  }

  remove(fichierId: number): void {
    this._items.update(list => list.filter(i => i.fichier.id !== fichierId));
  }

  addHistorique(fichierId: number, entry: HistoriqueEntry): void {
    this._items.update(list => list.map(item =>
      item.fichier.id === fichierId
        ? { ...item, historiqueLocal: [...item.historiqueLocal, entry] }
        : item
    ));
  }

  updateFichier(fichier: Fichier): void {
    this._items.update(list => list.map(item =>
      item.fichier.id === fichier.id ? { ...item, fichier } : item
    ));
  }

  get(fichierId: number): WorkspaceItem | undefined {
    return this._items().find(i => i.fichier.id === fichierId);
  }
}
