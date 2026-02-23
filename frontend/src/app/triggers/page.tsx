"use client";

import { useEffect, useState, useCallback } from "react";
import { listTriggers, fireTrigger, deleteTrigger, syncTriggers } from "@/lib/api";
import { useToast } from "@/components/Toast";
import type { TriggerRegistration } from "@/lib/types";

const TYPE_COLORS: Record<string, string> = {
  scheduled: "bg-blue-100 dark:bg-blue-950/40 text-blue-700 dark:text-blue-400",
  webhook:    "bg-purple-100 dark:bg-purple-950/40 text-purple-700 dark:text-purple-400",
  event:      "bg-amber-100 dark:bg-amber-950/40 text-amber-700 dark:text-amber-400",
  file_watch: "bg-teal-100 dark:bg-teal-950/40 text-teal-700 dark:text-teal-400",
  manual:     "bg-neutral-100 dark:bg-neutral-800 text-neutral-600 dark:text-neutral-400",
};

const TYPE_ICONS: Record<string, string> = {
  scheduled: "🕐",
  webhook:   "🔗",
  event:     "⚡",
  file_watch:"📁",
  manual:    "▶",
};

function TriggerTypeBadge({ type }: { type: string }) {
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs font-medium ${TYPE_COLORS[type] ?? TYPE_COLORS.manual}`}>
      <span>{TYPE_ICONS[type] ?? "▶"}</span>
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

  async function handleFire(trigger: TriggerRegistration) {
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

  async function handleDelete(trigger: TriggerRegistration) {
    if (!confirm(`Delete trigger for ${trigger.procedure_id}@${trigger.version}?`)) return;
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
    const apiBase = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
    const url = `${apiBase}/api/triggers/${encodeURIComponent(trigger.procedure_id)}/${encodeURIComponent(trigger.version)}/webhook`;
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

  const stats = {
    total: triggers.length,
    enabled: triggers.filter((t) => t.enabled).length,
    scheduled: triggers.filter((t) => t.trigger_type === "scheduled").length,
    webhook: triggers.filter((t) => t.trigger_type === "webhook").length,
  };

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Triggers</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Schedule, webhook, and event-based run triggers</p>
        </div>
        <button
          onClick={handleSync}
          disabled={syncing}
          className="flex items-center gap-2 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-60 transition-colors"
        >
          <svg className={`w-4 h-4 ${syncing ? "animate-spin" : ""}`} fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
          </svg>
          {syncing ? "Syncing…" : "Sync from Procedures"}
        </button>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-4">
        {[
          { label: "Total", value: stats.total, color: "text-neutral-900 dark:text-neutral-100" },
          { label: "Enabled", value: stats.enabled, color: "text-emerald-600 dark:text-emerald-400" },
          { label: "Scheduled", value: stats.scheduled, color: "text-blue-600 dark:text-blue-400" },
          { label: "Webhook", value: stats.webhook, color: "text-purple-600 dark:text-purple-400" },
        ].map((item) => (
          <div key={item.label} className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 px-5 py-4 shadow-sm">
            <p className="text-xs text-neutral-400 uppercase tracking-wide">{item.label}</p>
            <p className={`text-3xl font-bold mt-1 ${item.color}`}>{item.value}</p>
          </div>
        ))}
      </div>

      {/* Filters */}
      <div className="flex flex-wrap items-center gap-3">
        <input
          type="text"
          placeholder="Search procedure…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none w-56"
        />
        <select
          value={filterType}
          onChange={(e) => setFilterType(e.target.value)}
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
          className="rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 px-3 py-2 text-sm focus:outline-none"
        >
          <option value="all">All status</option>
          <option value="enabled">Enabled</option>
          <option value="disabled">Disabled</option>
        </select>
        <span className="text-xs text-neutral-400 ml-auto">{filtered.length} trigger{filtered.length !== 1 ? "s" : ""}</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="flex items-center justify-center min-h-48">
          <p className="text-neutral-400 text-sm">Loading triggers…</p>
        </div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center min-h-48 rounded-xl border border-dashed border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900">
          <p className="text-neutral-400 text-sm">No triggers found</p>
          <p className="text-xs text-neutral-300 dark:text-neutral-600 mt-1">
            Define trigger_config in a procedure&apos;s CKP file, then click &quot;Sync from Procedures&quot;
          </p>
        </div>
      ) : (
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 shadow-sm overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-neutral-100 dark:border-neutral-800 bg-neutral-50 dark:bg-neutral-900/50">
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400 w-6"></th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Procedure</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Version</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Type</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Schedule / Source</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Dedupe (s)</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Max Concurrent</th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wide text-neutral-400">Updated</th>
                  <th className="px-4 py-3 text-right text-xs font-semibold uppercase tracking-wide text-neutral-400">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-neutral-100 dark:divide-neutral-800">
                {filtered.map((trigger) => {
                  const key = `${trigger.procedure_id}:${trigger.version}`;
                  const isFiring = firing === key;
                  const isDeleting = deleting === key;
                  const updatedAt = new Date(trigger.updated_at);
                  const scheduleOrSource = trigger.schedule ?? trigger.event_source ?? "—";
                  return (
                    <tr key={trigger.id} className={`group hover:bg-neutral-50 dark:hover:bg-neutral-800/50 transition-colors ${!trigger.enabled ? "opacity-60" : ""}`}>
                      <td className="px-4 py-3">
                        <EnabledDot enabled={trigger.enabled} />
                      </td>
                      <td className="px-4 py-3 font-medium text-neutral-900 dark:text-neutral-100 max-w-xs truncate">
                        {trigger.procedure_id}
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-neutral-500">{trigger.version}</td>
                      <td className="px-4 py-3">
                        <TriggerTypeBadge type={trigger.trigger_type} />
                      </td>
                      <td className="px-4 py-3 font-mono text-xs text-neutral-500 max-w-xs truncate" title={scheduleOrSource}>
                        {scheduleOrSource}
                      </td>
                      <td className="px-4 py-3 text-xs text-neutral-500">{trigger.dedupe_window_seconds}</td>
                      <td className="px-4 py-3 text-xs text-neutral-500">{trigger.max_concurrent_runs ?? "∞"}</td>
                      <td className="px-4 py-3 text-xs text-neutral-400">
                        {updatedAt.toLocaleDateString()} {updatedAt.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
                      </td>
                      <td className="px-4 py-3 text-right">
                        <div className="flex items-center justify-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
                          {/* Fire button */}
                          <button
                            onClick={() => handleFire(trigger)}
                            disabled={isFiring || !trigger.enabled}
                            title="Fire Now"
                            className="rounded-lg bg-blue-600 px-3 py-1 text-xs font-medium text-white hover:bg-blue-700 disabled:opacity-50 transition-colors"
                          >
                            {isFiring ? "…" : "▶ Fire"}
                          </button>

                          {/* Webhook copy (only for webhook triggers) */}
                          {trigger.trigger_type === "webhook" && (
                            <button
                              onClick={() => copyWebhook(trigger)}
                              title="Copy webhook URL"
                              className="rounded-lg border border-neutral-200 dark:border-neutral-700 px-2 py-1 text-xs text-neutral-600 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
                            >
                              🔗
                            </button>
                          )}

                          {/* Delete */}
                          <button
                            onClick={() => handleDelete(trigger)}
                            disabled={isDeleting}
                            title="Delete trigger"
                            className="rounded-lg border border-red-200 dark:border-red-900/40 px-2 py-1 text-xs text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 disabled:opacity-50 transition-colors"
                          >
                            {isDeleting ? "…" : "✕"}
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

      {/* Help */}
      <div className="rounded-xl border border-neutral-100 dark:border-neutral-800/50 bg-neutral-50 dark:bg-neutral-900/50 px-5 py-4 text-xs text-neutral-500 dark:text-neutral-400 space-y-1">
        <p className="font-medium text-neutral-700 dark:text-neutral-300">How triggers work</p>
        <ul className="list-disc list-inside space-y-0.5 ml-1">
          <li><strong>scheduled</strong> — cron expression fires a run on a fixed schedule (server-side APScheduler)</li>
          <li><strong>webhook</strong> — POST to the webhook URL starts a run; copy the URL with 🔗</li>
          <li><strong>event</strong> — listens for named events via <code>/api/triggers/…/sync</code></li>
          <li><strong>file_watch</strong> — polls a file path; fires when mtime changes</li>
          <li><strong>manual</strong> — no automatic firing; use the ▶ Fire button or the REST API</li>
        </ul>
        <p className="pt-1">Triggers are defined in procedure CKP files under <code>trigger_config</code> and synced automatically on startup or via the Sync button.</p>
      </div>
    </div>
  );
}
