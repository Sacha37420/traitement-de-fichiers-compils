/**
 * Mise en forme du résultat de l'OCR Mistral en document HTML autonome.
 *
 * L'OCR lui-même est fait par le serveur de l'app (`POST /api/ocr/`, avec la clé
 * du coffre de l'utilisateur — `OcrService`) : ce fichier ne contacte personne.
 * marked (markdown → HTML) est importé dynamiquement.
 */

export interface OcrImage { id?: string; image_base64?: string; }
export interface OcrPage { markdown?: string; images?: OcrImage[]; }
export interface OcrResponse { pages?: OcrPage[]; }

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

/** Réponse de l'OCR (déjà obtenue du serveur) → document HTML autonome. */
export async function ocrResultToHtml(data: OcrResponse, name: string): Promise<string> {
  const pages = data.pages ?? [];
  const markdown = pages
    .map((p) => inlineImages(p.markdown ?? '', p.images ?? []))
    .join('\n\n---\n\n');

  const { marked } = await import('marked');
  const body = await marked.parse(markdown || '_Aucun texte détecté._');
  const title = name.replace(/\.[^.]+$/, '');
  return wrapHtml(title, body);
}
