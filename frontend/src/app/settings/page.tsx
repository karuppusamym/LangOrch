"use client";

import { useEffect, useState, useCallback } from "react";
import { getConfig, patchConfig, testLlmConnection, listRuns, listAgents, listProcedures, listProjects } from "@/lib/api";
import type { PlatformConfig } from "@/lib/types";

type Tab = "general" | "execution" | "security" | "llm" | "retention";

type PlatformStats = { totalRuns: number; totalAgents: number; totalProcedures: number; totalProjects: number };

function Toggle({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) {
  return value ? (
    <button onClick={() => onChange(false)} role="switch" aria-checked="true" aria-label="Toggle" title="Toggle"
      className="relative inline-flex h-6 w-11 rounded-full transition-colors focus:outline-none bg-blue-600">
      <span className="inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform mt-0.5 translate-x-5" />
    </button>
  ) : (
    <button onClick={() => onChange(true)} role="switch" aria-checked="false" aria-label="Toggle" title="Toggle"
      className="relative inline-flex h-6 w-11 rounded-full transition-colors focus:outline-none bg-neutral-300 dark:bg-neutral-600">
      <span className="inline-block h-5 w-5 rounded-full bg-white shadow transform transition-transform mt-0.5 translate-x-0.5" />
    </button>
  );
}

function Field({ label, children, help }: { label: string; children: React.ReactNode; help?: string }) {
  return (
    <div>
      <label className="mb-1 block text-sm font-medium text-neutral-700 dark:text-neutral-300">{label}</label>
      {children}
      {help && <p className="mt-1 text-xs text-neutral-400">{help}</p>}
    </div>
  );
}

function NumInput({ value, onChange }: { value: number; onChange: (n: number) => void }) {
  return (
    <input type="number" value={value} title="Number Input" placeholder="0"
      onChange={(e) => onChange(Number(e.target.value))}
      className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
  );
}

function TextInput({ value, onChange, placeholder }: { value: string; onChange: (s: string) => void; placeholder?: string }) {
  return (
    <input type="text" value={value} placeholder={placeholder ?? "Enter text"} title={placeholder ?? "Text Input"}
      onChange={(e) => onChange(e.target.value)}
      className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
  );
}

function SaveBar({ dirty, saving, onSave }: { dirty: boolean; saving: boolean; onSave: () => void }) {
  if (!dirty && !saving) return null;
  return (
    <div className="flex flex-col gap-3 rounded-2xl border border-amber-200 bg-amber-50 px-4 py-3 dark:border-amber-800 dark:bg-amber-950/30 sm:flex-row sm:items-center sm:justify-between">
      <p className="text-xs text-amber-700 dark:text-amber-400">
        Changes take effect immediately and are persisted to the database across server restarts.
      </p>
      <button onClick={onSave} disabled={saving}
        className="shrink-0 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-60">
        {saving ? "Saving…" : "Save Changes"}
      </button>
    </div>
  );
}

export default function SettingsPage() {
  const [tab, setTab] = useState<Tab>("general");
  const [cfg, setCfg] = useState<PlatformConfig | null>(null);
  const [draft, setDraft] = useState<Partial<PlatformConfig>>({});
  const [stats, setStats] = useState<PlatformStats | null>(null);
  const [saving, setSaving] = useState(false);
  const [savedAt, setSavedAt] = useState<Date | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [llmTesting, setLlmTesting] = useState(false);
  const [llmTestResult, setLlmTestResult] = useState<{ ok: boolean; model?: string; response?: string; error?: string } | null>(null);

  const dirty = Object.keys(draft).length > 0;

  const patch = useCallback(<K extends keyof PlatformConfig>(key: K, value: PlatformConfig[K]) => {
    setDraft((d) => ({ ...d, [key]: value }));
  }, []);

  const val = useCallback(<K extends keyof PlatformConfig>(key: K): PlatformConfig[K] => {
    if (key in draft) return (draft as PlatformConfig)[key];
    return cfg![key];
  }, [cfg, draft]);

  useEffect(() => {
    async function load() {
      try {
        const [config, runs, agents, procedures, projects] = await Promise.all([
          getConfig().catch(() => null),
          listRuns({ limit: 1 }).catch(() => []),
          listAgents().catch(() => []),
          listProcedures().catch(() => []),
          listProjects().catch(() => []),
        ]);
        if (config) setCfg(config);
        setStats({
          totalRuns: Array.isArray(runs) ? runs.length : 0,
          totalAgents: Array.isArray(agents) ? agents.length : 0,
          totalProcedures: Array.isArray(procedures) ? procedures.length : 0,
          totalProjects: Array.isArray(projects) ? projects.length : 0,
        });
      } catch (e) {
        setError(String(e));
      }
    }
    void load();
  }, []);

  async function handleSave() {
    if (!dirty) return;
    setSaving(true);
    setError(null);
    try {
      const updated = await patchConfig(draft);
      setCfg(updated);
      setDraft({});
      setSavedAt(new Date());
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  }

  const TABS: { key: Tab; label: string }[] = [
    { key: "general", label: "General" },
    { key: "execution", label: "Execution" },
    { key: "security", label: "Security" },
    { key: "llm", label: "LLM" },
    { key: "retention", label: "Retention & Alerts" },
  ];

  if (!cfg) {
    return (
      <div className="p-6 flex items-center justify-center min-h-64">
        <p className="text-neutral-400 text-sm">Loading configuration…</p>
      </div>
    );
  }

  return (
    <div className="min-h-[calc(100vh-4rem)] space-y-6 bg-neutral-50 p-6">
      <section className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-neutral-400">Platform Controls</p>
            <h1 className="mt-1 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">Settings</h1>
            <p className="mt-1 max-w-3xl text-sm text-neutral-500 dark:text-neutral-400">Platform configuration, execution defaults, security controls, provider settings, and retention policies.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2 text-xs text-neutral-500 dark:text-neutral-400">
            {stats && (
              <>
                <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 dark:border-neutral-700 dark:bg-neutral-800">Runs {stats.totalRuns}</span>
                <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 dark:border-neutral-700 dark:bg-neutral-800">Agents {stats.totalAgents}</span>
                <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 dark:border-neutral-700 dark:bg-neutral-800">Procedures {stats.totalProcedures}</span>
                <span className="rounded-full border border-neutral-200 bg-neutral-50 px-2.5 py-1 dark:border-neutral-700 dark:bg-neutral-800">Projects {stats.totalProjects}</span>
              </>
            )}
            {dirty && <span className="rounded-full border border-amber-200 bg-amber-50 px-2.5 py-1 text-amber-700 dark:border-amber-900/40 dark:bg-amber-950/20 dark:text-amber-300">Unsaved changes</span>}
            {savedAt && (
              <span className="rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-emerald-700 dark:border-emerald-900/40 dark:bg-emerald-950/20 dark:text-emerald-300">
                Saved {savedAt.toLocaleTimeString()}
              </span>
            )}
          </div>
        </div>
      </section>

      {error && (
        <div className="rounded-lg border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 px-4 py-3 text-sm text-red-700 dark:text-red-400">
          {error}
        </div>
      )}

      <div className="rounded-2xl border border-neutral-200 bg-white p-2 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
        <div className="flex flex-wrap gap-2">
        {TABS.map(({ key, label }) => (
          <button key={key} onClick={() => setTab(key)}
            className={`rounded-2xl px-4 py-2 text-sm font-medium transition-colors ${tab === key
              ? "bg-blue-600 text-white"
              : "bg-neutral-50 text-neutral-500 hover:bg-neutral-100 hover:text-neutral-800 dark:bg-neutral-800/70 dark:text-neutral-300 dark:hover:bg-neutral-800 dark:hover:text-neutral-100"
              }`}>
            {label}
          </button>
        ))}
        </div>
      </div>

      {/* ── General ─────────────────────────────── */}
      {tab === "general" && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Platform Overview</h2>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
              {[
                { label: "Total Runs", value: stats?.totalRuns ?? "—" },
                { label: "Agents", value: stats?.totalAgents ?? "—" },
                { label: "Procedures", value: stats?.totalProcedures ?? "—" },
                { label: "Projects", value: stats?.totalProjects ?? "—" },
              ].map((item) => (
                <div key={item.label} className="rounded-2xl border border-neutral-200 bg-neutral-50 px-3 py-3 dark:border-neutral-800 dark:bg-neutral-800/60">
                  <p className="text-xs text-neutral-400 uppercase tracking-wide">{item.label}</p>
                  <p className="mt-1 text-2xl font-bold text-neutral-900 dark:text-neutral-100">{item.value}</p>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Server</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Host">
                <code className="block rounded-md bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-xs font-mono text-neutral-700 dark:text-neutral-300">{cfg.host}</code>
              </Field>
              <Field label="Port">
                <code className="block rounded-md bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-xs font-mono text-neutral-700 dark:text-neutral-300">{cfg.port}</code>
              </Field>
              <Field label="Debug mode">
                <div className="flex items-center gap-3 pt-1">
                  <Toggle value={val("debug")} onChange={(v) => patch("debug", v)} />
                  <span className="text-xs text-neutral-500">{val("debug") ? "Enabled" : "Disabled"}</span>
                </div>
              </Field>
              <Field label="Database" help={`Dialect: ${cfg.db_dialect}`}>
                <code className="block rounded-md bg-neutral-100 dark:bg-neutral-800 px-3 py-2 text-xs font-mono text-neutral-700 dark:text-neutral-300">
                  {cfg.db_dialect}{cfg.db_host ? ` @ ${cfg.db_host}:${cfg.db_port}/${cfg.db_name}` : " (SQLite)"}
                </code>
              </Field>
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">CORS Origins</h2>
            <Field label="Allowed origins" help="Comma-separated list of allowed origins for cross-origin requests">
              <TextInput
                value={val("cors_origins").join(", ")}
                onChange={(s) => patch("cors_origins", s.split(",").map((x) => x.trim()).filter(Boolean))}
              />
            </Field>
          </div>

          <SaveBar dirty={dirty} saving={saving} onSave={handleSave} />
        </div>
      )}

      {/* ── Execution ────────────────────────────── */}
      {tab === "execution" && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-1 text-base font-semibold text-neutral-900 dark:text-neutral-100">Worker Configuration</h2>
            <p className="mb-4 text-xs text-neutral-400">Controls the embedded durable worker. Changes take effect in-memory immediately.</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Embedded mode">
                <div className="flex items-center gap-3 pt-1">
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cfg.worker_embedded ? "bg-emerald-100 dark:bg-emerald-950/40 text-emerald-600" : "bg-neutral-100 dark:bg-neutral-800 text-neutral-400"}`}>
                    {cfg.worker_embedded ? "Enabled" : "Disabled"}
                  </span>
                  <span className="text-xs text-neutral-400">(restart required to toggle)</span>
                </div>
              </Field>
              <Field label="Concurrency" help="Max parallel run executions">
                <NumInput value={val("worker_concurrency")} onChange={(n) => patch("worker_concurrency", n)} />
              </Field>
              <Field label="Poll interval (s)" help="How often the worker polls for queued runs">
                <NumInput value={val("worker_poll_interval")} onChange={(n) => patch("worker_poll_interval", n)} />
              </Field>
              <Field label="Max attempts" help="Retry limit per run before marking as failed">
                <NumInput value={val("worker_max_attempts")} onChange={(n) => patch("worker_max_attempts", n)} />
              </Field>
              <Field label="Retry delay (s)" help="Base delay between retry attempts">
                <NumInput value={val("worker_retry_delay_seconds")} onChange={(n) => patch("worker_retry_delay_seconds", n)} />
              </Field>
              <Field label="Lock duration (s)" help="How long a worker lock is held before expiring">
                <NumInput value={val("worker_lock_duration_seconds")} onChange={(n) => patch("worker_lock_duration_seconds", n)} />
              </Field>
              <Field label="Rate limit (max concurrent)" help="Max concurrent runs across the platform">
                <NumInput value={val("rate_limit_max_concurrent")} onChange={(n) => patch("rate_limit_max_concurrent", n)} />
              </Field>
              <Field label="Lease TTL (s)" help="Duration of resource leases before auto-expiry">
                <NumInput value={val("lease_ttl_seconds")} onChange={(n) => patch("lease_ttl_seconds", n)} />
              </Field>
            </div>
          </div>
          <SaveBar dirty={dirty} saving={saving} onSave={handleSave} />
        </div>
      )}

      {/* ── Security ─────────────────────────────── */}
      {tab === "security" && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Authentication</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Auth enabled" help="When disabled, all requests are treated as admin">
                <div className="flex items-center gap-3 pt-1">
                  <Toggle value={val("auth_enabled")} onChange={(v) => patch("auth_enabled", v)} />
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${val("auth_enabled") ? "bg-emerald-100 dark:bg-emerald-950/40 text-emerald-600" : "bg-amber-100 dark:bg-amber-950/40 text-amber-600"}`}>
                    {val("auth_enabled") ? "Enforced" : "Disabled"}
                  </span>
                </div>
              </Field>
              <Field label="Token expiry (minutes)" help="JWT access token lifetime">
                <NumInput value={val("auth_token_expire_minutes")} onChange={(n) => patch("auth_token_expire_minutes", n)} />
              </Field>
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Platform Security Features</h2>
            <div className="space-y-3">
              {[
                { label: "Secret Redaction", description: "Mask sensitive values in run logs and audit events", enabled: true },
                { label: "Approval Gate Enforcement", description: "Block run progression when human-in-the-loop nodes time out", enabled: true },
                { label: "Lease-based Locking", description: "Prevent concurrent modification of shared resources via distributed leases", enabled: true },
                { label: "Circuit Breaker (Agents)", description: "Auto-open circuit after consecutive agent health failures", enabled: true },
              ].map(({ label, description, enabled }) => (
                <div key={label} className="flex items-start gap-3 rounded-lg border border-neutral-100 p-3 dark:border-neutral-800">
                  <span className={`mt-0.5 rounded-full w-2.5 h-2.5 flex-shrink-0 ${enabled ? "bg-emerald-500" : "bg-neutral-300"}`} />
                  <div className="flex-1">
                    <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{label}</p>
                    <p className="text-xs text-neutral-500 mt-0.5">{description}</p>
                  </div>
                  <span className="text-xs font-medium px-2 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-950/40 text-emerald-600 dark:text-emerald-400">Active</span>
                </div>
              ))}
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Secrets</h2>
            <Field label="Secrets rotation check" help="Warn when secrets have not been rotated recently">
              <div className="flex items-center gap-3 pt-1">
                <Toggle value={val("secrets_rotation_check")} onChange={(v) => patch("secrets_rotation_check", v)} />
                <span className="text-xs text-neutral-500">{val("secrets_rotation_check") ? "Enabled" : "Disabled"}</span>
              </div>
            </Field>
          </div>

          <SaveBar dirty={dirty} saving={saving} onSave={handleSave} />
        </div>
      )}

      {/* ── LLM ──────────────────────────────────── */}
      {tab === "llm" && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-1 text-base font-semibold text-neutral-900 dark:text-neutral-100">LLM Provider</h2>
            <p className="mb-4 text-xs text-neutral-400">Configure the default LLM endpoint used by agentic steps.</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Base URL" help="OpenAI-compatible endpoint (e.g. http://localhost:11434/v1)">
                <TextInput
                  value={val("llm_base_url") ?? ""}
                  onChange={(s) => patch("llm_base_url", s || null)}
                  placeholder="https://api.openai.com/v1"
                />
              </Field>
              <Field label="Timeout (s)" help="Per-request timeout for LLM calls">
                <NumInput value={val("llm_timeout_seconds")} onChange={(n) => patch("llm_timeout_seconds", n)} />
              </Field>
              <Field label="Default Model" help="Fallback model if none specified in the node">
                <TextInput
                  value={val("llm_default_model") ?? ""}
                  onChange={(s) => patch("llm_default_model", s || "gpt-4o")}
                  placeholder="gpt-4o"
                />
              </Field>
              <Field label="API Key">
                <div className="flex flex-col gap-2">
                  <TextInput
                    value={val("llm_api_key") ?? ""}
                    onChange={(s) => patch("llm_api_key", (s || null) as any)}
                    placeholder="Enter new API key to update..."
                  />
                  {cfg.llm_key_set && !val("llm_api_key") && (
                    <span className="text-xs text-emerald-600 dark:text-emerald-400 font-medium">
                      ✓ A key is currently configured
                    </span>
                  )}
                </div>
              </Field>
            </div>
            {/* Test Connection */}
            <div className="mt-4 flex flex-wrap items-center gap-3 border-t border-neutral-100 pt-3 dark:border-neutral-800">
              <button
                onClick={async () => {
                  setLlmTesting(true);
                  setLlmTestResult(null);
                  try {
                    const res = await testLlmConnection();
                    setLlmTestResult(res);
                  } catch (e) {
                    setLlmTestResult({ ok: false, error: e instanceof Error ? e.message : "Request failed" });
                  } finally {
                    setLlmTesting(false);
                  }
                }}
                disabled={llmTesting}
                className="flex items-center gap-2 rounded-lg border border-neutral-300 dark:border-neutral-700 px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-60 transition-colors"
              >
                {llmTesting ? (
                  <><span className="h-3.5 w-3.5 rounded-full border-2 border-blue-500 border-t-transparent animate-spin" />Testing…</>
                ) : (
                  <><svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M5 12h14M12 5l7 7-7 7" /></svg>Test Connection</>
                )}
              </button>
              {llmTestResult && (
                <div className={`flex flex-col gap-0.5 text-xs rounded-lg px-3 py-2 border ${
                  llmTestResult.ok
                    ? "bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800 text-emerald-700 dark:text-emerald-400"
                    : "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800 text-red-700 dark:text-red-400"
                }`}>
                  {llmTestResult.ok ? (
                    <>
                      <span className="font-semibold">✓ Connected — model: {llmTestResult.model}</span>
                      {llmTestResult.response && <span className="opacity-70">Response: “{llmTestResult.response}”</span>}
                    </>
                  ) : (
                    <span className="font-medium">✗ {llmTestResult.error}</span>
                  )}
                </div>
              )}
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-1 text-base font-semibold text-neutral-900 dark:text-neutral-100">Apigee Gateway (mTLS + OAuth2)</h2>
            <p className="mb-4 text-xs text-neutral-400">Configure Apigee token exchange to dynamically inject Bearer tokens into LLM calls.</p>
            <div className="space-y-4">
              <Field label="Enable Apigee Integration" help="Requires valid token URL, mTLS certs, and client credentials">
                <div className="flex items-center gap-3 pt-1">
                  <Toggle value={val("apigee_enabled")} onChange={(v) => patch("apigee_enabled", v)} />
                  <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${val("apigee_enabled") ? "bg-emerald-100 dark:bg-emerald-950/40 text-emerald-600" : "bg-neutral-100 dark:bg-neutral-800 text-neutral-400"}`}>
                    {val("apigee_enabled") ? "Enabled" : "Disabled"}
                  </span>
                </div>
              </Field>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Token URL" help="Apigee OAuth2 token endpoint">
                  <TextInput value={val("apigee_token_url") ?? ""} onChange={(s) => patch("apigee_token_url", s || null)} placeholder="https://api.enterprise.com/oauth/token" />
                </Field>
                <Field label="mTLS Cert Path" help="Absolute path to the dual PEM certificate file">
                  <TextInput value={val("apigee_certs_path") ?? ""} onChange={(s) => patch("apigee_certs_path", s || null)} placeholder="/app/certs/apigee.pem" />
                </Field>
                <Field label="Client ID / Consumer Key">
                  <TextInput value={val("apigee_client_id") ?? ""} onChange={(s) => patch("apigee_client_id", s || null)} placeholder="Enter Client ID" />
                </Field>
                <Field label="Client Secret / Consumer Secret">
                  <div className="relative">
                    <input
                      className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                      type="password"
                      value={val("apigee_client_secret") ?? ""}
                      onChange={(e) => patch("apigee_client_secret", e.target.value || null)}
                      placeholder="Enter Client Secret"
                    />
                  </div>
                </Field>
                <Field label="Use Case ID (Optional)">
                  <TextInput value={val("apigee_use_case_id") ?? ""} onChange={(s) => patch("apigee_use_case_id", s || null)} placeholder="Optional Use Case ID" />
                </Field>
              </div>
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-1 text-base font-semibold text-neutral-900 dark:text-neutral-100">Enterprise Configuration</h2>
            <p className="mb-4 text-xs text-neutral-400">Advanced configuration for standalone API gateways and custom model costs.</p>
            <div className="space-y-4">
              <Field label="API Gateway Headers (JSON)" help="Extra headers injected on every LLM call (e.g. proxy auth, tenant ID)">
                <textarea
                  value={val("llm_gateway_headers") ?? ""}
                  onChange={(e) => patch("llm_gateway_headers", e.target.value || null)}
                  placeholder='{"X-Tenant-ID": "acme", "X-Proxy-Auth": "bearer..."}'
                  rows={3}
                  className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
                />
              </Field>
              <Field label="Model Cost Override (JSON)" help="Override default token costs per 1K tokens">
                <textarea
                  value={val("llm_model_cost_json") ?? ""}
                  onChange={(e) => patch("llm_model_cost_json", e.target.value || null)}
                  placeholder='{"gpt-4": {"prompt": 0.03, "completion": 0.06}}'
                  rows={4}
                  className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 px-3 py-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
                />
              </Field>
            </div>
          </div>
          <SaveBar dirty={dirty} saving={saving} onSave={handleSave} />
        </div>
      )}

      {/* ── Retention & Alerts ──────────────────── */}
      {tab === "retention" && (
        <div className="space-y-4">
          <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-1 text-base font-semibold text-neutral-900 dark:text-neutral-100">Data Retention</h2>
            <p className="mb-4 text-xs text-neutral-400">Automatic pruning of old run events and artifact files.</p>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Checkpoint retention (days)" help="Run events older than this are pruned hourly (0 = keep forever)">
                <NumInput value={val("checkpoint_retention_days")} onChange={(n) => patch("checkpoint_retention_days", n)} />
              </Field>
              <Field label="Artifact retention (days)" help="Artifact folders for terminal runs are deleted after this period (0 = keep forever)">
                <NumInput value={val("artifact_retention_days")} onChange={(n) => patch("artifact_retention_days", n)} />
              </Field>
            </div>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Alerts</h2>
            <Field label="Alert webhook URL" help="POST failures/completions to this URL (leave empty to disable)">
              <TextInput
                value={val("alert_webhook_url") ?? ""}
                onChange={(s) => patch("alert_webhook_url", s || null)}
                placeholder="https://hooks.slack.com/services/…"
              />
            </Field>
          </div>

          <div className="rounded-2xl border border-neutral-200 bg-white p-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <h2 className="mb-3 text-base font-semibold text-neutral-900 dark:text-neutral-100">Metrics Push</h2>
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
              <Field label="Pushgateway URL" help="Prometheus Pushgateway target (leave empty to disable)">
                <TextInput
                  value={val("metrics_push_url") ?? ""}
                  onChange={(s) => patch("metrics_push_url", s || null)}
                  placeholder="http://localhost:9091"
                />
              </Field>
              <Field label="Push interval (s)">
                <NumInput value={val("metrics_push_interval_seconds")} onChange={(n) => patch("metrics_push_interval_seconds", n)} />
              </Field>
            </div>
          </div>

          <SaveBar dirty={dirty} saving={saving} onSave={handleSave} />
        </div>
      )}
    </div>
  );
}
