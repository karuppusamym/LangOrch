/**
 * Shared StatusBadge component — single source of truth.
 * Used across runs, procedures, and dashboard pages.
 */

const DOT: Record<string, string> = {
  completed:        "bg-green-500",
  running:          "bg-blue-500 animate-pulse",
  created:          "bg-slate-400",
  waiting_approval: "bg-yellow-500",
  failed:           "bg-red-500",
  canceled:         "bg-slate-400",
  cancelled:        "bg-slate-400",
  paused:           "bg-amber-500",
};

const CLS: Record<string, string> = {
  completed:        "badge-success",
  running:          "badge-info",
  created:          "badge-neutral",
  waiting_approval: "badge-warning",
  failed:           "badge-error",
  canceled:         "badge-neutral",
  cancelled:        "badge-neutral",
  paused:           "badge-warning",
};

export function StatusBadge({ status }: { status: string }) {
  return (
    <span className={`badge ${CLS[status] ?? "badge-neutral"} inline-flex items-center gap-1.5`}>
      <span className={`inline-block h-1.5 w-1.5 rounded-full ${DOT[status] ?? "bg-slate-400"}`} />
      {status.replace(/_/g, " ")}
    </span>
  );
}
