import { FileOperation } from './operation.model';
import { WorkFile, workFileFromBlob, renameForMime } from '../work-file.model';
import { ocrResultToHtml } from '../mistral-ocr.util';

/** Types que l'OCR du serveur accepte (`OCR_TYPES`, backend/api/views.py). */
export const OCR_MIMES = ['application/pdf', 'image/png', 'image/jpeg', 'image/webp', 'image/gif'];

const isOcrable = (f: WorkFile): boolean =>
  (f.kind === 'image' || f.kind === 'pdf') && OCR_MIMES.includes(f.mime.toLowerCase());

/**
 * OCR Mistral → document HTML autonome. L'OCR est fait par le serveur de l'app
 * (clé Mistral du coffre de l'utilisateur) ; la mise en forme reste ici. Ajoute
 * le HTML, conserve le fichier source.
 */
const ocrHtml: FileOperation = {
  id: 'mistral-ocr-html',
  label: 'OCR → HTML (Mistral)',
  group: 'Conversion',
  ui: 'none',
  serverOcr: true,
  appliesTo: isOcrable,
  async run(file, _params, ctx) {
    if (!ctx?.ocr) throw new Error('Connexion requise pour l\'OCR.');
    const data = await ctx.ocr(file.blob, file.mime, file.name);
    const html = await ocrResultToHtml(data, file.name);
    const blob = new Blob([html], { type: 'text/html' });
    return {
      files: [workFileFromBlob(blob, renameForMime(file.name, 'text/html'), 'text/html', { origin: 'local' })],
      replacesSource: false,
    };
  },
};

export const OCR_OPERATIONS: FileOperation[] = [ocrHtml];
