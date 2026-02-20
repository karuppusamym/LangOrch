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
    <div className="space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <p className="text-sm text-gray-500">{agents.length} agent(s) registered</p>
        <button
          onClick={() => setShowRegister(true)}
          className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
        >
          Register Agent
        </button>
      </div>

      {/* Registration form */}
      {showRegister && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h3 className="mb-4 text-sm font-semibold">Register New Agent</h3>
          <div className="grid grid-cols-2 gap-4">
            <div>
              <label htmlFor="agent_id" className="mb-1 block text-xs text-gray-500">Agent ID</label>
              <input
                id="agent_id"
                title="Agent ID"
                value={form.agent_id}
                onChange={(e) => setForm({ ...form, agent_id: e.target.value })}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="desktop-agent-1"
              />
            </div>
            <div>
              <label htmlFor="name" className="mb-1 block text-xs text-gray-500">Name</label>
              <input
                id="name"
                title="Name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="Desktop Agent #1"
              />
            </div>
            <div>
              <label htmlFor="channel" className="mb-1 block text-xs text-gray-500">
                Channel
                <span className="ml-1 text-gray-400">(type any name or pick from suggestions)</span>
              </label>
              <input
                id="channel"
                list="channel-suggestions"
                title="Channel"
                value={form.channel}
                onChange={(e) => setForm({ ...form, channel: e.target.value.toLowerCase().replace(/\s+/g, "_") })}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="e.g. web, desktop, crm, slack..."
                autoComplete="off"
              />
              <datalist id="channel-suggestions">
                {allChannelSuggestions.map((ch) => (
                  <option key={ch} value={ch} />
                ))}
              </datalist>
            </div>
            <div>
              <label htmlFor="base_url" className="mb-1 block text-xs text-gray-500">Base URL</label>
              <div className="flex gap-2">
                <input
                  id="base_url"
                  title="Base URL"
                  value={form.base_url}
                  onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                  className="flex-1 rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                  placeholder="http://localhost:9000"
                />
                <button
                  type="button"
                  onClick={handleFetchCapabilities}
                  disabled={probingCaps}
                  className="whitespace-nowrap rounded-lg border border-primary-300 bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-100 disabled:opacity-50"
                >
                  {probingCaps ? "Fetching…" : "Fetch Capabilities"}
                </button>
              </div>
            </div>
            <div>
              <label htmlFor="resource_key" className="mb-1 block text-xs text-gray-500">Resource Key</label>
              <input
                id="resource_key"
                title="Resource Key"
                value={form.resource_key}
                onChange={(e) => setForm({ ...form, resource_key: e.target.value })}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="auto-generated if empty"
              />
            </div>
            <div>
              <label htmlFor="concurrency_limit" className="mb-1 block text-xs text-gray-500">Concurrency Limit</label>
              <input
                id="concurrency_limit"
                title="Concurrency Limit"
                type="number"
                min={1}
                value={form.concurrency_limit}
                onChange={(e) =>
                  setForm({ ...form, concurrency_limit: parseInt(e.target.value) || 1 })
                }
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="1"
              />
            </div>
          </div>
          {/* Capabilities — chips-based, always visible, fully free-form */}
          <div className="col-span-2 mt-4">
            <div className="mb-2 flex items-center justify-between">
              <label className="text-xs font-medium text-gray-600">
                Capabilities
                <span className="ml-1.5 font-normal text-gray-400">(leave empty = accepts all actions for this channel)</span>
              </label>
              {form.capabilities.length > 0 && (
                <button
                  type="button"
                  onClick={() => setForm({ ...form, capabilities: [] })}
                  className="text-xs text-gray-400 hover:text-red-500 hover:underline"
                >
                  Clear all
                </button>
              )}
            </div>
            {/* Current capability chips */}
            <div className="mb-2 flex min-h-[40px] flex-wrap gap-1.5 rounded-lg border border-gray-200 bg-gray-50 p-2">
              {form.capabilities.length === 0 ? (
                <span className="self-center text-xs italic text-gray-400">No capabilities set — will accept all actions for this channel</span>
              ) : (
                form.capabilities.map((cap) => (
                  <span
                    key={cap}
                    className="flex items-center gap-1 rounded-full bg-primary-100 px-2.5 py-0.5 text-xs font-medium text-primary-800"
                  >
                    {cap}
                    <button
                      type="button"
                      onClick={() => removeCapability(cap)}
                      className="ml-0.5 leading-none text-primary-500 hover:text-red-500"
                      title={`Remove ${cap}`}
                    >
                      &times;
                    </button>
                  </span>
                ))
              )}
            </div>
            {/* Manual add row */}
            <div className="flex gap-2">
              <input
                id="cap_input"
                list="cap-suggestions"
                value={capInput}
                onChange={(e) => setCapInput(e.target.value)}
                onKeyDown={(e) => {
                  if (e.key === "Enter") { e.preventDefault(); addCapability(); }
                }}
                placeholder="Type a capability name and press Enter or click Add"
                className="flex-1 rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                autoComplete="off"
              />
              <datalist id="cap-suggestions">
                {channelActions
                  .filter((a) => !form.capabilities.includes(a))
                  .map((a) => <option key={a} value={a} />)}
              </datalist>
              <button
                type="button"
                onClick={() => addCapability()}
                disabled={!capInput.trim()}
                className="rounded-lg border border-gray-300 bg-white px-3 py-2 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-40"
              >
                Add
              </button>
            </div>
          </div>
        {error && <p className="mt-3 text-sm text-red-600">{error}</p>}
        <div className="mt-4 flex gap-2">
          <button
            onClick={handleRegister}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          >
            Register
          </button>
          <button
            onClick={() => { setShowRegister(false); setError(""); }}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm font-medium text-gray-700 hover:bg-gray-50"
          >
            Cancel
          </button>
        </div>
        </div>
      )}

      {/* Agent grid */}
      {loading ? (
        <p className="text-gray-500">Loading agents...</p>
      ) : agents.length === 0 ? (
        <div className="rounded-xl border border-dashed border-gray-300 p-12 text-center text-gray-400">
          No agents registered. Click &quot;Register Agent&quot; to add one.
        </div>
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {agents.map((agent) => (
            <div
              key={agent.agent_id}
              className={`rounded-xl border bg-white p-5 shadow-sm ${agent.circuit_open_at ? "border-red-300 ring-1 ring-red-200" : "border-gray-200"}`}
            >
              <div className="flex items-center justify-between">
                <h3 className="font-medium text-gray-900">{agent.name}</h3>
                <AgentStatusDot status={agent.status} />
              </div>
              <div className="mt-3 space-y-1 text-xs text-gray-500">
                <p>
                  <span className="text-gray-400">Channel:</span>{" "}
                  <span className="rounded-full bg-primary-50 px-2 py-0.5 text-primary-700">{agent.channel}</span>
                </p>
                <p><span className="text-gray-400">URL:</span> {agent.base_url}</p>
                <p><span className="text-gray-400">Resource:</span> {agent.resource_key}</p>
                <p><span className="text-gray-400">Concurrency:</span> {agent.concurrency_limit}</p>
                <p className="text-gray-400">
                  Last seen:{" "}
                  <span className={`font-medium ${
                    Date.now() - new Date(agent.updated_at).getTime() < 120_000
                      ? "text-green-600"
                      : Date.now() - new Date(agent.updated_at).getTime() < 600_000
                      ? "text-yellow-600"
                      : "text-red-500"
                  }`}>
                    {formatRelativeTime(agent.updated_at)}
                  </span>
                </p>
                {agent.circuit_open_at && (
                  <p className="mt-1 flex items-center gap-1.5">
                    <span className="rounded-full bg-red-100 px-2 py-0.5 text-[10px] font-semibold text-red-700">
                      ⚡ circuit open · {agent.consecutive_failures} failure{agent.consecutive_failures !== 1 ? "s" : ""}
                    </span>
                    <span className="text-gray-400">since {formatRelativeTime(agent.circuit_open_at)}</span>
                  </p>
                )}
                {!agent.circuit_open_at && agent.consecutive_failures > 0 && (
                  <p className="mt-0.5">
                    <span className="rounded-full bg-yellow-100 px-2 py-0.5 text-[10px] font-semibold text-yellow-700">
                      ⚠ {agent.consecutive_failures} consecutive failure{agent.consecutive_failures !== 1 ? "s" : ""}
                    </span>
                  </p>
                )}
              </div>
              {agent.capabilities.length > 0 && (
                <div className="mt-3">
                  <p className="mb-1 text-xs text-gray-400">Capabilities</p>
                  <div className="flex flex-wrap gap-1">
                    {agent.capabilities.map((cap) => (
                      <span key={cap} className="rounded-full bg-gray-100 px-2 py-0.5 text-xs text-gray-600">
                        {cap}
                      </span>
                    ))}
                  </div>
                </div>
              )}
              <div className="mt-4 flex flex-wrap gap-2">
                <button
                  onClick={() => handleStatusToggle(agent)}
                  className={`flex-1 rounded-lg border px-3 py-1.5 text-xs font-medium transition-colors ${
                    agent.status === "online"
                      ? "border-gray-300 text-gray-600 hover:bg-gray-50"
                      : "border-green-300 text-green-700 hover:bg-green-50"
                  }`}
                >
                  Mark {agent.status === "online" ? "Offline" : "Online"}
                </button>
                <button
                  onClick={() => handleSyncCapabilities(agent)}
                  disabled={syncingId === agent.agent_id}
                  title="Pull latest capabilities from the live agent"
                  className="rounded-lg border border-primary-200 px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-50 disabled:opacity-50"
                >
                  {syncingId === agent.agent_id ? "Syncing…" : "Sync Capabilities"}
                </button>
                <button
                  onClick={() => handleDelete(agent)}
                  className="rounded-lg border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50"
                >
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

function AgentStatusDot({ status }: { status: string }) {
  return (
    <div className="flex items-center gap-1.5">
      <div className={`h-2 w-2 rounded-full ${STATUS_COLORS[status] ?? "bg-gray-400"}`} />
      <span className="text-xs text-gray-500">{status}</span>
    </div>
  );
}
