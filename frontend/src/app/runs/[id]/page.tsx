"use client";

import { useEffect, useState, useRef } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { getRun, listRunEvents, listRunArtifacts, cancelRun, retryRun } from "@/lib/api";
import { subscribeToRunEvents } from "@/lib/sse";
import type { Run, RunEvent, Artifact } from "@/lib/types";

export default function RunDetailPage() {
  const params = useParams();
  const runId = params.id as string;

  const [run, setRun] = useState<Run | null>(null);
  const [events, setEvents] = useState<RunEvent[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [artifactNotice, setArtifactNotice] = useState(false);
  const [loading, setLoading] = useState(true);
  const [liveMode, setLiveMode] = useState(true);
  const timelineRef = useRef<HTMLDivElement>(null);

  // Load run + events
  useEffect(() => {
    async function load() {
      try {
        const [r, evts, arts] = await Promise.all([
          getRun(runId),
          listRunEvents(runId),
          listRunArtifacts(runId),
        ]);
        setRun(r);
        setEvents(evts);
        setArtifacts(arts);
      } catch (err) {
        console.error(err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, [runId]);

  // SSE subscription for live events
  useEffect(() => {
    if (!liveMode) return;
    const cleanup = subscribeToRunEvents(runId, (event) => {
      setEvents((prev) => {
        if (prev.some((e) => e.event_id === event.event_id)) return prev;
        return [...prev, event];
      });

      if (event.event_type === "artifact_created") {
        setArtifactNotice(true);
        window.setTimeout(() => setArtifactNotice(false), 2500);
        void listRunArtifacts(runId)
          .then((arts) => setArtifacts(arts))
          .catch((err) => console.error("Failed to refresh artifacts", err));
      }
    });
    return cleanup;
  }, [runId, liveMode]);

  // Auto-scroll timeline
  useEffect(() => {
    if (timelineRef.current) {
      timelineRef.current.scrollTop = timelineRef.current.scrollHeight;
    }
  }, [events]);

  async function handleCancel() {
    if (!run) return;
    await cancelRun(run.run_id);
    setRun({ ...run, status: "cancelled" });
  }

  async function handleRetry() {
    if (!run) return;
    const newRun = await retryRun(run.run_id);
    // Navigate to new run
    window.location.href = `/runs/${newRun.run_id}`;
  }

  if (loading) return <p className="text-gray-500">Loading run...</p>;
  if (!run) return <p className="text-red-500">Run not found</p>;

  return (
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <Link href="/runs" className="text-sm text-primary-600 hover:underline">
            ← Runs
          </Link>
          <h2 className="mt-2 text-xl font-bold text-gray-900">
            Run {run.run_id.slice(0, 12)}…
          </h2>
          <p className="mt-1 text-sm text-gray-500">
            Procedure: {run.procedure_id} v{run.procedure_version}
          </p>
        </div>
        <div className="flex gap-2">
          {(run.status === "running" || run.status === "created") && (
            <button
              onClick={handleCancel}
              className="rounded-lg border border-red-300 px-4 py-2 text-sm font-medium text-red-600 hover:bg-red-50"
            >
              Cancel
            </button>
          )}
          {run.status === "failed" && (
            <button
              onClick={handleRetry}
              className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
            >
              Retry
            </button>
          )}
        </div>
      </div>

      {/* Status card */}
      <div className="grid grid-cols-2 gap-4 sm:grid-cols-4">
        <InfoCard label="Status" value={run.status} />
        <InfoCard label="Thread ID" value={run.thread_id.slice(0, 12) + "…"} />
        <InfoCard label="Created" value={new Date(run.created_at).toLocaleString()} />
        <InfoCard label="Updated" value={new Date(run.updated_at).toLocaleString()} />
      </div>

      {/* Input variables */}
      {run.input_vars && Object.keys(run.input_vars).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-3 text-sm font-semibold text-gray-900">Input Variables</h3>
          <pre className="rounded-lg bg-gray-50 p-3 font-mono text-xs">
            {JSON.stringify(run.input_vars, null, 2)}
          </pre>
        </div>
      )}

      {/* Event timeline */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">Artifacts ({artifacts.length})</h3>
          {artifactNotice && (
            <span className="rounded-md bg-green-50 px-2 py-1 text-xs font-medium text-green-700">
              New artifact received
            </span>
          )}
        </div>
        {artifacts.length === 0 ? (
          <p className="text-sm text-gray-400">No artifacts captured</p>
        ) : (
          <div className="space-y-2">
            {artifacts.map((artifact) => (
              <div key={artifact.artifact_id} className="flex items-center justify-between rounded-lg border border-gray-100 p-3">
                <div className="min-w-0">
                  <p className="text-xs font-medium text-gray-900">{artifact.kind}</p>
                  <p className="truncate text-xs text-gray-500">
                    {artifact.node_id ? `node: ${artifact.node_id}` : "-"}
                    {artifact.step_id ? ` | step: ${artifact.step_id}` : ""}
                  </p>
                </div>
                <a
                  href={artifact.uri}
                  target="_blank"
                  rel="noreferrer"
                  className="text-xs text-primary-600 hover:underline"
                >
                  Open
                </a>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Event timeline */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <div className="mb-4 flex items-center justify-between">
          <h3 className="text-sm font-semibold text-gray-900">
            Event Timeline ({events.length})
          </h3>
          <label className="flex items-center gap-2 text-sm text-gray-500">
            <input
              type="checkbox"
              checked={liveMode}
              onChange={(e) => setLiveMode(e.target.checked)}
              className="rounded"
            />
            Live updates
          </label>
        </div>
        <div
          ref={timelineRef}
          className="max-h-[500px] space-y-2 overflow-y-auto"
        >
          {events.length === 0 ? (
            <p className="text-sm text-gray-400">No events yet</p>
          ) : (
            events.map((event) => (
              <div
                key={event.event_id}
                className="flex gap-3 rounded-lg border border-gray-100 p-3"
              >
                <div className="flex-shrink-0">
                  <EventDot type={event.event_type} />
                </div>
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-medium text-gray-900">{event.event_type}</span>
                    {event.node_id && (
                      <span className="text-xs text-gray-400">node: {event.node_id}</span>
                    )}
                    {event.step_id && (
                      <span className="text-xs text-gray-400">step: {event.step_id}</span>
                    )}
                  </div>
                  {event.payload && Object.keys(event.payload).length > 0 && (
                    <pre className="mt-1 max-h-24 overflow-auto text-xs text-gray-500">
                      {JSON.stringify(event.payload, null, 2)}
                    </pre>
                  )}
                  <span className="mt-1 block text-[10px] text-gray-300">
                    {new Date(event.created_at).toLocaleTimeString()}
                  </span>
                </div>
              </div>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

function InfoCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <p className="text-xs text-gray-500">{label}</p>
      <p className="mt-1 text-sm font-medium text-gray-900">{value}</p>
    </div>
  );
}

function EventDot({ type }: { type: string }) {
  const colors: Record<string, string> = {
    run_created: "bg-blue-400",
    node_started: "bg-yellow-400",
    node_completed: "bg-green-400",
    step_started: "bg-gray-400",
    step_completed: "bg-green-300",
    error: "bg-red-400",
    approval_requested: "bg-orange-400",
    approval_decided: "bg-purple-400",
    run_completed: "bg-green-600",
    run_failed: "bg-red-600",
  };
  return (
    <div className={`mt-1 h-2.5 w-2.5 rounded-full ${colors[type] ?? "bg-gray-300"}`} />
  );
}
