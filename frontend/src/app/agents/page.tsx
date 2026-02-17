"use client";

import { useEffect, useState } from "react";
import { listAgents, registerAgent } from "@/lib/api";
import type { AgentInstance } from "@/lib/types";

export default function AgentsPage() {
  const [agents, setAgents] = useState<AgentInstance[]>([]);
  const [loading, setLoading] = useState(true);
  const [showRegister, setShowRegister] = useState(false);
  const [form, setForm] = useState({
    agent_id: "",
    name: "",
    channel: "web",
    base_url: "http://localhost:9000",
    resource_key: "",
    concurrency_limit: 1,
  });
  const [error, setError] = useState("");

  useEffect(() => {
    loadAgents();
  }, []);

  async function loadAgents() {
    try {
      const data = await listAgents();
      setAgents(data);
    } catch (err) {
      console.error(err);
    } finally {
      setLoading(false);
    }
  }

  async function handleRegister() {
    setError("");
    if (!form.agent_id || !form.name || !form.base_url) {
      setError("Agent ID, name, and base URL are required");
      return;
    }
    try {
      await registerAgent({
        ...form,
        resource_key: form.resource_key || `${form.channel}_default`,
      });
      setShowRegister(false);
      setForm({
        agent_id: "",
        name: "",
        channel: "web",
        base_url: "http://localhost:9000",
        resource_key: "",
        concurrency_limit: 1,
      });
      loadAgents();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Registration failed");
    }
  }

  const CHANNELS = ["web", "desktop", "email", "api", "database", "llm"];

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
              <label htmlFor="channel" className="mb-1 block text-xs text-gray-500">Channel</label>
              <select
                id="channel"
                title="Channel"
                value={form.channel}
                onChange={(e) => setForm({ ...form, channel: e.target.value })}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
              >
                {CHANNELS.map((ch) => (
                  <option key={ch} value={ch}>
                    {ch}
                  </option>
                ))}
              </select>
            </div>
            <div>
              <label htmlFor="base_url" className="mb-1 block text-xs text-gray-500">Base URL</label>
              <input
                id="base_url"
                title="Base URL"
                value={form.base_url}
                onChange={(e) => setForm({ ...form, base_url: e.target.value })}
                className="w-full rounded-lg border border-gray-300 p-2 text-sm focus:border-primary-500 focus:outline-none"
                placeholder="http://localhost:9000"
              />
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
              className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm"
            >
              <div className="flex items-center justify-between">
                <h3 className="font-medium text-gray-900">{agent.name}</h3>
                <AgentStatusDot status={agent.status} />
              </div>
              <div className="mt-3 space-y-1 text-xs text-gray-500">
                <p>
                  <span className="text-gray-400">Channel:</span>{" "}
                  <span className="badge badge-info">{agent.channel}</span>
                </p>
                <p>
                  <span className="text-gray-400">URL:</span> {agent.base_url}
                </p>
                <p>
                  <span className="text-gray-400">Resource:</span> {agent.resource_key}
                </p>
                <p>
                  <span className="text-gray-400">Concurrency:</span> {agent.concurrency_limit}
                </p>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function AgentStatusDot({ status }: { status: string }) {
  const colors: Record<string, string> = {
    online: "bg-green-500",
    offline: "bg-gray-400",
    busy: "bg-yellow-500",
  };
  return (
    <div className="flex items-center gap-1.5">
      <div className={`h-2 w-2 rounded-full ${colors[status] ?? "bg-gray-400"}`} />
      <span className="text-xs text-gray-500">{status}</span>
    </div>
  );
}
