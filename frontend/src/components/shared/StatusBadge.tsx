/**
 * Shared StatusBadge component — single source of truth.
 * Used across runs, procedures, and dashboard pages.
 */
export function StatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    completed:        "badge-success",
    running:          "badge-info",
    created:          "badge-neutral",
    waiting_approval: "badge-warning",
    failed:           "badge-error",
    canceled:         "badge-neutral",
    cancelled:        "badge-neutral",
    paused:           "badge-warning",
  };
  return (
    <span className={`badge ${cls[status] ?? "badge-neutral"}`}>{status}</span>
  );
}
