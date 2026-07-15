import { FileOperation } from './operation.model';
import { WorkFile, workFileFromBlob } from '../work-file.model';
import { extractVideoFrames } from '../video-frames.util';

const isVideo = (f: WorkFile): boolean => f.kind === 'video';

/**
 * Extrait la liste des images d'une vidéo (échantillonnage régulier). Les images
 * produites héritent ensuite de tous les traitements image (recadrage, OCR…) via
 * le registre — elles apparaissent comme des fichiers image à part entière.
 */
const extractFrames: FileOperation = {
  id: 'video-extract-frames',
  label: 'Extraire les images (frames)',
  group: 'Conversion',
  ui: 'form',
  appliesTo: isVideo,
  params: [
    {
      key: 'interval', label: 'Intervalle (secondes)', type: 'number', default: 1, min: 0.1, step: 0.1,
      hint: 'Une image capturée toutes les N secondes.',
    },
    { key: 'maxFrames', label: "Nombre max d'images", type: 'number', default: 60, min: 1, step: 1 },
    {
      key: 'format', label: 'Format', type: 'select', default: 'image/png',
      options: [
        { value: 'image/png', label: 'PNG' },
        { value: 'image/jpeg', label: 'JPEG' },
      ],
    },
  ],
  async run(file, params) {
    const interval = Number(params['interval'] ?? 1);
    const maxFrames = Number(params['maxFrames'] ?? 60);
    const mime = String(params['format'] ?? 'image/png');
    const ext = mime === 'image/jpeg' ? 'jpg' : 'png';
    const blobs = await extractVideoFrames(file.blob, { interval, mime, maxFrames });
    if (blobs.length === 0) {
      throw new Error('Aucune image extraite (vidéo vide ou format non pris en charge).');
    }
    const base = file.name.replace(/\.[^.]+$/, '');
    const files = blobs.map((b, i) =>
      workFileFromBlob(b, `${base}-frame-${i + 1}.${ext}`, mime, { origin: 'local' }),
    );
    return { files, replacesSource: false };
  },
};

export const VIDEO_OPERATIONS: FileOperation[] = [extractFrames];
