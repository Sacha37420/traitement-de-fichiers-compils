/**
 * Utilitaires PDF côté navigateur.
 *
 * pdf-lib (assemblage/pages) et pdfjs-dist (rendu) sont **importés dynamiquement**
 * pour rester hors du bundle initial (cf. budget de build). Ce module ne fait donc
 * aucun import statique de ces bibliothèques.
 */

async function pdfBytes(blob: Blob): Promise<Uint8Array> {
  return new Uint8Array(await blob.arrayBuffer());
}

// ── pdfjs (rendu) ───────────────────────────────────────────────────────────

let pdfjsReady: Promise<typeof import('pdfjs-dist')> | null = null;

async function getPdfjs(): Promise<typeof import('pdfjs-dist')> {
  if (!pdfjsReady) {
    pdfjsReady = import('pdfjs-dist').then((pdfjs) => {
      // Worker copié dans assets/ (cf. angular.json). Résolu contre le <base href>
      // pour fonctionner en dev ('/') comme derrière Caddy ('/…/').
      pdfjs.GlobalWorkerOptions.workerSrc = new URL(
        'assets/pdf.worker.min.mjs',
        document.baseURI,
      ).href;
      return pdfjs;
    });
  }
  return pdfjsReady;
}

async function loadPdfDocument(blob: Blob) {
  const pdfjs = await getPdfjs();
  const data = await pdfBytes(blob);
  const task = pdfjs.getDocument({ data });
  const doc = await task.promise;
  return { doc, task };
}

export async function getPdfPageCount(blob: Blob): Promise<number> {
  const { doc, task } = await loadPdfDocument(blob);
  const n = doc.numPages;
  await task.destroy();
  return n;
}

async function renderPageToCanvas(
  page: import('pdfjs-dist').PDFPageProxy,
  scale: number,
): Promise<HTMLCanvasElement> {
  const viewport = page.getViewport({ scale });
  const canvas = document.createElement('canvas');
  canvas.width = Math.ceil(viewport.width);
  canvas.height = Math.ceil(viewport.height);
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Contexte 2D indisponible');
  await page.render({ canvas, canvasContext: ctx, viewport }).promise;
  return canvas;
}

function canvasToBlob(canvas: HTMLCanvasElement, mime: string, quality?: number): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("Échec de l'encodage de la page"))),
      mime,
      quality,
    );
  });
}

/** Rend une page (1-based) en data URL — utilisé pour les miniatures. */
export async function renderPdfThumbnail(
  blob: Blob,
  pageNumber: number,
  maxWidth = 160,
): Promise<string> {
  const { doc, task } = await loadPdfDocument(blob);
  const page = await doc.getPage(pageNumber);
  const base = page.getViewport({ scale: 1 });
  const scale = Math.min(1, maxWidth / base.width);
  const canvas = await renderPageToCanvas(page, scale);
  const url = canvas.toDataURL('image/png');
  await task.destroy();
  return url;
}

/** Rend toutes les pages du PDF en images (une par page). */
export async function pdfToImageBlobs(
  blob: Blob,
  opts: { scale?: number; mime?: string; quality?: number } = {},
): Promise<Blob[]> {
  const scale = opts.scale ?? 2;
  const mime = opts.mime ?? 'image/png';
  const quality = opts.quality ?? (mime === 'image/jpeg' ? 0.92 : undefined);
  const { doc, task } = await loadPdfDocument(blob);
  const out: Blob[] = [];
  for (let i = 1; i <= doc.numPages; i++) {
    const page = await doc.getPage(i);
    const canvas = await renderPageToCanvas(page, scale);
    out.push(await canvasToBlob(canvas, mime, quality));
    page.cleanup();
  }
  await task.destroy();
  return out;
}

// ── pdf-lib (assemblage) ─────────────────────────────────────────────────────

/**
 * Reconstruit un PDF à partir d'un ordre de pages (indices 0-based, dans l'ordre
 * voulu). Les pages absentes de `order` sont supprimées.
 */
export async function reorderDeletePages(blob: Blob, order: number[]): Promise<Blob> {
  const { PDFDocument } = await import('pdf-lib');
  const src = await PDFDocument.load(await blob.arrayBuffer());
  const out = await PDFDocument.create();
  const copied = await out.copyPages(src, order);
  copied.forEach((p) => out.addPage(p));
  const bytes = await out.save();
  return new Blob([bytes as BlobPart], { type: 'application/pdf' });
}

/** Fusionne plusieurs PDF dans l'ordre fourni en un seul document. */
export async function mergePdfs(blobs: Blob[]): Promise<Blob> {
  const { PDFDocument } = await import('pdf-lib');
  const out = await PDFDocument.create();
  for (const blob of blobs) {
    const src = await PDFDocument.load(await blob.arrayBuffer());
    const copied = await out.copyPages(src, src.getPageIndices());
    copied.forEach((p) => out.addPage(p));
  }
  const bytes = await out.save();
  return new Blob([bytes as BlobPart], { type: 'application/pdf' });
}
