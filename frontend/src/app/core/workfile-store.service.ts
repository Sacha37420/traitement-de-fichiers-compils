import { Injectable, signal } from '@angular/core';
import {
  WorkFile,
  OperationRecord,
  workFileFromFile,
} from './work-file.model';
import { FileOperation } from './operations/operation.model';

/**
 * Store client de l'atelier : la liste des fichiers en cours de traitement.
 * Entièrement en mémoire (signals). Responsable de la révocation des object URLs
 * de prévisualisation pour éviter les fuites mémoire.
 */
@Injectable({ providedIn: 'root' })
export class WorkFileStore {
  private _files = signal<WorkFile[]>([]);
  readonly files = this._files.asReadonly();

  private _busy = signal(false);
  readonly busy = this._busy.asReadonly();

  addFiles(files: (File | WorkFile)[]): void {
    const wfs = files.map((f) => (f instanceof File ? workFileFromFile(f) : f));
    this._files.update((list) => [...list, ...wfs]);
  }

  remove(id: string): void {
    this._files.update((list) => {
      const target = list.find((f) => f.id === id);
      if (target) URL.revokeObjectURL(target.previewUrl);
      return list.filter((f) => f.id !== id);
    });
  }

  clear(): void {
    this._files().forEach((f) => URL.revokeObjectURL(f.previewUrl));
    this._files.set([]);
  }

  get(id: string): WorkFile | undefined {
    return this._files().find((f) => f.id === id);
  }

  rename(id: string, name: string): void {
    this._files.update((list) =>
      list.map((f) => (f.id === id ? { ...f, name } : f)),
    );
  }

  /** Applique une opération single-file et met à jour la liste (remplace ou ajoute). */
  async applyOperation(
    fileId: string,
    op: FileOperation,
    params: Record<string, unknown>,
  ): Promise<void> {
    const source = this.get(fileId);
    if (!source || !op.run) return;
    this._busy.set(true);
    try {
      const result = await op.run(source, params);
      const stamped = this.stamp(result.files, op, params);
      this._files.update((list) => {
        const idx = list.findIndex((f) => f.id === fileId);
        if (idx < 0) return list;
        if (result.replacesSource) {
          URL.revokeObjectURL(source.previewUrl);
          return [...list.slice(0, idx), ...stamped, ...list.slice(idx + 1)];
        }
        return [...list, ...stamped];
      });
    } finally {
      this._busy.set(false);
    }
  }

  /** Applique une opération multi-fichiers (ex. fusion) sur une sélection. */
  async applyMultiOperation(
    fileIds: string[],
    op: FileOperation,
    params: Record<string, unknown>,
  ): Promise<void> {
    const selected = this._files().filter((f) => fileIds.includes(f.id));
    if (!op.runMulti || selected.length === 0) return;
    this._busy.set(true);
    try {
      const result = await op.runMulti(selected, params);
      const stamped = this.stamp(result.files, op, params);
      this._files.update((list) => {
        if (result.replacesSource) {
          selected.forEach((f) => URL.revokeObjectURL(f.previewUrl));
          return [...list.filter((f) => !fileIds.includes(f.id)), ...stamped];
        }
        return [...list, ...stamped];
      });
    } finally {
      this._busy.set(false);
    }
  }

  private stamp(
    files: WorkFile[],
    op: FileOperation,
    params: Record<string, unknown>,
  ): WorkFile[] {
    const record: OperationRecord = {
      opId: op.id,
      label: op.label,
      params,
      date: new Date().toISOString(),
    };
    return files.map((f) => ({ ...f, history: [...f.history, record] }));
  }
}
