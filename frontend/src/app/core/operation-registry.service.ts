import { Injectable } from '@angular/core';
import { WorkFile } from './work-file.model';
import { FileOperation } from './operations/operation.model';
import { IMAGE_OPERATIONS } from './operations/image.ops';
import { PDF_OPERATIONS } from './operations/pdf.ops';
import { OCR_OPERATIONS } from './operations/ocr.ops';
import { VIDEO_OPERATIONS } from './operations/video.ops';

/**
 * Registre central des opérations. `applicableTo` est recalculé à chaque rendu
 * depuis le MIME/kind courant du fichier : une opération qui change le format
 * (ex. PDF → images) fait donc évoluer automatiquement les actions proposées.
 */
@Injectable({ providedIn: 'root' })
export class OperationRegistryService {
  private readonly all: FileOperation[] = [
    ...IMAGE_OPERATIONS,
    ...PDF_OPERATIONS,
    ...VIDEO_OPERATIONS,
    ...OCR_OPERATIONS,
  ];

  /** Opérations single-file applicables à ce fichier. */
  applicableTo(file: WorkFile): FileOperation[] {
    return this.all.filter((op) => !op.multi && op.appliesTo(file));
  }

  /** Opérations de collection applicables à une sélection (≥ 2 fichiers compatibles). */
  collectionOpsFor(files: WorkFile[]): FileOperation[] {
    if (files.length < 2) return [];
    return this.all.filter((op) => op.multi && files.every((f) => op.appliesTo(f)));
  }

  byId(id: string): FileOperation | undefined {
    return this.all.find((op) => op.id === id);
  }
}
