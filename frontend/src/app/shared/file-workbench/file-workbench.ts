import { Component, computed, effect, inject, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { WorkFileStore } from '../../core/workfile-store.service';
import { OperationRegistryService } from '../../core/operation-registry.service';
import { KeycloakService } from '../../core/keycloak.service';
import { FichierService } from '../../core/fichier.service';
import { OcrService } from '../../core/ocr.service';
import {
  WorkFile,
  kindToBackendType,
  workFileFromBlob,
} from '../../core/work-file.model';
import { FileOperation, OperationContext, defaultParams } from '../../core/operations/operation.model';
import { Rect } from '../../core/image-canvas.util';
import { ImageCropOverlayComponent } from './image-crop-overlay';
import { PdfPageManagerComponent } from './pdf-page-manager';

interface FormCtx { file: WorkFile; op: FileOperation; params: Record<string, unknown>; }
interface OpCtx { file: WorkFile; op: FileOperation; }
interface MergeCtx { op: FileOperation; order: WorkFile[]; }

/**
 * Atelier de fichiers partagé : importe une liste de fichiers (input/drag-drop ou
 * backend), les prévisualise, applique des opérations client-side dont les actions
 * disponibles se recalculent au changement de format, puis télécharge ou envoie
 * le résultat. Les appels backend sont désactivés hors connexion.
 */
@Component({
  selector: 'app-file-workbench',
  standalone: true,
  imports: [FormsModule, ImageCropOverlayComponent, PdfPageManagerComponent],
  templateUrl: './file-workbench.html',
  styleUrl: './file-workbench.scss',
})
export class FileWorkbenchComponent {
  private store = inject(WorkFileStore);
  private registry = inject(OperationRegistryService);
  private kc = inject(KeycloakService);
  private fichierService = inject(FichierService);
  private ocrService = inject(OcrService);

  readonly accept = 'image/*,application/pdf,video/*';

  files = this.store.files;
  busy = this.store.busy;

  dragOver = signal(false);
  message = signal('');
  error = signal('');
  private selected = signal<Set<string>>(new Set());

  private thumbs = signal<Record<string, string>>({});
  private requested = new Set<string>();

  activeForm = signal<FormCtx | null>(null);
  cropCtx = signal<OpCtx | null>(null);
  pagesCtx = signal<OpCtx | null>(null);
  mergeCtx = signal<MergeCtx | null>(null);

  // Clé API Mistral (OCR) — envoyée une fois au serveur, qui la garde chiffrée
  // et ne la renvoie jamais : on ne sait d'elle que « enregistrée ou non ».
  keyConfigured = signal(false);
  keyModal = signal<{ pending: OpCtx | null } | null>(null);
  keyInput = signal('');
  keyError = signal('');
  keySaving = signal(false);

  selectedFiles = computed(() => this.files().filter((f) => this.selected().has(f.id)));
  collectionOps = computed(() => this.registry.collectionOpsFor(this.selectedFiles()));

  constructor() {
    // Ancienne clé gardée par le navigateur : effacée, jamais envoyée (la
    // ressaisir une fois l'enregistre dans le coffre du serveur).
    try { localStorage.removeItem('mistral_api_key'); } catch { /* stockage indisponible */ }
    this.refreshKeyStatus();
    effect(() => {
      for (const f of this.files()) {
        if ((f.kind === 'pdf' || f.kind === 'video') && !this.requested.has(f.previewUrl)) {
          this.requested.add(f.previewUrl);
          void this.makeThumb(f);
        }
      }
    });
  }

  get isAuthenticated(): boolean { return this.kc.isAuthenticated; }

  // ── Import ────────────────────────────────────────────────────────────────
  onInputChange(ev: Event): void {
    const input = ev.target as HTMLInputElement;
    if (input.files?.length) this.store.addFiles(Array.from(input.files));
    input.value = '';
  }

  onDragOver(ev: DragEvent): void { ev.preventDefault(); this.dragOver.set(true); }
  onDragLeave(): void { this.dragOver.set(false); }
  onDrop(ev: DragEvent): void {
    ev.preventDefault();
    this.dragOver.set(false);
    if (ev.dataTransfer?.files.length) this.store.addFiles(Array.from(ev.dataTransfer.files));
  }

  // ── Opérations ────────────────────────────────────────────────────────────
  opsFor(file: WorkFile): FileOperation[] { return this.registry.applicableTo(file); }
  isOpDisabled(op: FileOperation): boolean { return !!op.requiresAuth && !this.isAuthenticated; }

  launch(file: WorkFile, op: FileOperation): void {
    if (this.isOpDisabled(op) || this.busy()) return;
    // OCR par le serveur : connexion et clé enregistrée requises.
    if (op.serverOcr) {
      if (this.isAuthenticated && this.keyConfigured()) void this.runOp(file.id, op, {}, this.ocrCtx());
      else this.openKeyModal({ file, op });
      return;
    }
    switch (op.ui) {
      case 'image-crop': this.cropCtx.set({ file, op }); break;
      case 'pdf-pages': this.pagesCtx.set({ file, op }); break;
      case 'none': void this.runOp(file.id, op, {}); break;
      default: this.activeForm.set({ file, op, params: defaultParams(op) });
    }
  }

  /** Exécute une opération single-file avec remontée d'erreur à l'utilisateur. */
  private async runOp(
    fileId: string, op: FileOperation, params: Record<string, unknown>, ctx?: OperationContext,
  ): Promise<void> {
    this.error.set('');
    try {
      await this.store.applyOperation(fileId, op, params, ctx);
    } catch (e) {
      this.error.set(`« ${op.label} » a échoué : ${errMessage(e)}`);
    }
  }

  async applyForm(): Promise<void> {
    const a = this.activeForm();
    if (!a) return;
    this.activeForm.set(null);
    await this.runOp(a.file.id, a.op, a.params);
  }

  async onCropConfirmed(rect: Rect): Promise<void> {
    const c = this.cropCtx();
    if (!c) return;
    this.cropCtx.set(null);
    await this.runOp(c.file.id, c.op, { ...rect });
  }

  async onPagesConfirmed(order: number[]): Promise<void> {
    const c = this.pagesCtx();
    if (!c) return;
    this.pagesCtx.set(null);
    await this.runOp(c.file.id, c.op, { order });
  }

  // ── Clé API Mistral (coffre du serveur) ──────────────────────────────────
  private ocrCtx(): OperationContext {
    return { ocr: (blob, mime, name) => this.ocrService.run(blob, mime, name) };
  }

  private refreshKeyStatus(): void {
    if (!this.isAuthenticated) { this.keyConfigured.set(false); return; }
    this.ocrService.keyStatus().subscribe({
      next: (r) => this.keyConfigured.set(!!r.mistral_key_configured),
      error: () => this.keyConfigured.set(false),
    });
  }

  openKeyModal(pending: OpCtx | null = null): void {
    this.keyInput.set('');
    this.keyError.set('');
    this.keyModal.set({ pending });
  }

  login(): void { this.kc.login(); }

  saveKey(): void {
    const key = this.keyInput().trim();
    if (!key || !this.isAuthenticated || this.keySaving()) return;
    this.keySaving.set(true);
    this.keyError.set('');
    this.ocrService.setKey(key).subscribe({
      next: () => {
        this.keySaving.set(false);
        this.keyInput.set('');
        this.keyConfigured.set(true);
        const pending = this.keyModal()?.pending ?? null;
        this.keyModal.set(null);
        if (pending) void this.runOp(pending.file.id, pending.op, {}, this.ocrCtx());
      },
      error: () => {
        this.keySaving.set(false);
        this.keyInput.set('');
        this.keyError.set('La clé n\'a pas pu être enregistrée (format refusé ou serveur injoignable).');
      },
    });
  }

  clearKey(): void {
    if (!this.isAuthenticated || this.keySaving()) return;
    this.keySaving.set(true);
    this.keyError.set('');
    this.ocrService.setKey('').subscribe({
      next: () => {
        this.keySaving.set(false);
        this.keyConfigured.set(false);
        this.keyInput.set('');
        this.keyModal.set(null);
      },
      error: () => {
        this.keySaving.set(false);
        this.keyError.set('La clé n\'a pas pu être retirée. Réessayez.');
      },
    });
  }

  // ── Opérations de collection (fusion) ────────────────────────────────────
  startCollectionOp(op: FileOperation): void {
    this.mergeCtx.set({ op, order: [...this.selectedFiles()] });
  }

  moveMerge(i: number, dir: -1 | 1): void {
    const c = this.mergeCtx();
    if (!c) return;
    const order = [...c.order];
    const t = i + dir;
    if (t < 0 || t >= order.length) return;
    [order[i], order[t]] = [order[t], order[i]];
    this.mergeCtx.set({ ...c, order });
  }

  async applyCollectionOp(): Promise<void> {
    const c = this.mergeCtx();
    if (!c) return;
    const op = c.op;
    const ids = c.order.map((f) => f.id);
    this.mergeCtx.set(null);
    this.selected.set(new Set());
    this.error.set('');
    try {
      await this.store.applyMultiOperation(ids, op, {});
    } catch (e) {
      this.error.set(`« ${op.label} » a échoué : ${errMessage(e)}`);
    }
  }

  // ── Sélection ─────────────────────────────────────────────────────────────
  isSelected(id: string): boolean { return this.selected().has(id); }
  toggleSelect(id: string): void {
    const s = new Set(this.selected());
    s.has(id) ? s.delete(id) : s.add(id);
    this.selected.set(s);
  }

  // ── Liste ─────────────────────────────────────────────────────────────────
  remove(id: string): void {
    const s = new Set(this.selected());
    s.delete(id);
    this.selected.set(s);
    this.store.remove(id);
  }

  clearAll(): void {
    this.selected.set(new Set());
    this.store.clear();
  }

  // ── Téléchargement ────────────────────────────────────────────────────────
  download(file: WorkFile): void {
    const url = URL.createObjectURL(file.blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = file.name;
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  downloadAll(): void { this.files().forEach((f) => this.download(f)); }

  // ── Backend (nécessite l'authentification) ───────────────────────────────
  loadFromBackend(): void {
    if (!this.isAuthenticated) return;
    this.error.set('');
    this.fichierService.getMesFichiers({}).subscribe({
      next: (res) => {
        if (!res.results.length) { this.flash('Aucun fichier côté serveur.'); return; }
        res.results.forEach((meta) => {
          this.fichierService.downloadBlob(meta).subscribe({
            next: (blob) => {
              const mime = meta.fichier_type_mime || blob.type || 'application/octet-stream';
              this.store.addFiles([
                workFileFromBlob(blob, meta.nom, mime, { origin: 'backend', backendId: meta.id }),
              ]);
            },
            error: () => this.error.set('Échec du téléchargement d\'un fichier.'),
          });
        });
        this.flash(`${res.results.length} fichier(s) chargé(s) depuis le serveur.`);
      },
      error: () => this.error.set('Impossible de charger vos fichiers.'),
    });
  }

  push(file: WorkFile): void {
    if (!this.isAuthenticated) return;
    const fd = new FormData();
    fd.append('fichier', new File([file.blob], file.name, { type: file.mime }));
    fd.append('nom', file.name.replace(/\.[^.]+$/, ''));
    fd.append('type', kindToBackendType(file.kind));
    this.fichierService.uploadFichier(fd).subscribe({
      next: () => this.flash(`« ${file.name} » envoyé au serveur.`),
      error: () => this.error.set(`Échec de l'envoi de « ${file.name} ».`),
    });
  }

  pushAll(): void {
    if (!this.isAuthenticated) return;
    this.files().forEach((f) => this.push(f));
  }

  // ── Miniatures / affichage ───────────────────────────────────────────────
  thumbFor(file: WorkFile): string {
    if (file.kind === 'image') return file.previewUrl;
    return this.thumbs()[file.previewUrl] ?? '';
  }

  private async makeThumb(file: WorkFile): Promise<void> {
    try {
      if (file.kind === 'pdf') {
        const { renderPdfThumbnail } = await import('../../core/pdf.util');
        const url = await renderPdfThumbnail(file.blob, 1, 220);
        this.thumbs.update((m) => ({ ...m, [file.previewUrl]: url }));
      } else if (file.kind === 'video') {
        const url = await videoThumbnail(file.previewUrl);
        this.thumbs.update((m) => ({ ...m, [file.previewUrl]: url }));
      }
    } catch {
      /* pas de miniature → icône de repli */
    }
  }

  kindLabel(file: WorkFile): string {
    if (file.mime === 'text/html') return 'HTML';
    switch (file.kind) {
      case 'pdf': return 'PDF';
      case 'image': return 'Image';
      case 'video': return 'Vidéo';
      default: return 'Fichier';
    }
  }

  kindIcon(file: WorkFile): string {
    if (file.mime === 'text/html') return '🌐';
    switch (file.kind) {
      case 'pdf': return '📄';
      case 'image': return '🖼️';
      case 'video': return '🎬';
      default: return '📁';
    }
  }

  formatSize(bytes: number): string {
    if (bytes < 1024) return `${bytes} o`;
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} Ko`;
    return `${(bytes / 1024 / 1024).toFixed(2)} Mo`;
  }

  private flash(msg: string): void {
    this.message.set(msg);
    setTimeout(() => this.message.set(''), 4000);
  }
}

/** Capture la première image d'une vidéo (via un object URL same-origin, non taintée). */
function videoThumbnail(src: string): Promise<string> {
  return new Promise((resolve, reject) => {
    const video = document.createElement('video');
    video.muted = true;
    video.preload = 'metadata';
    video.src = src;
    video.onloadeddata = () => {
      try { video.currentTime = Math.min(0.1, (video.duration || 1) / 2); }
      catch { reject(new Error('seek')); }
    };
    video.onseeked = () => {
      const canvas = document.createElement('canvas');
      canvas.width = video.videoWidth || 320;
      canvas.height = video.videoHeight || 180;
      const ctx = canvas.getContext('2d');
      if (!ctx) { reject(new Error('ctx')); return; }
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      resolve(canvas.toDataURL('image/png'));
    };
    video.onerror = () => reject(new Error('video'));
  });
}

function errMessage(e: unknown): string {
  return e instanceof Error ? e.message : String(e);
}
