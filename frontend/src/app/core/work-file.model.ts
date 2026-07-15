/**
 * Modèle client d'un fichier en cours de traitement dans l'atelier.
 *
 * Tout est manipulé côté navigateur (offline-first) : le `blob` est le binaire
 * courant, qui évolue au fil des opérations. `mime`/`kind` peuvent changer après
 * une opération (ex. PDF → images), ce qui recalcule automatiquement les actions
 * disponibles (voir OperationRegistryService).
 */

export type FileKind = 'pdf' | 'image' | 'video' | 'other';

export interface OperationRecord {
  opId: string;
  label: string;
  params?: Record<string, unknown>;
  date: string;
}

export interface WorkFile {
  /** Identifiant local stable (uuid), indépendant du backend. */
  id: string;
  /** Nom d'affichage, extension comprise. */
  name: string;
  /** Type MIME courant (peut changer après une opération). */
  mime: string;
  /** Catégorie dérivée du MIME. */
  kind: FileKind;
  /** Binaire courant. */
  blob: Blob;
  /** URL.createObjectURL(blob) pour la prévisualisation — révoquée au remplacement. */
  previewUrl: string;
  /** Provenance : sélection locale ou chargé depuis le backend. */
  origin: 'local' | 'backend';
  /** Id du Fichier backend si origin === 'backend'. */
  backendId?: number;
  /** Historique des opérations appliquées. */
  history: OperationRecord[];
}

export function kindFromMime(mime: string): FileKind {
  if (mime === 'application/pdf') return 'pdf';
  if (mime.startsWith('image/')) return 'image';
  if (mime.startsWith('video/')) return 'video';
  return 'other';
}

/** Mappe un `kind` vers le champ `type` attendu par le backend Django. */
export function kindToBackendType(kind: FileKind): string {
  switch (kind) {
    case 'pdf': return 'PDF';
    case 'image': return 'Image';
    case 'video': return 'Video';
    default: return 'PDF';
  }
}

function uuid(): string {
  return crypto.randomUUID();
}

/** Construit un WorkFile à partir d'un Blob (crée l'object URL de preview). */
export function workFileFromBlob(
  blob: Blob,
  name: string,
  mime: string,
  opts: { origin?: 'local' | 'backend'; backendId?: number; history?: OperationRecord[] } = {},
): WorkFile {
  return {
    id: uuid(),
    name,
    mime,
    kind: kindFromMime(mime),
    blob,
    previewUrl: URL.createObjectURL(blob),
    origin: opts.origin ?? 'local',
    backendId: opts.backendId,
    history: opts.history ?? [],
  };
}

/** Construit un WorkFile à partir d'un File issu d'un <input> ou d'un drag-&-drop. */
export function workFileFromFile(file: File): WorkFile {
  const mime = file.type || guessMimeFromName(file.name);
  return workFileFromBlob(file, file.name, mime, { origin: 'local' });
}

/**
 * Produit un nouveau WorkFile dérivé d'un fichier source après une opération :
 * conserve l'id (édition en place) et recrée un blob/preview/mime.
 */
export function deriveWorkFile(
  source: WorkFile,
  blob: Blob,
  mime: string,
  name?: string,
): WorkFile {
  return {
    ...source,
    name: name ?? source.name,
    mime,
    kind: kindFromMime(mime),
    blob,
    previewUrl: URL.createObjectURL(blob),
    // l'historique et l'id sont conservés ; le blob/preview sont neufs.
  };
}

const EXT_MIME: Record<string, string> = {
  pdf: 'application/pdf',
  png: 'image/png',
  jpg: 'image/jpeg',
  jpeg: 'image/jpeg',
  webp: 'image/webp',
  gif: 'image/gif',
  bmp: 'image/bmp',
  svg: 'image/svg+xml',
  mp4: 'video/mp4',
  webm: 'video/webm',
  mov: 'video/quicktime',
};

function guessMimeFromName(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase() ?? '';
  return EXT_MIME[ext] ?? 'application/octet-stream';
}

/** Remplace (ou ajoute) l'extension d'un nom de fichier selon un nouveau MIME. */
export function renameForMime(name: string, mime: string): string {
  const ext = mimeToExt(mime);
  const base = name.replace(/\.[^.]+$/, '');
  return ext ? `${base}.${ext}` : base;
}

export function mimeToExt(mime: string): string {
  switch (mime) {
    case 'application/pdf': return 'pdf';
    case 'image/png': return 'png';
    case 'image/jpeg': return 'jpg';
    case 'image/webp': return 'webp';
    case 'image/gif': return 'gif';
    case 'image/bmp': return 'bmp';
    case 'image/svg+xml': return 'svg';
    case 'video/mp4': return 'mp4';
    case 'video/webm': return 'webm';
    default: return '';
  }
}
