/**
 * Utilitaires de traitement d'image côté navigateur (Canvas 2D).
 * Aucune dépendance lourde : ces fonctions restent dans le bundle initial.
 */

export interface Rect { x: number; y: number; width: number; height: number; }

/** Charge un Blob image en HTMLImageElement (révoque l'URL temporaire ensuite). */
export function loadImage(blob: Blob): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error("Image illisible")); };
    img.src = url;
  });
}

export async function getImageSize(blob: Blob): Promise<{ width: number; height: number }> {
  const img = await loadImage(blob);
  return { width: img.naturalWidth, height: img.naturalHeight };
}

function newCanvas(width: number, height: number): HTMLCanvasElement {
  const canvas = document.createElement('canvas');
  canvas.width = Math.max(1, Math.round(width));
  canvas.height = Math.max(1, Math.round(height));
  return canvas;
}

function ctx2d(canvas: HTMLCanvasElement): CanvasRenderingContext2D {
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error("Contexte 2D indisponible");
  return ctx;
}

export function canvasToBlob(
  canvas: HTMLCanvasElement,
  mime: string,
  quality?: number,
): Promise<Blob> {
  return new Promise((resolve, reject) => {
    canvas.toBlob(
      (b) => (b ? resolve(b) : reject(new Error("Échec de l'encodage image"))),
      mime,
      quality,
    );
  });
}

/** Recadre l'image selon un rectangle (en pixels de l'image source). */
export async function cropImage(blob: Blob, rect: Rect, mime: string): Promise<Blob> {
  const img = await loadImage(blob);
  const w = Math.max(1, Math.round(rect.width));
  const h = Math.max(1, Math.round(rect.height));
  const canvas = newCanvas(w, h);
  const ctx = ctx2d(canvas);
  ctx.drawImage(img, Math.round(rect.x), Math.round(rect.y), w, h, 0, 0, w, h);
  return canvasToBlob(canvas, mime, mime === 'image/jpeg' ? 0.92 : undefined);
}

/** Ré-encode l'image dans un format/qualité donnés (compression). */
export async function recodeImage(blob: Blob, mime: string, quality: number): Promise<Blob> {
  const img = await loadImage(blob);
  const canvas = newCanvas(img.naturalWidth, img.naturalHeight);
  const ctx = ctx2d(canvas);
  // Fond blanc si on part vers un format sans alpha (JPEG) pour éviter le noir.
  if (mime === 'image/jpeg') {
    ctx.fillStyle = '#ffffff';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
  }
  ctx.drawImage(img, 0, 0);
  return canvasToBlob(canvas, mime, quality);
}

/** Garantit un canal alpha (sortie PNG) et applique une opacité globale (0–1). */
export async function applyGlobalAlpha(blob: Blob, opacity: number): Promise<Blob> {
  const img = await loadImage(blob);
  const canvas = newCanvas(img.naturalWidth, img.naturalHeight);
  const ctx = ctx2d(canvas);
  ctx.globalAlpha = Math.min(1, Math.max(0, opacity));
  ctx.drawImage(img, 0, 0);
  return canvasToBlob(canvas, 'image/png');
}

/**
 * Rend transparente une couleur cible (± tolérance sur chaque canal RGB).
 * Sortie PNG (canal alpha requis).
 */
export async function colorToTransparent(
  blob: Blob,
  hexColor: string,
  tolerance: number,
): Promise<Blob> {
  const img = await loadImage(blob);
  const canvas = newCanvas(img.naturalWidth, img.naturalHeight);
  const ctx = ctx2d(canvas);
  ctx.drawImage(img, 0, 0);
  const target = hexToRgb(hexColor);
  const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
  const data = image.data;
  const tol = Math.max(0, tolerance);
  for (let i = 0; i < data.length; i += 4) {
    if (
      Math.abs(data[i] - target.r) <= tol &&
      Math.abs(data[i + 1] - target.g) <= tol &&
      Math.abs(data[i + 2] - target.b) <= tol
    ) {
      data[i + 3] = 0;
    }
  }
  ctx.putImageData(image, 0, 0);
  return canvasToBlob(canvas, 'image/png');
}

export function hexToRgb(hex: string): { r: number; g: number; b: number } {
  const clean = hex.replace('#', '');
  const full = clean.length === 3
    ? clean.split('').map((c) => c + c).join('')
    : clean.padEnd(6, '0').slice(0, 6);
  const num = parseInt(full, 16);
  return { r: (num >> 16) & 255, g: (num >> 8) & 255, b: num & 255 };
}
