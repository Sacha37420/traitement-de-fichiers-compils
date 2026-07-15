import { FileOperation } from './operation.model';
import { WorkFile, deriveWorkFile, renameForMime } from '../work-file.model';
import {
  cropImage,
  recodeImage,
  applyGlobalAlpha,
  colorToTransparent,
  Rect,
} from '../image-canvas.util';

const isImage = (f: WorkFile): boolean => f.kind === 'image';

/** Recadrage — paramètres fournis par l'overlay interactif. */
const crop: FileOperation = {
  id: 'image-crop',
  label: 'Recadrer',
  group: 'Édition',
  ui: 'image-crop',
  appliesTo: isImage,
  async run(file, params) {
    const rect: Rect = {
      x: Number(params['x'] ?? 0),
      y: Number(params['y'] ?? 0),
      width: Number(params['width'] ?? 0),
      height: Number(params['height'] ?? 0),
    };
    // Un format sans alpha reste identique ; PNG/WebP conservent l'alpha.
    const mime = file.mime === 'image/jpeg' ? 'image/jpeg' : 'image/png';
    const blob = await cropImage(file.blob, rect, mime);
    return {
      files: [deriveWorkFile(file, blob, mime, renameForMime(file.name, mime))],
      replacesSource: true,
    };
  },
};

/** Compression — ré-encodage avec un format et une qualité choisis. */
const compress: FileOperation = {
  id: 'image-compress',
  label: 'Compresser',
  group: 'Édition',
  ui: 'form',
  appliesTo: isImage,
  params: [
    {
      key: 'format', label: 'Format', type: 'select', default: 'image/jpeg',
      options: [
        { value: 'image/jpeg', label: 'JPEG' },
        { value: 'image/webp', label: 'WebP' },
      ],
    },
    { key: 'quality', label: 'Qualité', type: 'range', default: 0.7, min: 0.1, max: 1, step: 0.05 },
  ],
  async run(file, params) {
    const mime = String(params['format'] ?? 'image/jpeg');
    const quality = Number(params['quality'] ?? 0.7);
    const blob = await recodeImage(file.blob, mime, quality);
    return {
      files: [deriveWorkFile(file, blob, mime, renameForMime(file.name, mime))],
      replacesSource: true,
    };
  },
};

/** Ajout d'un canal alpha (transparence) — sortie PNG. */
const addAlpha: FileOperation = {
  id: 'image-add-alpha',
  label: 'Ajouter de la transparence',
  group: 'Édition',
  ui: 'form',
  appliesTo: isImage,
  params: [
    { key: 'opacity', label: 'Opacité', type: 'range', default: 1, min: 0, max: 1, step: 0.05 },
  ],
  async run(file, params) {
    const opacity = Number(params['opacity'] ?? 1);
    const blob = await applyGlobalAlpha(file.blob, opacity);
    return {
      files: [deriveWorkFile(file, blob, 'image/png', renameForMime(file.name, 'image/png'))],
      replacesSource: true,
    };
  },
};

/** Rend transparente une couleur cible (± tolérance RGB) — sortie PNG. */
const colorTransparent: FileOperation = {
  id: 'image-color-to-transparent',
  label: 'Rendre une couleur transparente',
  group: 'Édition',
  ui: 'form',
  appliesTo: isImage,
  params: [
    { key: 'color', label: 'Couleur à retirer', type: 'color', default: '#ffffff' },
    {
      key: 'tolerance', label: 'Tolérance', type: 'range', default: 30, min: 0, max: 255, step: 1,
      hint: 'Écart maximal accepté sur chaque canal RVB.',
    },
  ],
  async run(file, params) {
    const color = String(params['color'] ?? '#ffffff');
    const tolerance = Number(params['tolerance'] ?? 30);
    const blob = await colorToTransparent(file.blob, color, tolerance);
    return {
      files: [deriveWorkFile(file, blob, 'image/png', renameForMime(file.name, 'image/png'))],
      replacesSource: true,
    };
  },
};

export const IMAGE_OPERATIONS: FileOperation[] = [crop, compress, addAlpha, colorTransparent];
