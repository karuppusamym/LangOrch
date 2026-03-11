"use client";

import { useEffect, useState, useCallback } from "react";
import { listTriggers, fireTrigger, deleteTrigger, syncTriggers } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { TriggerRegistration } from "@/lib/types";

const TYPE_COLORS: Record<string, string> = {
  scheduled: "bg-blue-100 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400",
  webhook: "bg-purple-100 dark:bg-purple-950/40 text-purple-700 dark:text-purple-400",
  event: "bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400",
  file_watch: "bg-teal-100 dark:bg-teal-950/40 text-teal-700 dark:text-teal-400",
  manual: "bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400",
};

function TriggerTypeBadge({ type }: { type: string }) {
  return (
    <span className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${TYPE_COLORS[type] ?? TYPE_COLORS.manual}`}>
      {type.replace("_", " ")}
    </span>
  );
}

function EnabledDot({ enabled }: { enabled: boolean }) {
  return (
    <span className={`inline-block w-2 h-2 rounded-full ${enabled ? "bg-emerald-500" : "bg-neutral-300 dark:bg-neutral-600"}`} title={enabled ? "Enabled" : "Disabled"} />
  );
}

export default function TriggersPage() {
  const [triggers, setTriggers] = useState<TriggerRegistration[]>([]);
  const [loading, setLoading] = useState(true);
  const [firing, setFiring] = useState<string | null>(null);
  const [deleting, setDeleting] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);
  const [filterType, setFilterType] = useState<string>("all");
  const [filterEnabled, setFilterEnabled] = useState<"all" | "enabled" | "disabled">("all");
  const [search, setSearch] = useState("");
  const [confirmDelete, setConfirmDelete] = useState<TriggerRegistration | null>(null);
  const [confirmFire, setConfirmFire] = useState<TriggerRegistration | null>(null);
  const [trigPage, setTrigPage] = useState(0);
  const { toast } = useToast();

  const load = useCallback(async () => {
    try {
      const data = await listTriggers();
      setTriggers(data);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load triggers", "error");
    } finally {
      setLoading(false);
    }
  }, [toast]);

  useEffect(() => { void load(); }, [load]);
  useEffect(() => { setTrigPage(0); }, [filterType, filterEnabled, search]);

  function handleFire(trigger: TriggerRegistration) {
    setConfirmFire(trigger);
  }

  async function performFire() {
    if (!confirmFire) return;
    const trigger = confirmFire;
    setConfirmFire(null);
    const key = `${trigger.procedure_id}:${trigger.version}`;
    setFiring(key);
    try {
      const result = await fireTrigger(trigger.procedure_id, trigger.version);
      toast(`Fired! Run ID: ${result.run_id.slice(0, 8)}…`, "success");
      void load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to fire trigger", "error");
    } finally {
      setFiring(null);
    }
  }

  function handleDelete(trigger: TriggerRegistration) {
    setConfirmDelete(trigger);
  }

  async function performDelete() {
    if (!confirmDelete) return;
    const trigger = confirmDelete;
    setConfirmDelete(null);
    const key = `${trigger.procedure_id}:${trigger.version}`;
    setDeleting(key);
    try {
      await deleteTrigger(trigger.procedure_id, trigger.version);
      toast("Trigger deleted", "success");
      void load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to delete trigger", "error");
    } finally {
      setDeleting(null);
    }
  }

  async function handleSync() {
    setSyncing(true);
    try {
      const result = await syncTriggers();
      toast(`Synced ${result.synced} trigger(s) from procedures`, "success");
      void load();
    } catch (err) {
      toast(err instanceof Error ? err.message : "Sync failed", "error");
    } finally {
      setSyncing(false);
    }
  }

  function copyWebhook(trigger: TriggerRegistration) {
    const fallbackBase = typeof window !== "undefined" ? window.location.origin : "http://localhost:8000";
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? fallbackBase;
    const url = `${apiBase}/api/triggers/webhook/${encodeURIComponent(trigger.procedure_id)}`;
    void navigator.clipboard.writeText(url);
    toast("Webhook URL copied", "success");
  }

  const allTypes = Array.from(new Set(triggers.map((t) => t.trigger_type)));
  const filtered = triggers.filter((t) => {
    if (filterType !== "all" && t.trigger_type !== filterType) return false;
    if (filterEnabled === "enabled" && !t.enabled) return false;
    if (filterEnabled === "disabled" && t.enabled) return false;
    if (search && !t.procedure_id.toLowerCase().includes(search.toLowerCase()) && !t.version.toLowerCase().includes(search.toLowerCase())) return false;
    return true;
  });
  const TRIG_PAGE_SIZE = 15;
  const totalTrigPages = Math.ceil(filtered.length / TRIG_PAGE_SIZE);
  const pagedTriggers = filtered.slice(trigPage * TRIG_PAGE_SIZE, (trigPage + 1) * TRIG_PAGE_SIZE);

  const stats = {
    total: triggers.length,
    enabled: triggers.filter((t) => t.enabled).length,
    scheduled: triggers.filter((t) => t.trigger_type === "scheduled").length,
    webhook: triggers.filter((t) => t.trigger_type === "webhook").length,
  };
  const disabledCount = Math.max(0, stats.total - stats.enabled);

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-4 bg-neutral-50 p-6">
      <section className="rounded-2xl border border-neutral-200 bg-white px-6 py-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div className="min-w-0 flex-1">
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-neutral-400">Runtime Workspace</p>
            <h1 className="mt-1 text-3xl font-bold text-neutral-900 dark:text-neutral-100">Triggers</h1>
            <p className="mt-1 max-w-3xl text-sm text-neutral-500 dark:text-neutral-400">Schedule, webhook, and event-based trigger registrations with manual fire and sync controls.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
            <span className="rounded-full border px-2 py-1">Enabled {stats.enabled}</span>
            <span className="rounded-full border px-2 py-1">Disabled {disabledCount}</span>
            <button
              onClick={handleSync}
              disabled={syncing}
              className="flex items-center gap-2 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-60 transition-colors"
            >
              <svg className={`h-4 w-4 ${syncing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
              </svg>
              {syncing ? "Syncing…" : "Sync from Procedures"}
            </button>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-3 sm:grid-cols-4">
          {[
            { label: "Total", value: stats.total, color: "text-neutral-900 dark:text-neutral-100" },
            { label: "Enabled", value: stats.enabled, color: "text-emerald-600 dark:text-emerald-400" },
            { label: "Scheduled", value: stats.scheduled, color: "text-blue-600 dark:text-blue-400" },
            { label: "Webhook", value: stats.webhook, color: "text-purple-600 dark:text-purple-400" },
          ].map((item) => (
            <div key={item.label} className="rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-4 py-3 shadow-sm">
              <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">{item.label}</p>
              <p className={`mt-2 text-2xl font-semibold ${item.color}`}>{item.value}</p>
            </div>
          ))}
        </div>
      </section>

      <div className="rounded-2xl border border-neutral-200 bg-white p-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap items-center gap-2">
            <input
              type="text"
              placeholder="Search procedure or version"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              className="w-60 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
            />
            <select
              value={filterType}
              onChange={(e) => setFilterType(e.target.value)}
              aria-label="Filter triggers by type"
              className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none"
            >
              <option value="all">All types</option>
              {allTypes.map((t) => (
                <option key={t} value={t}>{t.replace("_", " ")}</option>
              ))}
            </select>
            <select
              value={filterEnabled}
              onChange={(e) => setFilterEnabled(e.target.value as "all" | "enabled" | "disabled")}
              aria-label="Filter triggers by enabled status"
              className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none"
            >
              <option value="all">All status</option>
              <option value="enabled">Enabled</option>
              <option value="disabled">Disabled</option>
            </select>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
            <span className="rounded-full border px-2 py-1">Visible {filtered.length}</span>
            <span className="rounded-full border px-2 py-1">Page {Math.min(trigPage + 1, Math.max(totalTrigPages, 1))} / {Math.max(totalTrigPages, 1)}</span>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center min-h-48">
          <p className="text-neutral-400 text-sm">Loading triggers…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-48 rounded-2xl border border-dashed border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900">
          <p className="text-neutral-400 text-sm">No triggers found</p>
          <p className="text-xs text-neutral-300 dark:text-neutral-600 mt-1">
            Define trigger_config in a procedure&apos;s CKP file, then click &quot;Sync from Procedures&quot;
          </p>
        </div>
      ) : (
        <div className="rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/50">
                  <th className="w-6 px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400"></th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Procedure</th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Type</th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Source</th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Limits</th>
                  <th className="px-3 py-2.5 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Updated</th>
                  <th className="px-3 py-2.5 text-right text-xs font-semibold uppercase tracking-wide text-neutral-400">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {pagedTriggers.map((trigger) => {
                  const key = `${trigger.procedure_id}:${trigger.version}`;
                  const isFiring = firing === key;
                  const isDeleting = deleting === key;
                  const updatedAt = new Date(trigger.updated_at);
                  const scheduleOrSource = trigger.schedule ?? trigger.event_source ?? "—";
                  return (
                    <tr key={trigger.id} className={`hover:bg-neutral-50 dark:hover:bg-neutral-800/50 transition-colors ${!trigger.enabled ? "opacity-60" : ""}`}>
                      <td className="px-3 py-2.5">
                        <EnabledDot enabled={trigger.enabled} />
                      </td>
                      <td className="px-3 py-2.5">
                        <div className="max-w-sm">
                          <p className="truncate font-medium text-neutral-900 dark:text-neutral-100">{trigger.procedure_id}</p>
                          <p className="mt-0.5 font-mono text-[11px] text-neutral-500">v{trigger.version}</p>
                        </div>
                      </td>
                      <td className="px-3 py-2.5">
                        <TriggerTypeBadge type={trigger.trigger_type} />
                      </td>
                      <td className="px-3 py-2.5 font-mono text-xs text-neutral-500 max-w-xs truncate" title={scheduleOrSource}>
                        {scheduleOrSource}
                      </td>
                      <td className="px-3 py-2.5 text-xs text-neutral-500">
                        <div className="space-y-0.5">
                          <p>Dedupe {trigger.dedupe_window_seconds}s</p>
                          <p>Max {trigger.max_concurrent_runs ?? "∞"}</p>
                        </div>
                      </td>
                      <td className="px-3 py-2.5 text-xs text-neutral-400">
                        {updatedAt.toLocaleDateString()} {updatedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </td>
                      <td className="px-3 py-2.5 text-right">
                        <div className="flex items-center justify-end gap-2">
                          <button
                            onClick={() => handleFire(trigger)}
                            disabled={isFiring || !trigger.enabled}
                            title="Fire Now"
                            className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                          >
                            {isFiring ? "..." : "Fire"}
                          </button>

                          {trigger.trigger_type === "webhook" && (
                            <button
                              onClick={() => copyWebhook(trigger)}
                              title="Copy webhook URL"
                              className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-2 py-1 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
                            >
                              Copy URL
                            </button>
                          )}

                          <button
                            onClick={() => handleDelete(trigger)}
                            disabled={isDeleting}
                            title="Delete trigger"
                            className="rounded-lg border border-red-200 dark:border-red-900/40 px-2 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 disabled:opacity-50 transition-colors"
                          >
                            {isDeleting ? "..." : "Delete"}
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </div>
      )}
      {!loading && totalTrigPages > 1 && (
        <div className="flex items-center justify-between px-2 py-1">
          <span className="text-xs text-neutral-400">{trigPage * TRIG_PAGE_SIZE + 1}–{Math.min((trigPage + 1) * TRIG_PAGE_SIZE, filtered.length)} of {filtered.length} triggers</span>
          <div className="flex items-center gap-1.5">
            <button onClick={() => setTrigPage((p) => Math.max(0, p - 1))} disabled={trigPage === 0}
              className="rounded px-2.5 py-1.5 text-xs font-medium border border-neutral-200 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-40 disabled:cursor-not-allowed">
              ← Prev
            </button>
            <span className="text-xs text-neutral-500 px-2">{trigPage + 1} / {totalTrigPages}</span>
            <button onClick={() => setTrigPage((p) => Math.min(totalTrigPages - 1, p + 1))} disabled={trigPage >= totalTrigPages - 1}
              className="rounded px-2.5 py-1.5 text-xs font-medium border border-neutral-200 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-40 disabled:cursor-not-allowed">
              Next →
            </button>
          </div>
        </div>
      )}

      <div className="rounded-2xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-4 py-3 text-xs text-neutral-500 dark:text-neutral-400 space-y-1">
        <p className="font-medium text-neutral-700 dark:text-neutral-300">How triggers work</p>
        <ul className="list-disc list-inside space-y-0.5 ml-1">
          <li><strong>scheduled</strong> — cron expression fires a run on a fixed schedule (server-side APScheduler)</li>
          <li><strong>webhook</strong> — POST to the webhook URL starts a run; use Copy URL for the endpoint</li>
          <li><strong>event</strong> — listens for named events via <code>/api/triggers/…/sync</code></li>
          <li><strong>file_watch</strong> — polls a file path; fires when mtime changes</li>
          <li><strong>manual</strong> — no automatic firing; use the Fire button or the REST API</li>
        </ul>
        <p className="pt-1">Triggers are defined in procedure CKP files under <code>trigger_config</code> and synced automatically on startup or via the Sync button.</p>
      </div>

      <ConfirmDialog
        open={confirmDelete !== null}
        title="Delete Trigger"
        message={`Are you sure you want to delete the trigger for ${confirmDelete?.procedure_id}@${confirmDelete?.version}?\n\nThis will stop automatic runs. You can restore it later by re-syncing.`}
        confirmLabel="Delete Trigger"
        danger={true}
        onConfirm={performDelete}
        onCancel={() => setConfirmDelete(null)}
      />

      <ConfirmDialog
        open={confirmFire !== null}
        title="Fire Trigger Manually"
        message={`Are you sure you want to manually fire a run for ${confirmFire?.procedure_id}@${confirmFire?.version}?\n\nThis will immediately dispatch a new job to the orchestrated workers.`}
        confirmLabel="Fire Now"
        danger={false}
        onConfirm={performFire}
        onCancel={() => setConfirmFire(null)}
      />
    </div>
  );
}
