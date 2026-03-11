import type { Run, RunEvent } from "@/lib/types";

export type BuilderNodeExecutionState =
  | "idle"
  | "current"
  | "running"
  | "completed"
  | "failed"
  | "paused"
  | "sla_breached";

export interface BuilderNodeExecutionSummary {
  state: BuilderNodeExecutionState;
  loopCount?: string;
}

export interface BuilderRunOverlay {
  runId: string;
  status: string;
  lastNodeId: string | null;
  startedAt: string | null;
  updatedAt: string;
  nodeStates: Record<string, BuilderNodeExecutionSummary>;
  edgeTraversals: Record<string, number>;
}

function buildEdgeTraversalCounts(events: RunEvent[]): Record<string, number> {
  const counts: Record<string, number> = {};
  const started = events
    .filter((event) => event.event_type === "node_started" && !!event.node_id)
    .sort((left, right) => {
      const leftTs = new Date(left.created_at).getTime();
      const rightTs = new Date(right.created_at).getTime();
      if (leftTs !== rightTs) {
        return leftTs - rightTs;
      }
      return String(left.event_id).localeCompare(String(right.event_id));
    });

  for (let index = 1; index < started.length; index += 1) {
    const from = started[index - 1].node_id;
    const to = started[index].node_id;
    if (!from || !to) {
      continue;
    }
    const key = `${from}=>${to}`;
    counts[key] = (counts[key] ?? 0) + 1;
  }

  return counts;
}

function buildNodeStateMap(
  events: RunEvent[],
  currentNodeId: string | null,
  runStatus: Run["status"],
): Record<string, BuilderNodeExecutionSummary> {
  const map: Record<string, BuilderNodeExecutionSummary> = {};
  const loopIterationsByNode: Record<string, number> = {};

  for (const event of events) {
    if (!event.node_id) {
      continue;
    }

    const nodeId = event.node_id;
    const prior = map[nodeId]?.state;

    if (["node_error", "step_error_notification", "step_timeout"].includes(event.event_type)) {
      map[nodeId] = { ...(map[nodeId] ?? {}), state: "failed" };
      continue;
    }

    if (event.event_type === "sla_breached") {
      if (prior !== "failed") {
        map[nodeId] = { ...(map[nodeId] ?? {}), state: "sla_breached" };
      }
      continue;
    }

    if (["node_completed", "step_completed"].includes(event.event_type)) {
      if (prior !== "failed" && prior !== "sla_breached") {
        map[nodeId] = { ...(map[nodeId] ?? {}), state: "completed" };
      }
      continue;
    }

    if (event.event_type === "node_paused" || event.event_type === "approval_requested") {
      if (prior !== "failed" && prior !== "sla_breached") {
        map[nodeId] = { ...(map[nodeId] ?? {}), state: "paused" };
      }
      continue;
    }

    if (["node_started", "step_started"].includes(event.event_type)) {
      if (prior !== "failed" && prior !== "sla_breached" && prior !== "paused") {
        map[nodeId] = { ...(map[nodeId] ?? {}), state: "running" };
      }
      continue;
    }

    if (event.event_type === "loop_iteration") {
      const payload = (event.payload as Record<string, unknown> | null) ?? {};
      const total = payload.total !== undefined ? Number(payload.total) : undefined;
      const iteration = payload.iteration !== undefined ? Number(payload.iteration) + 1 : undefined;

      if (iteration !== undefined && Number.isFinite(iteration)) {
        loopIterationsByNode[nodeId] = Math.max(loopIterationsByNode[nodeId] ?? 0, iteration);
      } else {
        loopIterationsByNode[nodeId] = (loopIterationsByNode[nodeId] ?? 0) + 1;
      }

      const loopCount = total && Number.isFinite(total)
        ? `${loopIterationsByNode[nodeId]}/${total}`
        : `${loopIterationsByNode[nodeId]}`;

      map[nodeId] = { ...(map[nodeId] ?? { state: "running" }), loopCount };
    }
  }

  if (currentNodeId) {
    if (runStatus === "failed") {
      map[currentNodeId] = { ...(map[currentNodeId] ?? {}), state: "failed" };
    } else if (runStatus === "completed") {
      map[currentNodeId] = { ...(map[currentNodeId] ?? {}), state: "completed" };
    } else if (runStatus === "waiting_approval" && map[currentNodeId]?.state !== "failed") {
      map[currentNodeId] = { ...(map[currentNodeId] ?? {}), state: "paused" };
    } else if (["running", "created", "pending"].includes(runStatus) && map[currentNodeId]?.state !== "failed") {
      map[currentNodeId] = { ...(map[currentNodeId] ?? {}), state: "current" };
    }
  }

  if (["running", "created", "pending"].includes(runStatus)) {
    const lastStarted = [...events]
      .reverse()
      .find((event) => event.node_id && ["node_started", "step_started"].includes(event.event_type));
    if (lastStarted?.node_id && map[lastStarted.node_id]?.state === "running") {
      map[lastStarted.node_id] = { ...map[lastStarted.node_id], state: "current" };
    }
  }

  return map;
}

export function buildBuilderRunOverlay(run: Run | null, events: RunEvent[]): BuilderRunOverlay | null {
  if (!run) {
    return null;
  }

  return {
    runId: run.run_id,
    status: run.status,
    lastNodeId: run.last_node_id,
    startedAt: run.started_at,
    updatedAt: run.updated_at,
    nodeStates: buildNodeStateMap(events, run.last_node_id ?? null, run.status),
    edgeTraversals: buildEdgeTraversalCounts(events),
  };
}