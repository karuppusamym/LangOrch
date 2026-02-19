/* SSE helper — subscribes to a run's event stream */

import type { RunEvent } from "./types";

export function subscribeToRunEvents(
  runId: string,
  onEvent: (event: RunEvent) => void,
  onError?: (error: Event) => void
): () => void {
  const url = `/api/runs/${runId}/stream`;
  const source = new EventSource(url);

  source.addEventListener("run_event", (e: MessageEvent) => {
    try {
      const event: RunEvent = JSON.parse(e.data);
      onEvent(event);
    } catch {
      console.error("Failed to parse SSE event", e.data);
    }
  });

  source.onerror = (e) => {
    if (onError) onError(e);
    else console.error("SSE error", e);
  };

  // Return cleanup function
  return () => source.close();
}

/* SSE helper — subscribes to approval updates */

export interface ApprovalSSEEvent {
  approval_id: string;
  run_id: string;
  node_id: string;
  prompt: string;
  status: string;
  decided_by: string | null;
  decided_at: string | null;
  expires_at: string | null;
  created_at: string | null;
}

export function subscribeToApprovalUpdates(
  onUpdate: (event: ApprovalSSEEvent) => void,
  onError?: (error: Event) => void
): () => void {
  const url = `/api/approvals/stream`;
  const source = new EventSource(url);

  source.addEventListener("approval_update", (e: MessageEvent) => {
    try {
      const data: ApprovalSSEEvent = JSON.parse(e.data);
      onUpdate(data);
    } catch {
      console.error("Failed to parse approval SSE event", e.data);
    }
  });

  source.onerror = (e) => {
    if (onError) onError(e);
    else console.error("Approval SSE error", e);
  };

  return () => source.close();
}
