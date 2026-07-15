import { WorkFile } from '../work-file.model';

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
  /** Opération nécessitant une clé API externe (saisie une fois, stockée en localStorage). */
  apiKey?: 'mistral';
  /** Opère sur une sélection de fichiers (ex. fusion de PDF). */
  multi?: boolean;
  /** Exécution sur un fichier unique (ops non-multi). */
  run?(file: WorkFile, params: Record<string, unknown>): Promise<OperationResult>;
  /** Exécution sur une sélection (ops multi). */
  runMulti?(files: WorkFile[], params: Record<string, unknown>): Promise<OperationResult>;
}

/** Valeurs par défaut d'une opération, prêtes à alimenter le formulaire. */
export function defaultParams(op: FileOperation): Record<string, unknown> {
  const out: Record<string, unknown> = {};
  for (const f of op.params ?? []) {
    out[f.key] = f.default;
  }
  return out;
}
