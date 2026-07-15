import { FileOperation } from './operation.model';
import {
  WorkFile,
  deriveWorkFile,
  workFileFromBlob,
} from '../work-file.model';
import { reorderDeletePages, pdfToImageBlobs, mergePdfs, compressPdf } from '../pdf.util';

const isPdf = (f: WorkFile): boolean => f.kind === 'pdf';

/** Réorganisation / suppression de pages — `order` fourni par le gestionnaire de pages. */
const pages: FileOperation = {
  id: 'pdf-pages',
  label: 'Réorganiser / supprimer des pages',
  group: 'Édition',
  ui: 'pdf-pages',
  appliesTo: isPdf,
  async run(file, params) {
    const order = (params['order'] as number[] | undefined) ?? [];
    if (order.length === 0) {
      // Aucune page conservée : on ne produit rien, la source est gardée.
      return { files: [file], replacesSource: true };
    }
    const blob = await reorderDeletePages(file.blob, order);
    return {
      files: [deriveWorkFile(file, blob, 'application/pdf')],
      replacesSource: true,
    };
  },
};

/** Conversion en images (une par page) — ajoute les images, garde le PDF. */
const toImages: FileOperation = {
  id: 'pdf-to-images',
  label: 'Convertir en images (1 par page)',
  group: 'Conversion',
  ui: 'form',
  appliesTo: isPdf,
  params: [
    { key: 'scale', label: 'Résolution', type: 'range', default: 2, min: 1, max: 4, step: 0.5,
      hint: 'Facteur d\'échelle du rendu (2 = 144 dpi environ).' },
    {
      key: 'format', label: 'Format', type: 'select', default: 'image/png',
      options: [
        { value: 'image/png', label: 'PNG' },
        { value: 'image/jpeg', label: 'JPEG' },
      ],
    },
  ],
  async run(file, params) {
    const scale = Number(params['scale'] ?? 2);
    const mime = String(params['format'] ?? 'image/png');
    const ext = mime === 'image/jpeg' ? 'jpg' : 'png';
    const blobs = await pdfToImageBlobs(file.blob, { scale, mime });
    const base = file.name.replace(/\.[^.]+$/, '');
    const files = blobs.map((blob, i) =>
      workFileFromBlob(blob, `${base}-p${i + 1}.${ext}`, mime, { origin: 'local' }),
    );
    return { files, replacesSource: false };
  },
};

/** Fusion de plusieurs PDF dans l'ordre de la sélection (réordonnable en amont). */
const merge: FileOperation = {
  id: 'pdf-merge',
  label: 'Fusionner les PDF sélectionnés',
  group: 'Assemblage',
  ui: 'none',
  multi: true,
  appliesTo: isPdf,
  async runMulti(files) {
    const blob = await mergePdfs(files.map((f) => f.blob));
    return {
      files: [workFileFromBlob(blob, 'fusion.pdf', 'application/pdf', { origin: 'local' })],
      replacesSource: false,
    };
  },
};

/** Compression rasterisée (pages → JPEG → PDF). Remplace le PDF ; perd le texte. */
const compress: FileOperation = {
  id: 'pdf-compress',
  label: 'Compresser (rasterisé)',
  group: 'Édition',
  ui: 'form',
  appliesTo: isPdf,
  params: [
    { key: 'quality', label: 'Qualité', type: 'range', default: 0.6, min: 0.3, max: 0.9, step: 0.05 },
    {
      key: 'scale', label: 'Résolution', type: 'range', default: 1.5, min: 1, max: 3, step: 0.5,
      hint: 'Rasterise les pages (le texte sélectionnable est perdu). Idéal pour les PDF scannés.',
    },
  ],
  async run(file, params) {
    const quality = Number(params['quality'] ?? 0.6);
    const scale = Number(params['scale'] ?? 1.5);
    const blob = await compressPdf(file.blob, { scale, quality });
    return { files: [deriveWorkFile(file, blob, 'application/pdf')], replacesSource: true };
  },
};

export const PDF_OPERATIONS: FileOperation[] = [pages, toImages, merge, compress];
