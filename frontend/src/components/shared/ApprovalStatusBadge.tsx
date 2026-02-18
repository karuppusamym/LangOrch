/**
 * Shared ApprovalStatusBadge component — single source of truth.
 * Used across approvals list and approval detail pages.
 */
export function ApprovalStatusBadge({ status }: { status: string }) {
  const cls: Record<string, string> = {
    pending:   "badge-warning",
    approved:  "badge-success",
    rejected:  "badge-error",
    timed_out: "badge-neutral",
    expired:   "badge-neutral",
  };
  return (
    <span className={`badge ${cls[status] ?? "badge-neutral"}`}>{status}</span>
  );
}
