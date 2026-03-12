import { useState } from "react";
import type { ReactNode } from "react";

export type EditableObject = Record<string, unknown>;
export type EditorTemplate = { label: string; value: EditableObject };
export type EditorFieldDefinition = {
  key: string;
  label: string;
  description?: string;
  required?: boolean;
  keyEditable?: boolean;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
  valueInput?: "text" | "textarea" | "select";
  valueOptions?: string[];
  valueRows?: number;
  visibleWhen?: (value: EditableObject) => boolean;
  valuePresets?: Record<string, EditableObject>;
};

function isFieldVisible(field: EditorFieldDefinition | undefined, value: EditableObject): boolean {
  return field?.visibleWhen ? field.visibleWhen(value) : true;
}

function isEmptyFieldValue(value: unknown): boolean {
  if (value === undefined || value === null) {
    return true;
  }
  if (typeof value === "string") {
    return value.trim().length === 0;
  }
  return false;
}

function getMissingRequiredFields(fields: EditorFieldDefinition[], value: EditableObject): EditorFieldDefinition[] {
  return fields.filter((field) => field.required && isFieldVisible(field, value) && isEmptyFieldValue(value[field.key]));
}

function moveItem<T>(items: T[], fromIndex: number, toIndex: number): T[] {
  if (fromIndex === toIndex || toIndex < 0 || toIndex >= items.length) {
    return items;
  }

  const nextItems = [...items];
  const [movedItem] = nextItems.splice(fromIndex, 1);
  nextItems.splice(toIndex, 0, movedItem);
  return nextItems;
}

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

function applyFieldValueChange(objectValue: EditableObject, previousKey: string, nextKey: string, nextValue: string, field?: EditorFieldDefinition): EditableObject {
  const nextObject = updateObjectEntry(objectValue, previousKey, nextKey, nextValue);
  if (!field?.valuePresets) {
    return nextObject;
  }

  const preset = field.valuePresets[nextValue];
  if (!preset) {
    return nextObject;
  }

  const mergedObject: EditableObject = { ...nextObject };
  for (const [presetKey, presetValue] of Object.entries(preset)) {
    const currentValue = mergedObject[presetKey];
    const isEmpty = currentValue === undefined || currentValue === null || currentValue === "";
    if (isEmpty) {
      mergedObject[presetKey] = presetValue;
    }
  }
  return mergedObject;
}

function renderValueInput({
  entryKey,
  entryValue,
  field,
  value,
  onChange,
}: {
  entryKey: string;
  entryValue: unknown;
  field?: EditorFieldDefinition;
  value: EditableObject;
  onChange: (nextValue: EditableObject) => void;
}) {
  const formattedValue = formatLooseValue(entryValue);

  if (field?.valueInput === "select" && field.valueOptions && field.valueOptions.length > 0) {
    return (
      <select
        aria-label={field.label}
        title={field.label}
        value={formattedValue}
        onChange={(event) => onChange(applyFieldValueChange(value, entryKey, entryKey, event.target.value, field))}
        className="w-full rounded-xl border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400"
      >
        <option value="">Select...</option>
        {field.valueOptions.map((option) => (
          <option key={`${entryKey}-${option}`} value={option}>{option}</option>
        ))}
      </select>
    );
  }

  if (field?.valueInput === "textarea") {
    return (
      <textarea
        rows={field.valueRows ?? 3}
        value={formattedValue}
        onChange={(event) => onChange(updateObjectEntry(value, entryKey, entryKey, event.target.value))}
        placeholder={field.valuePlaceholder ?? "value"}
        className="w-full rounded-xl border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400"
      />
    );
  }

  return (
    <input
      value={formattedValue}
      onChange={(event) => onChange(updateObjectEntry(value, entryKey, entryKey, event.target.value))}
      placeholder={field?.valuePlaceholder ?? "value"}
      className="w-full rounded-xl border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400"
    />
  );
}

export function StructuredObjectEditor({
  label,
  value,
  onChange,
  addButtonLabel = "Add Field",
  templates = [],
  fields = [],
  emptyState = "No fields configured yet.",
  showHeader = true,
  allowAddField = true,
  showAllDefinedFields = false,
}: {
  label: string;
  value: EditableObject;
  onChange: (nextValue: EditableObject) => void;
  addButtonLabel?: string;
  templates?: EditorTemplate[];
  fields?: EditorFieldDefinition[];
  emptyState?: ReactNode;
  showHeader?: boolean;
  allowAddField?: boolean;
  showAllDefinedFields?: boolean;
}) {
  const visibleFields = fields.filter((field) => isFieldVisible(field, value));
  const missingRequiredFields = getMissingRequiredFields(fields, value);
  const entryKeys = showAllDefinedFields && fields.length > 0
    ? [...visibleFields.map((field) => field.key), ...Object.keys(value).filter((key) => !fields.some((field) => field.key === key))]
    : Object.keys(value);
  const entries = entryKeys.map((key) => [key, key in value ? value[key] : ""] as const);
  const fieldLookup = new Map(fields.map((field) => [field.key, field]));

  function addField() {
    const nextDefinedField = visibleFields.find((field) => !(field.key in value));
    if (nextDefinedField) {
      onChange({ ...value, [nextDefinedField.key]: "" });
      return;
    }
    onChange({ ...value, [`field_${entries.length + 1}`]: "" });
  }

  return (
    <div>
      {showHeader ? (
        <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
          <label className="block text-xs font-medium text-neutral-500">{label}</label>
          {allowAddField ? (
            <button
              type="button"
              onClick={addField}
              className="rounded-lg border border-neutral-200 px-2.5 py-1.5 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
            >
              {addButtonLabel}
            </button>
          ) : null}
        </div>
      ) : null}
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
      <div className="space-y-2.5">
        {entries.length === 0 ? (
          <div className="rounded-xl border border-dashed border-neutral-200 px-3 py-3 text-xs text-neutral-500">
            {emptyState}
          </div>
        ) : null}
        {entries.map(([entryKey, entryValue]) => (
          <div key={entryKey} className="rounded-2xl border border-neutral-200 bg-white p-3">
            {(() => {
              const field = fieldLookup.get(entryKey);
              const isMissingRequired = Boolean(field?.required && isEmptyFieldValue(entryValue));
              return (
                <>
                  <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
                    <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-400">
                      {field?.label ?? "Field"}
                    </p>
                    {allowAddField ? (
                      <button
                        type="button"
                        onClick={() => {
                          const nextObject = { ...value };
                          delete nextObject[entryKey];
                          onChange(nextObject);
                        }}
                        className="rounded-lg border border-neutral-200 px-2.5 py-1.5 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
                      >
                        Remove
                      </button>
                    ) : null}
                  </div>
                  <div className="space-y-3">
                    <div className="space-y-1">
                      <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-400">Key</p>
                      {field?.keyEditable === false ? (
                        <div className="rounded-xl border border-neutral-200 bg-neutral-50 px-3 py-2.5 text-sm text-neutral-700 break-all">
                          {entryKey}
                        </div>
                      ) : (
                        <input
                          value={entryKey}
                          onChange={(event) => onChange(updateObjectEntry(value, entryKey, event.target.value, formatLooseValue(entryValue)))}
                          placeholder={field?.keyPlaceholder ?? "field"}
                          className="w-full rounded-xl border border-neutral-200 px-3 py-2.5 text-sm outline-none focus:border-indigo-400"
                        />
                      )}
                    </div>
                    <div className="space-y-1">
                      <p className="text-[10px] font-medium uppercase tracking-wide text-neutral-400">Value</p>
                      <div className={isMissingRequired ? "rounded-2xl border border-amber-200 bg-amber-50/40 p-1" : undefined}>
                        {renderValueInput({
                          entryKey,
                          entryValue,
                          field,
                          value,
                          onChange,
                        })}
                      </div>
                      {isMissingRequired ? (
                        <p className="text-xs leading-5 text-amber-700">This field is required.</p>
                      ) : null}
                      {field?.description ? (
                        <p className="text-xs leading-5 text-neutral-500">{field.description}</p>
                      ) : null}
                    </div>
                  </div>
                </>
              );
            })()}
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
      <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
        <label className="block text-xs font-medium text-neutral-500">{label}</label>
        <button
          type="button"
          onClick={() => onChange([...normalizedItems, { ...newItem }])}
          className="rounded-lg border border-neutral-200 px-2.5 py-1.5 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
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
            totalItems={normalizedItems.length}
            item={item}
            fields={fields}
            onRemove={() => onChange(normalizedItems.filter((_, itemIndex) => itemIndex !== index))}
            onMoveUp={() => onChange(moveItem(normalizedItems, index, index - 1))}
            onMoveDown={() => onChange(moveItem(normalizedItems, index, index + 1))}
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
  totalItems,
  item,
  fields,
  onRemove,
  onMoveUp,
  onMoveDown,
  onChange,
}: {
  label: string;
  index: number;
  totalItems: number;
  item: EditableObject;
  fields: EditorFieldDefinition[];
  onRemove: () => void;
  onMoveUp: () => void;
  onMoveDown: () => void;
  onChange: (nextItem: EditableObject) => void;
}) {
  const [isOpen, setIsOpen] = useState(index === 0);
  const missingRequiredFields = getMissingRequiredFields(fields, item);
  const titleField = fields.find((field) => {
    if (!isFieldVisible(field, item)) {
      return false;
    }
    const value = item[field.key];
    return typeof value === "string" ? value.trim().length > 0 : value !== undefined && value !== null && value !== "";
  });
  const titleValue = titleField ? formatLooseValue(item[titleField.key]) : "";
  const summaryFields = fields
    .filter((field) => isFieldVisible(field, item))
    .map((field) => ({ field, value: item[field.key] }))
    .filter(({ value }) => typeof value === "string" ? value.trim().length > 0 : value !== undefined && value !== null && value !== "")
    .slice(0, 3);

  return (
    <div className="rounded-2xl border border-neutral-200 bg-neutral-50/60">
      <div className="flex flex-col gap-3 px-3 py-3">
        <div className="flex items-start justify-between gap-3">
          <button
            type="button"
            onClick={() => setIsOpen((current) => !current)}
            className="min-w-0 flex-1 text-left"
          >
            <div className="flex flex-wrap items-center gap-2">
              <span className="rounded-full bg-white px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-neutral-500">
                {label} {index + 1}
              </span>
              {missingRequiredFields.length > 0 ? (
                <span className="rounded-full bg-amber-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-amber-700">
                  {missingRequiredFields.length} missing
                </span>
              ) : (
                <span className="rounded-full bg-emerald-100 px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-emerald-700">
                  Ready
                </span>
              )}
              {titleValue ? <p className="truncate text-sm font-medium text-neutral-800">{titleValue}</p> : null}
            </div>
            {summaryFields.length > 0 ? (
              <div className="mt-2 flex flex-wrap gap-1.5">
                {summaryFields.map(({ field, value }) => (
                  <span
                    key={`${label}-${index}-${field.key}`}
                    className="rounded-full border border-neutral-200 bg-white px-2 py-1 text-[10px] text-neutral-600"
                  >
                    {field.label}: {formatLooseValue(value)}
                  </span>
                ))}
              </div>
            ) : null}
          </button>
          <div className="flex flex-wrap items-center gap-2">
            <button
              type="button"
              onClick={onMoveUp}
              disabled={index === 0}
              className="rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:bg-neutral-100 disabled:text-neutral-400"
            >
              Up
            </button>
            <button
              type="button"
              onClick={onMoveDown}
              disabled={index === totalItems - 1}
              className="rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:bg-neutral-100 disabled:text-neutral-400"
            >
              Down
            </button>
          </div>
        </div>
        {missingRequiredFields.length > 0 ? (
          <div className="rounded-xl border border-amber-200 bg-amber-50 px-3 py-2 text-xs text-amber-800">
            Missing: {missingRequiredFields.map((field) => field.label).join(", ")}
          </div>
        ) : null}
        <div className="flex flex-wrap items-center gap-2">
          <button
            type="button"
            onClick={() => setIsOpen((current) => !current)}
            className="rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
          >
            {isOpen ? "Collapse" : "Expand"}
          </button>
          <button
            type="button"
            onClick={onRemove}
            className="rounded-lg border border-neutral-200 bg-white px-2.5 py-1.5 text-[11px] font-medium text-neutral-600 hover:bg-neutral-50"
          >
            Remove
          </button>
        </div>
      </div>
      {isOpen ? (
        <div className="border-t border-neutral-200 bg-white p-3">
          <StructuredObjectEditor
            label="Fields"
            value={item}
            fields={fields}
            showHeader={false}
            allowAddField={false}
            showAllDefinedFields={fields.length > 0}
            onChange={onChange}
          />
        </div>
      ) : null}
    </div>
  );
}