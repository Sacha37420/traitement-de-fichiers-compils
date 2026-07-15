/**
 * Extraction de frames d'une vidéo côté navigateur (élément <video> + canvas).
 *
 * On échantillonne la vidéo à intervalle régulier par seeks successifs, chaque
 * frame étant dessinée sur un canvas puis encodée. Limité aux formats que le
 * navigateur sait décoder (typiquement MP4/H.264, WebM). Aucune dépendance lourde
 * (pas de ffmpeg.wasm) : reste dans le bundle initial.
 */

export interface FrameExtractOptions {
  /** Secondes entre deux images capturées (défaut 1). */
  interval?: number;
  /** Format de sortie (défaut image/png). */
  mime?: string;
  /** Qualité pour les formats avec perte (JPEG). */
  quality?: number;
  /** Garde-fou sur le nombre d'images produites (défaut 200). */
  maxFrames?: number;
}

export function extractVideoFrames(blob: Blob, opts: FrameExtractOptions = {}): Promise<Blob[]> {
  const interval = Math.max(0.05, opts.interval ?? 1);
  const mime = opts.mime ?? 'image/png';
  const quality = opts.quality ?? (mime === 'image/jpeg' ? 0.92 : undefined);
  const maxFrames = Math.max(1, Math.floor(opts.maxFrames ?? 200));

  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const video = document.createElement('video');
    video.muted = true;
    video.preload = 'auto';
    video.src = url;

    const canvas = document.createElement('canvas');
    let ctx: CanvasRenderingContext2D | null = null;
    const frames: Blob[] = [];
    const times: number[] = [];
    let idx = 0;
    let settled = false;

    const cleanup = () => {
      if (settled) return;
      settled = true;
      URL.revokeObjectURL(url);
    };
    const finish = () => { cleanup(); resolve(frames); };
    const fail = (msg: string) => { cleanup(); reject(new Error(msg)); };

    const captureNext = () => {
      if (idx >= times.length) { finish(); return; }
      // Un léger epsilon garantit qu'un seek (et donc l'événement 'seeked') a lieu,
      // y compris pour la première image (currentTime déjà à 0).
      video.currentTime = times[idx];
    };

    video.onloadedmetadata = () => {
      const dur = Number.isFinite(video.duration) ? video.duration : 0;
      canvas.width = video.videoWidth || 320;
      canvas.height = video.videoHeight || 180;
      ctx = canvas.getContext('2d');
      if (!ctx) { fail('Contexte 2D indisponible.'); return; }
      const start = 0.001;
      if (dur > 0) {
        for (let t = start; t < dur && times.length < maxFrames; t += interval) times.push(t);
      }
      if (times.length === 0) times.push(start);
      captureNext();
    };

    video.onseeked = () => {
      if (!ctx) return;
      ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
      canvas.toBlob((b) => {
        if (b) frames.push(b);
        idx++;
        captureNext();
      }, mime, quality);
    };

    video.onerror = () => fail('Vidéo illisible ou format non pris en charge par le navigateur.');
  });
}
