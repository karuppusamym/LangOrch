/**
 * Frontend redaction utilities — mirrors backend app/utils/redaction.py
 * Sensitive keys are redacted before display or logging so passwords / tokens
 * are never shown in plain text in the UI.
 */

const SENSITIVE_PATTERNS = [
  /password/i,
  /token/i,
  /api[_-]?key/i,
  /secret/i,
  /credential/i,
  /authorization/i,
  /^auth$/i,
  /private[_-]?key/i,
  /access[_-]?key/i,
  /client[_-]?secret/i,
];

export const REDACTION_PLACEHOLDER = "***REDACTED***";

export function isSensitiveKey(key: string): boolean {
  return SENSITIVE_PATTERNS.some((p) => p.test(key));
}

/**
 * Recursively redact sensitive fields from a plain object / array.
 * Produces a deep copy — does NOT mutate the original.
 */
export function redactForDisplay(
  data: unknown,
  extraSensitiveKeys?: string[],
  depth = 0
): unknown {
  if (depth > 10) return data;

  const extraPatterns = (extraSensitiveKeys ?? []).map(
    (k) => new RegExp(k, "i")
  );
  const allPatterns = [...SENSITIVE_PATTERNS, ...extraPatterns];

  if (Array.isArray(data)) {
    return data.map((item) => redactForDisplay(item, extraSensitiveKeys, depth + 1));
  }

  if (data !== null && typeof data === "object") {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
      if (allPatterns.some((p) => p.test(k))) {
        out[k] = REDACTION_PLACEHOLDER;
      } else {
        out[k] = redactForDisplay(v, extraSensitiveKeys, depth + 1);
      }
    }
    return out;
  }

  return data;
}

/**
 * Given a variables_schema and input_vars, return a copy of input_vars where
 * any field marked sensitive:true or type:"password" is redacted.
 */
export function redactInputVars(
  inputVars: Record<string, unknown>,
  schema?: Record<string, unknown>
): Record<string, unknown> {
  if (!inputVars) return {};

  const out: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(inputVars)) {
    const meta = (schema?.[k] ?? {}) as Record<string, unknown>;
    const isSensitive =
      !!meta.sensitive ||
      meta.type === "password" ||
      isSensitiveKey(k);
    out[k] = isSensitive ? REDACTION_PLACEHOLDER : v;
  }
  return out;
}

/**
 * Check whether a variables_schema field entry should be treated as sensitive.
 */
export function isFieldSensitive(meta: Record<string, unknown>): boolean {
  return !!meta.sensitive || meta.type === "password" || false;
}

/**
 * Flatten the nested CKP variables_schema format:
 *   { required: { varName: meta }, optional: { varName: meta } }
 * into a flat map where each entry has `required: true/false` injected.
 * If the schema is already flat (each key points directly to a meta object
 * that is NOT a group of variables), it is returned as-is.
 */
export function flattenVariablesSchema(
  raw: Record<string, unknown>
): Record<string, unknown> {
  const keys = Object.keys(raw);
  const isNested =
    keys.length > 0 && keys.every((k) => k === "required" || k === "optional");
  if (!isNested) return raw;
  const flat: Record<string, unknown> = {};
  for (const [varName, meta] of Object.entries(
    (raw.required ?? {}) as Record<string, unknown>
  )) {
    flat[varName] = { required: true, ...(meta as Record<string, unknown>) };
  }
  for (const [varName, meta] of Object.entries(
    (raw.optional ?? {}) as Record<string, unknown>
  )) {
    flat[varName] = { required: false, ...(meta as Record<string, unknown>) };
  }
  return flat;
}
