import type { EditorFieldDefinition, EditorTemplate } from "@/builder-v2/inspector/shared/structured-editors";

export interface BuilderNodeEditorValidationRule {
  required?: boolean;
  min?: number;
  minItems?: number;
  nonEmptyObject?: boolean;
  message?: string;
}

export type BuilderNodeEditorValueControl = {
  kind: "text" | "textarea" | "number" | "checkbox" | "select";
  label: string;
  keys: string[];
  placeholder?: string;
  rows?: number;
  defaultValue?: string | number | boolean;
  options?: string[];
  validation?: BuilderNodeEditorValidationRule;
};

export type BuilderNodeEditorObjectControl = {
  kind: "object";
  label: string;
  keys: string[];
  fields?: EditorFieldDefinition[];
  templates?: EditorTemplate[];
  addButtonLabel?: string;
  emptyState?: string;
  validation?: BuilderNodeEditorValidationRule;
};

export type BuilderNodeEditorObjectListControl = {
  kind: "object-list";
  label: string;
  keys: string[];
  fields?: EditorFieldDefinition[];
  templates?: EditorTemplate[];
  newItem: Record<string, unknown>;
  addItemLabel?: string;
  emptyState?: string;
  validation?: BuilderNodeEditorValidationRule;
};

export type BuilderNodeEditorControl =
  | BuilderNodeEditorValueControl
  | BuilderNodeEditorObjectControl
  | BuilderNodeEditorObjectListControl;

export interface BuilderNodeEditorSection {
  title?: string;
  controls: BuilderNodeEditorControl[];
}

export function readConfigValue(config: Record<string, unknown>, keys: string[], defaultValue?: unknown): unknown {
  for (const key of keys) {
    const value = config[key];
    if (value !== undefined) {
      return value;
    }
  }
  return defaultValue;
}

export function createConfigPatch(keys: string[], value: unknown): Record<string, unknown> {
  return Object.fromEntries(keys.map((key) => [key, value]));
}

export function validateControlValue(control: BuilderNodeEditorControl, value: unknown): string | null {
  const validation = control.validation;
  if (!validation) {
    return null;
  }

  if (validation.required) {
    if (typeof value === "string" && value.trim().length === 0) {
      return validation.message ?? `${control.label} is required.`;
    }
    if (value === undefined || value === null) {
      return validation.message ?? `${control.label} is required.`;
    }
  }

  if (typeof validation.min === "number") {
    const numericValue = typeof value === "number" ? value : Number(value);
    if (!Number.isNaN(numericValue) && numericValue < validation.min) {
      return validation.message ?? `${control.label} must be at least ${validation.min}.`;
    }
  }

  if (typeof validation.minItems === "number") {
    if (Array.isArray(value) && value.length < validation.minItems) {
      return validation.message ?? `${control.label} must include at least ${validation.minItems} item(s).`;
    }
  }

  if (validation.nonEmptyObject) {
    if (value && typeof value === "object" && !Array.isArray(value) && Object.keys(value as Record<string, unknown>).length === 0) {
      return validation.message ?? `${control.label} cannot be empty.`;
    }
  }

  return null;
}