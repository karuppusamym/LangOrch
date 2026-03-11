import { useEffect, useMemo } from "react";

import type { BuilderNodeDraft } from "@/builder-v2/reference-contract";
import type { BuilderNodeEditorControl, BuilderNodeEditorSection } from "@/builder-v2/inspector/editor-schema";
import { createConfigPatch, readConfigValue, validateControlValue } from "@/builder-v2/inspector/editor-schema";
import { normalizeEditableObject, StructuredObjectEditor, StructuredObjectListEditor } from "@/builder-v2/inspector/shared/structured-editors";

interface RegistryNodeConfigEditorProps {
  node: BuilderNodeDraft;
  layout: BuilderNodeEditorSection[];
  onUpdateConfig: (patch: Record<string, unknown>) => void;
  onValidationChange?: (errors: string[]) => void;
}

function getControlValue(node: BuilderNodeDraft, control: BuilderNodeEditorControl): unknown {
  const defaultValue = "defaultValue" in control ? control.defaultValue : undefined;
  return readConfigValue(node.config, control.keys, defaultValue);
}

function renderValidationMessage(message: string | null) {
  if (!message) {
    return null;
  }

  return <p className="mt-1 text-xs text-red-600">{message}</p>;
}

function renderControl(
  control: BuilderNodeEditorControl,
  node: BuilderNodeDraft,
  onUpdateConfig: (patch: Record<string, unknown>) => void,
) {
  if (control.kind === "text" || control.kind === "number") {
    const value = getControlValue(node, control);
    const validationMessage = validateControlValue(control, value);
    return (
      <div key={`${node.id}-${control.label}`}>
        <label className="mb-1 block text-xs font-medium text-neutral-500">{control.label}</label>
        <input
          type={control.kind === "number" ? "number" : "text"}
          value={value === undefined ? "" : String(value)}
          placeholder={control.placeholder}
          onChange={(event) => onUpdateConfig(createConfigPatch(control.keys, control.kind === "number"
            ? (event.target.value ? Number(event.target.value) : undefined)
            : event.target.value))}
          className={`w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-indigo-400 ${validationMessage ? "border-red-300" : "border-neutral-200"}`}
        />
        {renderValidationMessage(validationMessage)}
      </div>
    );
  }

  if (control.kind === "textarea") {
    const value = getControlValue(node, control);
    const validationMessage = validateControlValue(control, value);
    return (
      <div key={`${node.id}-${control.label}`}>
        <label className="mb-1 block text-xs font-medium text-neutral-500">{control.label}</label>
        <textarea
          rows={control.rows ?? 3}
          value={value === undefined ? "" : String(value)}
          placeholder={control.placeholder}
          onChange={(event) => onUpdateConfig(createConfigPatch(control.keys, event.target.value))}
          className={`w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-indigo-400 ${validationMessage ? "border-red-300" : "border-neutral-200"}`}
        />
        {renderValidationMessage(validationMessage)}
      </div>
    );
  }

  if (control.kind === "checkbox") {
    const value = Boolean(getControlValue(node, control));
    return (
      <label key={`${node.id}-${control.label}`} className="flex items-center gap-2 rounded-xl border border-neutral-200 px-3 py-2 text-sm text-neutral-700">
        <input
          type="checkbox"
          checked={value}
          onChange={(event) => onUpdateConfig(createConfigPatch(control.keys, event.target.checked))}
        />
        {control.label}
      </label>
    );
  }

  if (control.kind === "select") {
    const value = getControlValue(node, control);
    const validationMessage = validateControlValue(control, value);
    return (
      <div key={`${node.id}-${control.label}`}>
        <label className="mb-1 block text-xs font-medium text-neutral-500">{control.label}</label>
        <select
          aria-label={control.label}
          value={value === undefined ? "" : String(value)}
          onChange={(event) => onUpdateConfig(createConfigPatch(control.keys, event.target.value))}
          className={`w-full rounded-xl border px-3 py-2 text-sm outline-none focus:border-indigo-400 ${validationMessage ? "border-red-300" : "border-neutral-200"}`}
        >
          {(control.options ?? []).map((option) => <option key={option} value={option}>{option}</option>)}
        </select>
        {renderValidationMessage(validationMessage)}
      </div>
    );
  }

  if (control.kind === "object") {
    const value = normalizeEditableObject(readConfigValue(node.config, control.keys));
    const validationMessage = validateControlValue(control, value);
    return (
      <div key={`${node.id}-${control.label}`}>
        <StructuredObjectEditor
          label={control.label}
          value={value}
          fields={control.fields}
          templates={control.templates}
          addButtonLabel={control.addButtonLabel}
          emptyState={control.emptyState}
          onChange={(nextValue) => onUpdateConfig(createConfigPatch(control.keys, nextValue))}
        />
        {renderValidationMessage(validationMessage)}
      </div>
    );
  }

  if (control.kind === "object-list") {
    const items = (readConfigValue(node.config, control.keys) as unknown[] | undefined) ?? [];
    const validationMessage = validateControlValue(control, items);
    return (
      <div key={`${node.id}-${control.label}`}>
        <StructuredObjectListEditor
          label={control.label}
          items={items}
          newItem={control.newItem}
          fields={control.fields}
          templates={control.templates}
          addItemLabel={control.addItemLabel}
          emptyState={control.emptyState}
          onChange={(nextItems) => onUpdateConfig(createConfigPatch(control.keys, nextItems))}
        />
        {renderValidationMessage(validationMessage)}
      </div>
    );
  }

  return null;
}

export function RegistryNodeConfigEditor({ node, layout, onUpdateConfig, onValidationChange }: RegistryNodeConfigEditorProps) {
  const validationErrors = useMemo(() => {
    return layout.flatMap((section) => section.controls)
      .map((control) => validateControlValue(control, getControlValue(node, control)))
      .filter((message): message is string => Boolean(message));
  }, [layout, node.config]);

  useEffect(() => {
    onValidationChange?.(validationErrors);
  }, [onValidationChange, validationErrors]);

  return (
    <div className="space-y-4">
      {layout.map((section, index) => (
        <details key={`${node.id}-section-${index}`} className="rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2.5" open={index === 0}>
          <summary className="cursor-pointer list-none text-xs font-semibold uppercase tracking-wide text-neutral-500">
            {section.title ?? section.controls[0]?.label ?? `Section ${index + 1}`}
          </summary>
          <div className="mt-3 space-y-3">
            {section.controls.map((control) => renderControl(control, node, onUpdateConfig))}
          </div>
        </details>
      ))}
    </div>
  );
}