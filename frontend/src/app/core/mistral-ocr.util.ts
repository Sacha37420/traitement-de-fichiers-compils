/**
 * OCR Mistral → HTML, appelé **directement depuis le navigateur** (l'API Mistral
 * autorise le CORS). La clé API est fournie par l'appelant (stockée en localStorage
 * côté composant). marked (markdown → HTML) est importé dynamiquement.
 */

const OCR_ENDPOINT = 'https://api.mistral.ai/v1/ocr';

interface OcrImage { id?: string; image_base64?: string; }
interface OcrPage { index?: number; markdown?: string; images?: OcrImage[]; }
interface OcrResponse { pages?: OcrPage[]; }

function blobToDataUri(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error('Lecture du fichier impossible.'));
    reader.readAsDataURL(blob);
  });
}

/** Remplace les références d'images markdown (par id) par leurs data URIs base64. */
function inlineImages(markdown: string, images: OcrImage[]): string {
  let out = markdown;
  for (const img of images) {
    if (!img.id || !img.image_base64) continue;
    const uri = img.image_base64.startsWith('data:')
      ? img.image_base64
      : `data:image/png;base64,${img.image_base64}`;
    out = out.split(`](${img.id})`).join(`](${uri})`);
  }
  return out;
}

function escapeHtml(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

function wrapHtml(title: string, body: string): string {
  return `<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>${escapeHtml(title)}</title>
<style>
  body { font-family: -apple-system, Segoe UI, Roboto, sans-serif; line-height: 1.6;
         max-width: 820px; margin: 2rem auto; padding: 0 1rem; color: #1e293b; }
  img { max-width: 100%; height: auto; }
  table { border-collapse: collapse; width: 100%; margin: 1rem 0; }
  th, td { border: 1px solid #cbd5e1; padding: 6px 10px; text-align: left; }
  hr { border: none; border-top: 1px solid #e2e8f0; margin: 2rem 0; }
  pre { background: #f8fafc; padding: 12px; overflow: auto; border-radius: 6px; }
</style>
</head>
<body>
${body}
</body>
</html>`;
}

/** Envoie le fichier à l'OCR Mistral et renvoie un document HTML autonome. */
export async function mistralOcrToHtml(
  blob: Blob,
  mime: string,
  name: string,
  apiKey: string,
): Promise<string> {
  const dataUri = await blobToDataUri(blob);
  const isPdf = mime === 'application/pdf';
  const document = isPdf
    ? { type: 'document_url', document_url: dataUri }
    : { type: 'image_url', image_url: dataUri };

  let res: Response;
  try {
    res = await fetch(OCR_ENDPOINT, {
      method: 'POST',
      headers: {
        'Authorization': `Bearer ${apiKey}`,
        'Content-Type': 'application/json',
      },
      body: JSON.stringify({
        model: 'mistral-ocr-latest',
        document,
        include_image_base64: true,
      }),
    });
  } catch {
    throw new Error('Impossible de joindre l\'API Mistral (réseau).');
  }

  if (!res.ok) {
    let detail = '';
    try {
      const err = await res.json();
      detail = (err && (err.message || err.detail)) || '';
    } catch { /* corps non-JSON */ }
    if (res.status === 401) throw new Error('Clé API Mistral invalide ou expirée.');
    throw new Error(`Erreur Mistral (${res.status})${detail ? ' : ' + detail : ''}`);
  }

  const data = (await res.json()) as OcrResponse;
  const pages = data.pages ?? [];
  const markdown = pages
    .map((p) => inlineImages(p.markdown ?? '', p.images ?? []))
    .join('\n\n---\n\n');

  const { marked } = await import('marked');
  const body = await marked.parse(markdown || '_Aucun texte détecté._');
  const title = name.replace(/\.[^.]+$/, '');
  return wrapHtml(title, body);
}
