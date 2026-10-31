import { WorkFile } from '../work-file.model';
import { OcrResponse } from '../mistral-ocr.util';

/** Types de champ pour le formulaire de paramètres générique. */
export type ParamType = 'number' | 'range' | 'text' | 'color' | 'select' | 'boolean';

export interface OperationParamField {
  key: string;
  label: string;
  type: ParamType;
  default?: unknown;
  min?: number;
  max?: number;
  step?: number;
  options?: { value: string; label: string }[];
  hint?: string;
}

export interface OperationResult {
  /** Fichier(s) produit(s) par l'opération. */
  files: WorkFile[];
  /**
   * true  → les `files` remplacent le fichier source (édition en place),
   * false → les `files` sont ajoutés à la liste, la source est conservée.
   */
  replacesSource: boolean;
}

/**
 * UI de saisie des paramètres :
 *  - 'form'        : formulaire générique construit depuis `params`
 *  - 'image-crop'  : overlay de recadrage interactif
 *  - 'pdf-pages'   : gestionnaire de pages (miniatures, réordonner, supprimer)
 *  - 'none'        : exécution immédiate, sans saisie
 */
export type OperationUi = 'form' | 'image-crop' | 'pdf-pages' | 'none';

export interface FileOperation {
  id: string;
  label: string;
  /** Regroupement dans le menu (ex. 'Édition', 'Conversion', 'Assemblage'). */
  group: string;
  ui?: OperationUi;
  /** Détermine l'applicabilité selon le MIME/kind courant du fichier. */
  appliesTo(file: WorkFile): boolean;
  params?: OperationParamField[];
  /** Opération nécessitant une authentification (ops backend). */
  requiresAuth?: boolean;
  /**
   * Opération faite par le serveur de l'app (OCR Mistral, avec la clé du coffre
   * de l'utilisateur) : demande une connexion et passe par `OperationContext.ocr`.
   */
  serverOcr?: boolean;
  /** Opère sur une sélection de fichiers (ex. fusion de PDF). */
  multi?: boolean;
  /** Exécution sur un fichier unique (ops non-multi). */
  run?(file: WorkFile, params: Record<string, unknown>, ctx?: OperationContext): Promise<OperationResult>;
  /** Exécution sur une sélection (ops multi). */
  runMulti?(files: WorkFile[], params: Record<string, unknown>): Promise<OperationResult>;
}

/**
 * Services fournis par l'atelier à une opération qui en a besoin (passé en
 * troisième argument de `run`, jamais dans `params` : `params` est recopié dans
 * l'historique du fichier). Les opérations purement locales l'ignorent.
 */
export interface OperationContext {
  /** OCR par le serveur (`POST /api/ocr/`). */
  ocr?: (blob: Blob, mime: string, name: string) => Promise<OcrResponse>;
}

/** Valeurs par défaut d'une opération, prêtes à alimenter le formulaire. */
export function defaultParams(op: FileOperation): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of op.params ?? []) {
    out[f.key] = f.default;
  }
  return out;
}
