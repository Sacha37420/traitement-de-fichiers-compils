import { FileOperation } from './operation.model';
import { WorkFile, workFileFromBlob, renameForMime } from '../work-file.model';
import { mistralOcrToHtml } from '../mistral-ocr.util';

const isOcrable = (f: WorkFile): boolean => f.kind === 'image' || f.kind === 'pdf';

/** OCR Mistral → document HTML autonome. Ajoute le HTML, conserve le fichier source. */
const ocrHtml: FileOperation = {
  id: 'mistral-ocr-html',
  label: 'OCR → HTML (Mistral)',
  group: 'Conversion',
  ui: 'none',
  apiKey: 'mistral',
  appliesTo: isOcrable,
  async run(file, params) {
    const apiKey = String(params['apiKey'] ?? '');
    if (!apiKey) throw new Error('Clé API Mistral manquante.');
    const html = await mistralOcrToHtml(file.blob, file.mime, file.name, apiKey);
    const blob = new Blob([html], { type: 'text/html' });
    return {
      files: [workFileFromBlob(blob, renameForMime(file.name, 'text/html'), 'text/html', { origin: 'local' })],
      replacesSource: false,
    };
  },
};

export const OCR_OPERATIONS: FileOperation[] = [ocrHtml];
