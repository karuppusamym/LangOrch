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
