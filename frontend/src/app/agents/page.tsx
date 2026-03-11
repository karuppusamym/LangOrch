"use client";

import { useEffect, useMemo, useState } from "react";
import { listAgents, registerAgent, updateAgent, deleteAgent, getActionCatalog, syncAgentCapabilities, probeAgentCapabilities } from "@/lib/api";
import { useToast } from "@/components/Toast";
import { ConfirmDialog } from "@/components/ConfirmDialog";
import type { AgentInstance, AgentCapability } from "@/lib/types";

// Suggested channels — user can type anything; these are just hints shown via datalist
const SUGGESTED_CHANNELS = ["web", "desktop", "email", "api", "database", "llm", "masteragent", "crm", "erp", "iot", "voice", "chat"];

const STATUS_COLORS: Record<string, string> = {
  online: "bg-green-500",
  offline: "bg-neutral-400",
  busy: "bg-yellow-500",
};

function formatRelativeTime(iso: string): string {
  const diff = Date.now() - new Date(iso).getTime();
  if (diff < 60_000) return "just now";
  if (diff < 3_600_000) return `${Math.floor(diff / 60_000)}m ago`;
  if (diff < 86_400_000) return `${Math.floor(diff / 3_600_000)}h ago`;
  return `${Math.floor(diff / 86_400_000)}d ago`;
}

function staleTone(updatedAt: string): string {
  const age = Date.now() - new Date(updatedAt).getTime();
  if (age < 120_000) return "text-emerald-600 dark:text-emerald-400";
  if (age < 600_000) return "text-amber-600 dark:text-amber-400";
  return "text-red-500 dark:text-red-400";
}

function statusPillClass(status: string): string {
  if (status === "online") return "bg-emerald-100 text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300";
  if (status === "busy") return "bg-amber-100 text-amber-700 dark:bg-amber-950/40 dark:text-amber-300";
  return "bg-neutral-200 text-neutral-700 dark:bg-neutral-800 dark:text-neutral-300";
}

function renderCapacitySlots(concurrencyLimit: number) {
  const slots = Math.max(1, Math.min(concurrencyLimit, 12));
  return Array.from({ length: slots }, (_, index) => (
    <div key={index} className="h-full flex-1 rounded-full bg-blue-500" />
  ));
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentInstance[]>([]);
  const [catalog, setCatalog] = useState<Record<string, string[]>>({});
  const [loading, setLoading] = useState(true);
  const [agentPage, setAgentPage] = useState(0);
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [channelFilter, setChannelFilter] = useState("all");
  const [showRegister, setShowRegister] = useState(false);
  const [form, setForm] = useState({
    agent_id: "",
    name: "",
    channel: "web",
    base_url: "http://localhost:9000",
    resource_key: "",
    concurrency_limit: 1,
    capabilities: [] as AgentCapability[],
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

  useEffect(() => {
    setAgentPage(0);
  }, [search, statusFilter, channelFilter]);

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
    const capName = (value ?? capInput).trim().toLowerCase().replace(/\s+/g, "_");
    if (!capName || form.capabilities.some((c) => c.name === capName)) { setCapInput(""); return; }
    const newCap: AgentCapability = { name: capName, type: "tool", description: null, estimated_duration_s: null, is_batch: false };
    setForm((prev) => ({ ...prev, capabilities: [...prev.capabilities, newCap] }));
    setCapInput("");
  }

  function removeCapability(capName: string) {
    setForm((prev) => ({ ...prev, capabilities: prev.capabilities.filter((c) => c.name !== capName) }));
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

  const agentChannels = useMemo(
    () => [...new Set(agents.map((agent) => agent.channel))].sort(),
    [agents],
  );

  const filteredAgents = useMemo(() => {
    const query = search.trim().toLowerCase();
    return agents.filter((agent) => {
      if (statusFilter !== "all" && agent.status !== statusFilter) return false;
      if (channelFilter !== "all" && agent.channel !== channelFilter) return false;
      if (!query) return true;
      return (
        agent.name.toLowerCase().includes(query) ||
        agent.agent_id.toLowerCase().includes(query) ||
        agent.channel.toLowerCase().includes(query) ||
        agent.resource_key.toLowerCase().includes(query) ||
        agent.base_url.toLowerCase().includes(query)
      );
    });
  }, [agents, channelFilter, search, statusFilter]);

  const summary = useMemo(() => {
    const online = agents.filter((agent) => agent.status === "online").length;
    const busy = agents.filter((agent) => agent.status === "busy").length;
    const circuitOpen = agents.filter((agent) => !!agent.circuit_open_at).length;
    const workflows = agents.filter((agent) => agent.capabilities.some((cap) => cap.type === "workflow")).length;
    return {
      online,
      busy,
      circuitOpen,
      workflows,
      total: agents.length,
      channels: agentChannels.length,
    };
  }, [agentChannels.length, agents]);

  const AGENT_PAGE_SIZE = 9;
  const totalAgentPages = Math.ceil(filteredAgents.length / AGENT_PAGE_SIZE);
  const pagedAgents = filteredAgents.slice(agentPage * AGENT_PAGE_SIZE, (agentPage + 1) * AGENT_PAGE_SIZE);

  return (
    <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 p-6">
      <div className="space-y-4">
        <section className="rounded-2xl border border-neutral-200 bg-white px-6 py-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div className="min-w-0 flex-1">
              <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-neutral-400">Infrastructure Workspace</p>
              <div className="mt-1 flex flex-wrap items-center gap-3">
                <h1 className="text-2xl font-semibold text-neutral-900 dark:text-neutral-100">Agents</h1>
                <span className="rounded-full border border-neutral-200 bg-white px-3 py-1 text-[11px] font-medium text-neutral-500 shadow-sm dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-400">
                  {filteredAgents.length} visible
                </span>
              </div>
              <p className="mt-1.5 max-w-3xl text-sm leading-5 text-neutral-600 dark:text-neutral-400">
                Register, monitor, and govern execution agents from a layout designed to hold far more channels, capabilities, and runtime states without turning into noise.
              </p>
            </div>
            <button
              onClick={() => setShowRegister(true)}
              className="inline-flex items-center gap-2 rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white shadow-sm transition hover:bg-blue-700"
            >
              <svg className="h-4 w-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M12 4v16m8-8H4" /></svg>
              Register Agent
            </button>
          </div>

          <div className="mt-4 grid gap-2.5 sm:grid-cols-2 xl:grid-cols-[repeat(4,minmax(0,1fr))_minmax(280px,1.1fr)]">
            {[
              { label: "Agents Online", value: summary.online, meta: `${summary.total} total`, tone: "text-emerald-600" },
              { label: "Busy Agents", value: summary.busy, meta: `${summary.channels} channels`, tone: "text-amber-600" },
              { label: "Workflow Capable", value: summary.workflows, meta: "workflow agents", tone: "text-blue-600" },
              { label: "Circuit Open", value: summary.circuitOpen, meta: "needs attention", tone: "text-red-600" },
            ].map((card) => (
              <div key={card.label} className="rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">{card.label}</p>
                <div className="mt-2 flex items-end justify-between gap-3">
                  <p className={`text-2xl font-semibold ${card.tone}`}>{card.value}</p>
                  <p className="text-xs text-neutral-500 dark:text-neutral-400">{card.meta}</p>
                </div>
              </div>
            ))}
            <div className="rounded-2xl border border-neutral-200 bg-white px-4 py-3 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
              <div className="flex flex-wrap items-center gap-2.5">
                <div className="relative min-w-[200px] flex-1">
              <svg className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-neutral-400" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" /></svg>
              <input
                type="search"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search agents, channels, URLs, resources..."
                className="w-full rounded-2xl border border-neutral-300 bg-neutral-50 py-2 pl-9 pr-3 text-sm text-neutral-900 outline-none transition focus:border-blue-500 dark:border-neutral-700 dark:bg-neutral-950/40 dark:text-neutral-100"
              />
                </div>
                <select
                  value={statusFilter}
                  onChange={(e) => setStatusFilter(e.target.value)}
                  aria-label="Filter agents by status"
                  className="rounded-2xl border border-neutral-300 bg-white px-3.5 py-2 text-sm text-neutral-700 outline-none transition focus:border-blue-500 dark:border-neutral-700 dark:bg-neutral-950/40 dark:text-neutral-300"
                >
                  <option value="all">All statuses</option>
                  <option value="online">Online</option>
                  <option value="busy">Busy</option>
                  <option value="offline">Offline</option>
                </select>
                <select
                  value={channelFilter}
                  onChange={(e) => setChannelFilter(e.target.value)}
                  aria-label="Filter agents by channel"
                  className="rounded-2xl border border-neutral-300 bg-white px-3.5 py-2 text-sm text-neutral-700 outline-none transition focus:border-blue-500 dark:border-neutral-700 dark:bg-neutral-950/40 dark:text-neutral-300"
                >
                  <option value="all">All channels</option>
                  {agentChannels.map((channel) => (
                    <option key={channel} value={channel}>{channel}</option>
                  ))}
                </select>
                <button
                  onClick={() => {
                    setSearch("");
                    setStatusFilter("all");
                    setChannelFilter("all");
                  }}
                  className="rounded-2xl border border-neutral-300 px-3.5 py-2 text-sm font-medium text-neutral-700 transition hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
                >
                  Reset
                </button>
              </div>
            </div>
          </div>
        </section>

        {showRegister && (
          <section className="rounded-2xl border border-neutral-200 bg-white px-6 py-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <div className="flex items-start justify-between gap-4">
              <div>
                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">Registration</p>
                <h2 className="mt-1 text-lg font-semibold text-neutral-900 dark:text-neutral-100">Register New Agent</h2>
                <p className="mt-1 text-sm leading-5 text-neutral-500 dark:text-neutral-400">Add a new execution endpoint, probe capabilities, and assign it to the right channel.</p>
              </div>
              <button
                onClick={() => { setShowRegister(false); setError(""); }}
                className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-600 transition hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800"
              >
                Close
              </button>
            </div>

            <div className="mt-4 grid gap-3 md:grid-cols-2">
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

            <div className="mt-3">
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
                <span key={cap.name} className="flex items-center gap-1 rounded-full bg-blue-100 dark:bg-blue-950/50 px-2.5 py-0.5 text-xs font-medium text-blue-800 dark:text-blue-300">
                  {cap.name}
                  <button type="button" onClick={() => removeCapability(cap.name)} className="ml-0.5 text-blue-500 hover:text-red-500">&times;</button>
                </span>
              ))}
            </div>
            <div className="flex gap-2">
              <input id="cap_input" list="cap-suggestions" value={capInput} onChange={(e) => setCapInput(e.target.value)}
                onKeyDown={(e) => { if (e.key === "Enter") { e.preventDefault(); addCapability(); } }}
                placeholder="Type a capability and press Enter or Add"
                className="flex-1 rounded-lg border border-neutral-300 dark:border-neutral-700 bg-white dark:bg-neutral-800 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none" autoComplete="off" />
              <datalist id="cap-suggestions">
                {channelActions.filter((a) => !form.capabilities.some((c) => c.name === a)).map((a) => <option key={a} value={a} />)}
              </datalist>
              <button type="button" onClick={() => addCapability()} disabled={!capInput.trim()}
                className="rounded-lg border border-neutral-300 dark:border-neutral-700 px-3 py-2 text-xs font-medium text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800 disabled:opacity-40">
                Add
              </button>
            </div>
            </div>
            {error && <p className="mt-2 text-sm text-red-600">{error}</p>}
            <div className="mt-3 flex gap-2">
              <button onClick={handleRegister} className="rounded-full bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700">Register Agent</button>
              <button onClick={() => { setShowRegister(false); setError(""); }} className="rounded-full border border-neutral-300 px-4 py-2 text-sm font-medium text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800">Cancel</button>
            </div>
          </section>
        )}

        {loading ? (
          <div className="flex items-center justify-center py-16">
            <div className="h-8 w-8 animate-spin rounded-full border-2 border-blue-600 border-t-transparent" />
          </div>
        ) : filteredAgents.length === 0 ? (
          <div className="rounded-2xl border border-dashed border-neutral-300 bg-white p-12 text-center text-neutral-500 shadow-sm dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-400">
            {agents.length === 0 ? "No agents registered yet. Register your first agent to start assigning execution capacity." : "No agents match the current filters."}
          </div>
      ) : (
          <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3">
            {pagedAgents.map((agent) => (
              <div key={agent.agent_id} className={`rounded-2xl border bg-white p-4 shadow-sm dark:bg-neutral-900 ${agent.circuit_open_at ? "border-red-300 ring-1 ring-red-200 dark:border-red-800 dark:ring-red-900/50" : "border-neutral-200 dark:border-neutral-800"}`}>
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-2">
                      <h3 className="truncate text-base font-semibold text-neutral-900 dark:text-neutral-100">{agent.name}</h3>
                      <span className={`rounded-full px-2.5 py-1 text-[10px] font-semibold uppercase ${statusPillClass(agent.status)}`}>
                        {agent.status}
                      </span>
                    </div>
                    <p className="mt-1 truncate text-xs text-neutral-500 dark:text-neutral-400">{agent.agent_id}</p>
                  </div>
                  <div className={`h-2.5 w-2.5 rounded-full ${STATUS_COLORS[agent.status] ?? "bg-neutral-400"}`} />
                </div>

                <div className="mt-3 grid grid-cols-2 gap-2.5">
                  <div className="rounded-2xl border border-neutral-200 bg-neutral-50 px-3.5 py-2.5 dark:border-neutral-800 dark:bg-neutral-800/60">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-neutral-400">Channel</p>
                    <p className="mt-1.5 text-sm font-medium text-neutral-900 dark:text-neutral-100">{agent.channel}</p>
                  </div>
                  <div className="rounded-2xl border border-neutral-200 bg-neutral-50 px-3.5 py-2.5 dark:border-neutral-800 dark:bg-neutral-800/60">
                    <p className="text-[10px] font-semibold uppercase tracking-[0.18em] text-neutral-400">Capacity</p>
                    <div className="mt-1.5 flex items-center gap-2">
                      <div className="flex h-2 flex-1 gap-1 overflow-hidden rounded-full bg-neutral-200 p-[1px] dark:bg-neutral-700">
                        {renderCapacitySlots(agent.concurrency_limit)}
                      </div>
                      <span className="text-xs font-medium text-neutral-600 dark:text-neutral-300">{agent.concurrency_limit}</span>
                    </div>
                  </div>
                </div>

                <div className="mt-3 space-y-1.5 text-xs text-neutral-500 dark:text-neutral-400">
                  <p className="truncate"><span className="font-medium text-neutral-700 dark:text-neutral-300">URL:</span> {agent.base_url}</p>
                  <p className="truncate"><span className="font-medium text-neutral-700 dark:text-neutral-300">Resource:</span> {agent.resource_key}</p>
                  <p>
                    <span className="font-medium text-neutral-700 dark:text-neutral-300">Last seen:</span>{" "}
                    <span className={`font-medium ${staleTone(agent.updated_at)}`}>{formatRelativeTime(agent.updated_at)}</span>
                  </p>
                </div>

                <div className="mt-3 flex flex-wrap gap-1.5">
                  {agent.circuit_open_at ? (
                    <span className="rounded-full bg-red-100 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-red-700 dark:bg-red-950/40 dark:text-red-300">
                      Circuit open · {agent.consecutive_failures} failure{agent.consecutive_failures !== 1 ? "s" : ""}
                    </span>
                  ) : agent.consecutive_failures > 0 ? (
                    <span className="rounded-full bg-amber-100 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-amber-700 dark:bg-amber-950/40 dark:text-amber-300">
                      {agent.consecutive_failures} consecutive failure{agent.consecutive_failures !== 1 ? "s" : ""}
                    </span>
                  ) : (
                    <span className="rounded-full bg-emerald-100 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.16em] text-emerald-700 dark:bg-emerald-950/40 dark:text-emerald-300">
                      Stable
                    </span>
                  )}
                </div>

                {agent.capabilities.length > 0 && (
                  <div className="mt-3">
                    <p className="mb-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-neutral-400">Capabilities</p>
                    <div className="flex flex-wrap gap-1.5">
                      {agent.capabilities.slice(0, 6).map((cap, index) => (
                        <span
                          key={`${cap.name}-${index}`}
                          className={`inline-flex items-center gap-1 rounded-full px-2.5 py-0.5 text-xs ${cap.type === "workflow"
                            ? "border border-violet-200 bg-violet-100 text-violet-700 dark:border-violet-800/50 dark:bg-violet-950/40 dark:text-violet-300"
                            : "bg-neutral-100 text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300"
                            }`}
                          title={cap.description || undefined}
                        >
                          {cap.name}
                          {cap.is_batch && <span className="text-[9px] font-bold uppercase opacity-60">Batch</span>}
                        </span>
                      ))}
                      {agent.capabilities.length > 6 && (
                        <span className="inline-flex items-center rounded-full bg-neutral-100 px-2.5 py-0.5 text-xs text-neutral-500 dark:bg-neutral-800 dark:text-neutral-400">
                          +{agent.capabilities.length - 6} more
                        </span>
                      )}
                    </div>
                  </div>
                )}

                <div className="mt-4 flex flex-wrap gap-2">
                  <button onClick={() => handleStatusToggle(agent)}
                    className={`flex-1 rounded-full border px-3 py-1.5 text-xs font-medium transition-colors ${agent.status === "online" ? "border-neutral-300 text-neutral-700 hover:bg-neutral-50 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800" : "border-green-300 text-green-700 hover:bg-green-50 dark:border-green-800 dark:text-green-400 dark:hover:bg-green-950/40"}`}>
                    Mark {agent.status === "online" ? "Offline" : "Online"}
                  </button>
                  <button onClick={() => handleSyncCapabilities(agent)} disabled={syncingId === agent.agent_id}
                    className="rounded-full border border-blue-200 px-3 py-1.5 text-xs font-medium text-blue-700 hover:bg-blue-50 disabled:opacity-50 dark:border-blue-800 dark:text-blue-400 dark:hover:bg-blue-950/40">
                    {syncingId === agent.agent_id ? "Syncing..." : "Sync Caps"}
                  </button>
                  <button onClick={() => handleDelete(agent)}
                    className="rounded-full border border-red-200 px-3 py-1.5 text-xs font-medium text-red-600 hover:bg-red-50 dark:border-red-800 dark:text-red-400 dark:hover:bg-red-950/40">
                    Delete
                  </button>
                </div>
              </div>
            ))}
          </div>
        )}

        {!loading && totalAgentPages > 1 && (
          <div className="flex items-center justify-between rounded-2xl border border-neutral-200 bg-white px-4 py-2.5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
            <span className="text-xs text-neutral-500 dark:text-neutral-400">{agentPage * AGENT_PAGE_SIZE + 1}–{Math.min((agentPage + 1) * AGENT_PAGE_SIZE, filteredAgents.length)} of {filteredAgents.length} agents</span>
            <div className="flex items-center gap-1.5">
            <button onClick={() => setAgentPage((p) => Math.max(0, p - 1))} disabled={agentPage === 0}
              className="rounded-full border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800">
              ← Prev
            </button>
            <span className="px-2 text-xs text-neutral-500 dark:text-neutral-400">{agentPage + 1} / {totalAgentPages}</span>
            <button onClick={() => setAgentPage((p) => Math.min(totalAgentPages - 1, p + 1))} disabled={agentPage >= totalAgentPages - 1}
              className="rounded-full border border-neutral-300 px-3 py-1.5 text-xs font-medium text-neutral-600 hover:bg-neutral-50 disabled:cursor-not-allowed disabled:opacity-40 dark:border-neutral-700 dark:text-neutral-300 dark:hover:bg-neutral-800">
              Next →
            </button>
          </div>
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
    </div>
  );
}



