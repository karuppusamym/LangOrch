import { useState } from "react";
import type { ReactNode } from "react";

export type EditableObject = Record<string, unknown>;
export type EditorTemplate = { label: string; value: EditableObject };
export type EditorFieldDefinition = {
  key: string;
  label: string;
  keyEditable?: boolean;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
};

export function parseLooseValue(value: string): unknown {
  const trimmed = value.trim();
  if (!trimmed) {
    return "";
  }
  if (trimmed === "true") return true;
  if (trimmed === "false") return false;
  if (trimmed === "null") return null;
  if (!Number.isNaN(Number(trimmed)) && /^-?\d+(?:\.\d+)?$/.test(trimmed)) {
    return Number(trimmed);
  }
  if (["{", "[", '"'].includes(trimmed[0])) {
    try {
      return JSON.parse(trimmed);
    } catch {
      return value;
    }
  }
  return value;
}

export function formatLooseValue(value: unknown): string {
  if (typeof value === "string") {
    return value;
  }
  if (value === undefined) {
    return "";
  }
  return JSON.stringify(value);
}

export function normalizeEditableObject(value: unknown): EditableObject {
  if (value && typeof value === "object" && !Array.isArray(value)) {
    return value as EditableObject;
  }
  return value === undefined ? {} : { value };
}

function updateObjectEntry(objectValue: EditableObject, previousKey: string, nextKey: string, nextValue: string): EditableObject {
  const nextObject: EditableObject = {};
  for (const [key, value] of Object.entries(objectValue)) {
    if (key === previousKey) {
      continue;
    }
    nextObject[key] = value;
  }
  const targetKey = nextKey.trim() || previousKey;
  nextObject[targetKey] = parseLooseValue(nextValue);
  return nextObject;
}

export function StructuredObjectEditor({
  label,
  value,
  onChange,
  addButtonLabel = "Add Field",
  templates = [],
  fields = [],
  emptyState = "No fields configured yet.",
}: {
  label: string;
  value: EditableObject;
  onChange: (nextValue: EditableObject) => void;
  addButtonLabel?: string;
  templates?: EditorTemplate[];
  fields?: EditorFieldDefinition[];
  emptyState?: ReactNode;
}) {
  const entries = Object.entries(value);
  const fieldLookup = new Map(fields.map((field) => [field.key, field]));

  function addField() {
    const nextDefinedField = fields.find((field) => !(field.key in value));
    if (nextDefinedField) {
      onChange({ ...value, [nextDefinedField.key]: "" });
      return;
    }
    onChange({ ...value, [`field_${entries.length + 1}`]: "" });
  }

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <label className="block text-xs font-medium text-neutral-500">{label}</label>
        <button
          type="button"
          onClick={addField}
          className="rounded-lg border border-neutral-200 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
        >
          {addButtonLabel}
        </button>
      </div>
      {templates.length > 0 ? (
        <div className="mb-2 flex flex-wrap gap-2">
          {templates.map((template) => (
            <button
              key={`${label}-${template.label}`}
              type="button"
              onClick={() => onChange({ ...value, ...template.value })}
              className="rounded-full border border-neutral-200 bg-neutral-50 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-100"
            >
              {template.label}
            </button>
          ))}
        </div>
      ) : null}
      <div className="space-y-2">
        {entries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-neutral-200 px-3 py-3 text-xs text-neutral-500">
            {emptyState}
          </div>
        ) : null}
        {entries.map(([entryKey, entryValue]) => (
          <div key={entryKey} className="rounded-xl border border-neutral-200 p-2.5">
            <div className="mb-2 flex items-center justify-between gap-2">
              <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-400">
                {fieldLookup.get(entryKey)?.label ?? "Field"}
              </p>
              <button
                type="button"
                onClick={() => {
                  const nextObject = { ...value };
                  delete nextObject[entryKey];
                  onChange(nextObject);
                }}
                className="rounded-lg border border-neutral-200 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
              >
                Remove
              </button>
            </div>
            <div className="grid gap-2 sm:grid-cols-2">
              <div className="space-y-1">
                <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-400">Key</p>
                {fieldLookup.get(entryKey)?.keyEditable === false ? (
                  <div className="rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2 text-sm text-neutral-700">
                    {entryKey}
                  </div>
                ) : (
                  <input
                    value={entryKey}
                    onChange={(event) => onChange(updateObjectEntry(value, entryKey, event.target.value, formatLooseValue(entryValue)))}
                    placeholder={fieldLookup.get(entryKey)?.keyPlaceholder ?? "field"}
                    className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
                  />
                )}
              </div>
              <div className="space-y-1">
                <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-400">Value</p>
                <input
                  value={formatLooseValue(entryValue)}
                  onChange={(event) => onChange(updateObjectEntry(value, entryKey, entryKey, event.target.value))}
                  placeholder={fieldLookup.get(entryKey)?.valuePlaceholder ?? "value"}
                  className="w-full rounded-xl border border-neutral-200 px-3 py-2 text-sm outline-none focus:border-indigo-400"
                />
              </div>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

export function StructuredObjectListEditor({
  label,
  items,
  onChange,
  newItem,
  addItemLabel = "Add Item",
  templates = [],
  fields = [],
  emptyState = "No items configured yet.",
}: {
  label: string;
  items: unknown[];
  onChange: (nextItems: unknown[]) => void;
  newItem: EditableObject;
  addItemLabel?: string;
  templates?: EditorTemplate[];
  fields?: EditorFieldDefinition[];
  emptyState?: ReactNode;
}) {
  const normalizedItems = items.map((item) => normalizeEditableObject(item));

  return (
    <div>
      <div className="mb-2 flex items-center justify-between gap-2">
        <label className="block text-xs font-medium text-neutral-500">{label}</label>
        <button
          type="button"
          onClick={() => onChange([...normalizedItems, { ...newItem }])}
          className="rounded-lg border border-neutral-200 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
        >
          {addItemLabel}
        </button>
      </div>
      {templates.length > 0 ? (
        <div className="mb-2 flex flex-wrap gap-2">
          {templates.map((template) => (
            <button
              key={`${label}-${template.label}`}
              type="button"
              onClick={() => onChange([...normalizedItems, { ...template.value }])}
              className="rounded-full border border-neutral-200 bg-neutral-50 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-100"
            >
              {template.label}
            </button>
          ))}
        </div>
      ) : null}
      <div className="space-y-3">
        {normalizedItems.length === 0 ? (
          <div className="rounded-xl border border-dashed border-neutral-200 px-3 py-3 text-xs text-neutral-500">
            {emptyState}
          </div>
        ) : null}
        {normalizedItems.map((item, index) => (
          <StructuredObjectListItem
            key={`${label}-${index}`}
            label={label}
            index={index}
            item={item}
            fields={fields}
            onRemove={() => onChange(normalizedItems.filter((_, itemIndex) => itemIndex !== index))}
            onChange={(nextItem) => onChange(normalizedItems.map((currentItem, itemIndex) => itemIndex === index ? nextItem : currentItem))}
          />
        ))}
      </div>
    </div>
  );
}

function StructuredObjectListItem({
  label,
  index,
  item,
  fields,
  onRemove,
  onChange,
}: {
  label: string;
  index: number;
  item: EditableObject;
  fields: EditorFieldDefinition[];
  onRemove: () => void;
  onChange: (nextItem: EditableObject) => void;
}) {
  const [isOpen, setIsOpen] = useState(index === 0);
  const titleField = fields.find((field) => item[field.key]);
  const titleValue = titleField ? formatLooseValue(item[titleField.key]) : "";

  return (
    <div className="rounded-xl border border-neutral-200">
      <div className="flex items-center justify-between gap-2 px-3 py-2.5">
        <button
          type="button"
          onClick={() => setIsOpen((current) => !current)}
          className="min-w-0 text-left"
        >
          <p className="text-xs font-medium uppercase tracking-wide text-neutral-500">Item {index + 1}</p>
          {titleValue ? <p className="truncate text-xs text-neutral-600">{titleValue}</p> : null}
        </button>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => setIsOpen((current) => !current)}
            className="rounded-lg border border-neutral-200 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
          >
            {isOpen ? "Collapse" : "Expand"}
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded-lg border border-neutral-200 px-2 py-1 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
          >
            Remove
          </button>
        </div>
      </div>
      {isOpen ? (
        <div className="border-t border-neutral-100 p-3">
          <StructuredObjectEditor
            label="Fields"
            value={item}
            addButtonLabel="Add Field"
            fields={fields}
            onChange={onChange}
          />
        </div>
      ) : null}
    </div>
  );
}