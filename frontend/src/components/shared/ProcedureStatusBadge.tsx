/**
 * Shared ProcedureStatusBadge component — pill-style badge for procedure lifecycle statuses.
 * Used across procedures list, procedure detail, and version detail pages.
 */
const STATUS_COLORS: Record<string, string> = {
  active:      "bg-green-100 text-green-700",
  draft:       "bg-gray-100 text-gray-600",
  deprecated:  "bg-yellow-100 text-yellow-700",
  archived:    "bg-red-100 text-red-600",
};

export function ProcedureStatusBadge({ status }: { status: string }) {
  const cls = STATUS_COLORS[status] ?? "bg-gray-100 text-gray-500";
  return (
    <span
      className={`rounded-full px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide ${cls}`}
    >
      {status}
    </span>
  );
}
