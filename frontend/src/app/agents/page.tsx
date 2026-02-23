"use client";

import { useEffect, useState } from "react";
import { listAgents, registerAgent, updateAgent, deleteAgent, getActionCatalog, syncAgentCapabilities, probeAgentCapabilities } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { AgentInstance } from "@/lib/types";

// Suggested channels — user can type anything; these are just hints shown via datalist
const SUGGESTED_CHANNELS = ["web", "desktop", "email", "api", "database", "llm", "masteragent", "crm", "erp", "iot", "voice", "chat"];

const STATUS_COLORS: Record<string, string> = {
  online:  "bg-green-500",
  offline: "bg-gray-400",
  busy:    "bg-yellow-500",
};

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

export default function AgentsPage() {
  const [agents, setAgents]   = useState<AgentInstance[]>([]);
  const [catalog, setCatalog] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [showRegister, setShowRegister] = useState(false);
  const [form, setForm] = useState({
    agent_id: "",
    name: "",
    channel: "web",
    base_url: "http://localhost:9000",
    resource_key: "",
    concurrency_limit: 1,
    capabilities: [] as string[],
  });
  // Track existing channels from registered agents for the datalist
  const [registeredChannels, setRegisteredChannels] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [capInput, setCapInput] = useState("");
  const [probingCaps, setProbingCaps] = useState(false);
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [confirmDeleteAgent, setConfirmDeleteAgent] = useState<AgentInstance | null>(null);
  const { toast } = useToast();

  useEffect(() => {
    void Promise.all([loadAgents(), loadCatalog()]);
  }, []);

  async function loadAgents() {
    try {
      const data = await listAgents();
      setAgents(data);
      // Collect unique channels already in use
      const unique = [...new Set(data.map((a) => a.channel))];
      setRegisteredChannels(unique);
    } catch (err) {
      toast(err instanceof Error ? err.message : "Failed to load agents", "error");
    } finally {
      setLoading(false);
    }
  }

  async function loadCatalog() {
    try { setCatalog(await getActionCatalog()); } catch (_) { /* non-critical */ }
  }

  async function handleRegister() {
    setError("");
    if (!form.name || !form.base_url) {
      setError("Name and Base URL are required");
      return;
    }
    try {
      await registerAgent({
        ...form,
        resource_key: form.resource_key || `${form.channel}_default`,
        capabilities: form.capabilities.length > 0 ? form.capabilities : undefined,
      });
      setShowRegister(false);
      setForm({
        agent_id: "",
        name: "",
        channel: "web",
        base_url: "http://localhost:9000",
        resource_key: "",
        concurrency_limit: 1,
        capabilities: [],
      });
      setCapInput("");
      toast("Agent registered successfully", "success");
      void loadAgents();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Registration failed";
      setError(msg);
      toast(msg, "error");
    }
  }

  // Merge catalog channels with suggested + registered channels for the datalist
  const allChannelSuggestions = [...new Set([
    ...SUGGESTED_CHANNELS,
    ...registeredChannels,
    ...Object.keys(catalog),
  ])].sort();

  const channelActions = catalog[form.channel] ?? [];

  function addCapability(value?: string) {
    const cap = (value ?? capInput).trim().toLowerCase().replace(/\s+/g, "_");
    if (!cap || form.capabilities.includes(cap)) { setCapInput(""); return; }
    setForm((prev) => ({ ...prev, capabilities: [...prev.capabilities, cap] }));
    setCapInput("");
  }

  function removeCapability(cap: string) {
    setForm((prev) => ({ ...prev, capabilities: prev.capabilities.filter((c) => c !== cap) }));
  }

  async function handleFetchCapabilities() {
    if (!form.base_url) { setError("Enter a Base URL first"); return; }
    setProbingCaps(true);
    setError("");
    try {
      const caps = await probeAgentCapabilities(form.base_url);
      setForm((prev) => ({ ...prev, capabilities: caps }));
      toast(`Fetched ${caps.length} capabilities from agent`, "success");
    } catch {
      setError("Could not reach agent — is it running?");
    } finally {
      setProbingCaps(false);
    }
  }

  async function handleSyncCapabilities(agent: AgentInstance) {
    setSyncingId(agent.agent_id);
    try {
      await syncAgentCapabilities(agent.agent_id);
      toast("Capabilities synced from agent", "success");
      void loadAgents();
    } catch {
      toast("Failed to sync capabilities — is the agent reachable?", "error");
    } finally {
      setSyncingId(null);
    }
  }

  async function handleStatusToggle(agent: AgentInstance) {
    try {
      const next = agent.status === "online" ? "offline" : "online";
      await updateAgent(agent.agent_id, { status: next });
      toast(`Agent marked ${next}`, "success");
      void loadAgents();
    } catch {
      toast("Failed to update agent status", "error");
    }
  }

  async function handleDelete(agent: AgentInstance) {
    setConfirmDeleteAgent(agent);
  }

  async function doDeleteAgent() {
    if (!confirmDeleteAgent) return;
    const agent = confirmDeleteAgent;
    setConfirmDeleteAgent(null);
    try {
      await deleteAgent(agent.agent_id);
      toast("Agent deleted", "success");
      void loadAgents();
    } catch {
      toast("Failed to delete agent", "error");
    }
  }

  return (
    <div className="p-6 space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">Agents</h1>
          <p className="text-neutral-500 dark:text-neutral-400 mt-1">Manage workflow execution agents</p>
        </div>
        <button onClick={() => setShowRegister(true)}
          className="flex items-center gap-2 rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 transition-colors">
          <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" /></svg>
          Register Agent
        </button>
      </div>

      {/* Stat cards */}
      <div className="grid grid-cols-3 gap-4">
        {[
          { label: "Online", count: agents.filter(a => a.status === "online").length, color: "text-green-600", bg: "bg-green-50 dark:bg-green-950/30" },
          { label: "Busy", count: agents.filter(a => a.status === "busy").length, color: "text-amber-600", bg: "bg-amber-50 dark:bg-amber-950/30" },
          { label: "Total", count: agents.length, color: "text-blue-600", bg: "bg-blue-50 dark:bg-blue-950/30" },
        ].map((s) => (
          <div key={s.label} className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5 shadow-sm">
            <p className="text-sm text-neutral-500 dark:text-neutral-400">{s.label}</p>
            <p className={`mt-1 text-3xl font-bold ${s.color}`}>{s.count}</p>
          </div>
        ))}
      </div>

      {/* Registration form */}
      {showRegister && (
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-6 shadow-sm">
          <h3 className="mb-4 text-base font-semibold text-neutral-900 dark:text-neutral-100">Register New Agent</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="agent_id" className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Agent ID</label>
              <input id="agent_id" title="Agent ID" value={form.agent_id} onChange={(e) => setForm({ ...form, agent_id: e.target.value })}
                className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" placeholder="desktop-agent-1" />
            </div>
            <div>
              <label htmlFor="name" className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Name</label>
              <input id="name" title="Name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" placeholder="Desktop Agent #1" />
            </div>
            <div>
              <label htmlFor="channel" className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">
                Channel <span className="text-neutral-400 font-normal">(type or pick)</span>
              </label>
              <input id="channel" list="channel-suggestions" title="Channel" value={form.channel}
                onChange={(e) => setForm({ ...form, channel: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
                className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none"
                placeholder="e.g. web, desktop, crm..." autoComplete="off" />
              <datalist id="channel-suggestions">
                {allChannelSuggestions.map((ch) => <option key={ch} value={ch} />)}
              </datalist>
            </div>
            <div>
              <label htmlFor="base_url" className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Base URL</label>
              <div className="flex gap-2">
                <input id="base_url" title="Base URL" value={form.base_url} onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" placeholder="http://localhost:9000" />
                <button type="button" onClick={handleFetchCapabilities} disabled={probingCaps}
                  className="whitespace-nowrap rounded-lg border border-blue-300 dark:border-blue-700 bg-blue-50 dark:bg-blue-950/50 px-3 text-xs font-medium text-blue-700 dark:text-blue-400 hover:bg-blue-100 dark:hover:bg-blue-950 disabled:opacity-50">
                  {probingCaps ? "Fetching…" : "Fetch Caps"}
                </button>
              </div>
            </div>
            <div>
              <label htmlFor="resource_key" className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Resource Key</label>
              <input id="resource_key" title="Resource Key" value={form.resource_key} onChange={(e) => setForm({ ...form, resource_key: e.target.value })}
                className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" placeholder="auto-generated if empty" />
            </div>
            <div>
              <label htmlFor="concurrency_limit" className="mb-1 block text-xs font-medium text-neutral-600 dark:text-neutral-400">Concurrency Limit</label>
              <input id="concurrency_limit" title="Concurrency Limit" type="number" min={1} value={form.concurrency_limit}
                onChange={(e) => setForm({ ...form, concurrency_limit: parseInt(e.target.value) || 1 })}
                className="w-full rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" />
            </div>
          </div>
          {/* Capabilities */}
          <div className="mt-4">
            <div className="mb-2 flex items-center justify-between">
              <label className="text-xs font-medium text-neutral-600 dark:text-neutral-400">
                Capabilities <span className="font-normal text-neutral-400">(leave empty = accept all)</span>
              </label>
              {form.capabilities.length > 0 && (
                <button type="button" onClick={() => setForm({ ...form, capabilities: [] })} className="text-xs text-neutral-400 hover:text-red-500">Clear all</button>
              )}
            </div>
            <div className="mb-2 flex min-h-[40px] flex-wrap gap-1.5 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 p-2">
              {form.capabilities.length === 0 ? (
                <span className="self-center text-xs italic text-neutral-400">No capabilities — will accept all actions</span>
              ) : form.capabilities.map((cap) => (
                <span key={cap} className="flex items-center gap-1 rounded-full bg-blue-100 dark:bg-blue-950/50 px-2.5 py-0.5 text-xs font-medium text-blue-800 dark:text-blue-300">
                  {cap}
                  <button type="button" onClick={() => removeCapability(cap)} className="ml-0.5 text-blue-500 hover:text-red-500">&times;</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input id="cap_input" list="cap-suggestions" value={capInput} onChange={(e) => setCapInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCapability(); } }}
                placeholder="Type a capability and press Enter or Add"
                className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" autoComplete="off" />
              <datalist id="cap-suggestions">
                {channelActions.filter((a) => !form.capabilities.includes(a)).map((a) => <option key={a} value={a} />)}
              </datalist>
              <button type="button" onClick={() => addCapability()} disabled={!capInput.trim()}
                className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-3 py-2 text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-40">
                Add
              </button>
            </div>
          </div>
          {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
          <div className="mt-4 flex gap-2">
            <button onClick={handleRegister} className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">Register</button>
            <button onClick={() => { setShowRegister(false); setError(""); }} className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-4 py-2 text-sm font-medium text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50">Cancel</button>
          </div>
        </div>
      )}

      {/* Agent grid */}
      {loading ? (
        <div className="flex items-center justify-center py-16">
          <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
        </div>
      ) : agents.length === 0 ? (
        <div className="rounded-xl border border-dashed border-neutral-300 dark:border-neutral-700 p-16 text-center text-neutral-400">
          No agents registered. Click &quot;Register Agent&quot; to add one.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <div key={agent.agent_id} className={`rounded-xl border bg-white dark:bg-neutral-900 p-5 shadow-sm ${agent.circuit_open_at ? "border-red-300 dark:border-red-800 ring-1 ring-red-200 dark:ring-red-900" : "border-neutral-200 dark:border-neutral-800"}`}>
              <div className="flex items-center justify-between">
                <h3 className="font-semibold text-neutral-900 dark:text-neutral-100">{agent.name}</h3>
                <div className="flex items-center gap-1.5">
                  <div className={`h-2 w-2 rounded-full ${agent.status === "online" ? "bg-green-500" : agent.status === "busy" ? "bg-amber-500" : "bg-neutral-400"}`} />
                  <span className="text-xs text-neutral-500 dark:text-neutral-400">{agent.status}</span>
                </div>
              </div>
              <div className="mt-3 space-y-1.5 text-xs text-neutral-500 dark:text-neutral-400">
                <div className="flex items-center gap-2">
                  <span className="text-neutral-400">Channel:</span>
                  <span className="rounded-full bg-blue-50 dark:bg-blue-950/50 px-2 py-0.5 text-blue-700 dark:text-blue-400">{agent.channel}</span>
                </div>
                <p><span className="text-neutral-400">URL:</span> {agent.base_url}</p>
                <p><span className="text-neutral-400">Resource:</span> {agent.resource_key}</p>
                <div className="flex items-center gap-2">
                  <span className="text-neutral-400">Capacity:</span>
                  <div className="flex-1 h-1.5 rounded-full bg-neutral-100 dark:bg-neutral-800 overflow-hidden">
                    <div className="h-full bg-blue-500 rounded-full" style={{ width: `${(1 / Math.max(agent.concurrency_limit, 1)) * 100}%` }} />
                  </div>
                  <span className="text-neutral-400">{agent.concurrency_limit}</span>
                </div>
                <p className="text-neutral-400">Last seen: <span className={`font-medium ${Date.now() - new Date(agent.updated_at).getTime() < 120_000 ? "text-green-600 dark:text-green-400" : Date.now() - new Date(agent.updated_at).getTime() < 600_000 ? "text-amber-600 dark:text-amber-400" : "text-red-500 dark:text-red-400"}`}>{formatRelativeTime(agent.updated_at)}</span></p>
                {agent.circuit_open_at && (
                  <p className="flex items-center gap-1.5">
                    <span className="rounded-full bg-red-100 dark:bg-red-950/50 px-2 py-0.5 text-[10px] font-semibold text-red-700 dark:text-red-400">⚡ circuit open · {agent.consecutive_failures} failure{agent.consecutive_failures !== 1 ? "s" : ""}</span>
                  </p>
                )}
                {!agent.circuit_open_at && agent.consecutive_failures > 0 && (
                  <span className="rounded-full bg-amber-100 dark:bg-amber-950/50 px-2 py-0.5 text-[10px] font-semibold text-amber-700 dark:text-amber-400">⚠ {agent.consecutive_failures} consecutive failure{agent.consecutive_failures !== 1 ? "s" : ""}</span>
                )}
              </div>
              {agent.capabilities.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1 text-[10px] font-medium text-neutral-400 uppercase tracking-wider">Capabilities</p>
                  <div className="flex flex-wrap gap-1">
                    {agent.capabilities.map((cap) => (
                      <span key={cap} className="rounded-full bg-neutral-100 dark:bg-neutral-800 px-2 py-0.5 text-xs text-neutral-600 dark:text-neutral-400">{cap}</span>
                    ))}
                  </div>
                </div>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <button onClick={() => handleStatusToggle(agent)}
                  className={`flex-1 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${agent.status === "online" ? "border-neutral-200 dark:border-neutral-700 text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800" : "border-green-300 dark:border-green-700 text-green-700 dark:text-green-400 hover:bg-green-50 dark:hover:bg-green-950"}`}>
                  Mark {agent.status === "online" ? "Offline" : "Online"}
                </button>
                <button onClick={() => handleSyncCapabilities(agent)} disabled={syncingId === agent.agent_id}
                  className="rounded-lg border border-blue-200 dark:border-blue-800 px-3 py-1.5 text-xs font-medium text-blue-700 dark:text-blue-400 hover:bg-blue-50 dark:hover:bg-blue-950 disabled:opacity-50">
                  {syncingId === agent.agent_id ? "Syncing…" : "Sync Caps"}
                </button>
                <button onClick={() => handleDelete(agent)}
                  className="rounded-lg border border-red-200 dark:border-red-800 px-3 py-1.5 text-xs font-medium text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950">
                  Delete
                </button>
              </div>
            </div>
          ))}
        </div>
      )}

      <ConfirmDialog
        open={confirmDeleteAgent !== null}
        title="Delete Agent"
        message={confirmDeleteAgent ? `Delete agent "${confirmDeleteAgent.name}"? This cannot be undone.` : ""}
        confirmLabel="Delete"
        danger
        onConfirm={doDeleteAgent}
        onCancel={() => setConfirmDeleteAgent(null)}
      />
    </div>
  );
}



