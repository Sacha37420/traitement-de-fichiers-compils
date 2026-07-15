/**
 * Vectorisation raster → SVG côté navigateur via imagetracerjs (import dynamique).
 * Les grandes images sont réduites avant tracé pour limiter le temps de calcul et
 * la taille du SVG.
 */
import { loadImage } from './image-canvas.util';

export async function vectorizeImage(
  blob: Blob,
  preset = 'default',
  maxDim = 1400,
): Promise<Blob> {
  const img = await loadImage(blob);
  const ratio = Math.min(1, maxDim / Math.max(img.naturalWidth, img.naturalHeight));
  const w = Math.max(1, Math.round(img.naturalWidth * ratio));
  const h = Math.max(1, Math.round(img.naturalHeight * ratio));

  const canvas = document.createElement('canvas');
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext('2d');
  if (!ctx) throw new Error('Contexte 2D indisponible.');
  ctx.drawImage(img, 0, 0, w, h);
  const data = ctx.getImageData(0, 0, w, h);

  const mod = await import('imagetracerjs');
  const svg = mod.default.imagedataToSVG(data, preset);
  return new Blob([svg], { type: 'image/svg+xml' });
}
