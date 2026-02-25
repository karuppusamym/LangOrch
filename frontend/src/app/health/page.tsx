"use client";

import { useEffect, useState } from "react";
import { fetchOrchestrators, fetchAgentPools } from "@/lib/api";
import { OrchestratorWorkerOut, AgentPoolStats } from "@/lib/types";

export default function HealthPage() {
    const [orchestrators, setOrchestrators] = useState<OrchestratorWorkerOut[]>([]);
    const [pools, setPools] = useState<AgentPoolStats[]>([]);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);

    const loadData = async () => {
        try {
            const [orchData, poolData] = await Promise.all([
                fetchOrchestrators(),
                fetchAgentPools(),
            ]);
            setOrchestrators(orchData);
            setPools(poolData);
            setError(null);
        } catch (err: any) {
            setError(err.message || "Failed to load health metrics");
        } finally {
            setLoading(false);
        }
    };

    useEffect(() => {
        loadData();
        const interval = setInterval(loadData, 5000); // Polling every 5s
        return () => clearInterval(interval);
    }, []);

    return (
        <div className="p-8 max-w-7xl mx-auto space-y-8 animate-in fade-in duration-500">
            <div className="flex items-center justify-between">
                <h1 className="text-2xl font-bold text-gray-900 tracking-tight">System Health</h1>
                <button
                    onClick={loadData}
                    className="rounded-lg bg-white px-4 py-2 text-sm font-semibold text-gray-700 shadow-sm ring-1 ring-inset ring-gray-300 hover:bg-gray-50 transition-colors"
                >
                    Refresh
                </button>
            </div>

            {error && (
                <div className="rounded-xl border-l-4 border-red-500 bg-red-50 p-4 shadow-sm">
                    <p className="text-sm font-medium text-red-800">{error}</p>
                </div>
            )}

            {/* Orchestrators Section */}
            <section className="space-y-4">
                <h2 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                    <span className="text-xl">⚙️</span>
                    Orchestrator Workers
                </h2>
                {loading && orchestrators.length === 0 ? (
                    <p className="text-sm text-gray-500">Loading orchestrators...</p>
                ) : orchestrators.length === 0 ? (
                    <p className="text-sm text-gray-500 italic">No orchestrators detected. Is the backend running?</p>
                ) : (
                    <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                        {orchestrators.map((orch) => (
                            <div
                                key={orch.worker_id}
                                className={`relative rounded-2xl border p-5 shadow-sm transition-all duration-300 ${orch.is_leader ? "border-emerald-300 bg-emerald-50 shadow-emerald-100" : "border-gray-200 bg-white"}`}
                            >
                                {orch.is_leader && (
                                    <span className="absolute -top-3 right-4 rounded-full bg-emerald-500 px-3 py-0.5 text-[10px] font-black tracking-widest text-white shadow-sm ring-2 ring-white">
                                        LEADER
                                    </span>
                                )}
                                <div className="flex items-center justify-between mb-3">
                                    <span className="text-[10px] font-bold uppercase tracking-widest text-gray-400">Worker ID</span>
                                    <span className={`flex h-2 w-2 rounded-full ${orch.status === 'online' ? 'bg-emerald-500' : 'bg-red-500'}`} title={orch.status} />
                                </div>
                                <p className="font-mono text-sm font-medium text-gray-800 truncate mb-4" title={orch.worker_id}>
                                    {orch.worker_id}
                                </p>
                                <div className="flex items-center justify-between text-xs">
                                    <span className="text-gray-500">Last Heartbeat</span>
                                    <span className="font-medium text-gray-700">
                                        {new Date(orch.last_heartbeat_at).toLocaleTimeString()}
                                    </span>
                                </div>
                            </div>
                        ))}
                    </div>
                )}
            </section>

            {/* Agent Pools Section */}
            <section className="space-y-4 pt-4">
                <h2 className="text-lg font-bold text-gray-800 flex items-center gap-2">
                    <span className="text-xl">🤖</span>
                    Agent Worker Pools
                </h2>
                {loading && pools.length === 0 ? (
                    <p className="text-sm text-gray-500">Loading agent pools...</p>
                ) : pools.length === 0 ? (
                    <p className="text-sm text-gray-500 italic">No agents registered.</p>
                ) : (
                    <div className="overflow-hidden rounded-2xl border border-gray-200 bg-white shadow-sm">
                        <table className="min-w-full divide-y divide-gray-200">
                            <thead className="bg-gray-50">
                                <tr>
                                    <th scope="col" className="px-6 py-4 text-left text-[11px] font-bold uppercase tracking-wider text-gray-500">Pool ID</th>
                                    <th scope="col" className="px-6 py-4 text-left text-[11px] font-bold uppercase tracking-wider text-gray-500">Channel</th>
                                    <th scope="col" className="px-6 py-4 text-center text-[11px] font-bold uppercase tracking-wider text-gray-500">Agents</th>
                                    <th scope="col" className="px-6 py-4 text-center text-[11px] font-bold uppercase tracking-wider text-gray-500">Active Leases</th>
                                    <th scope="col" className="px-6 py-4 text-right text-[11px] font-bold uppercase tracking-wider text-gray-500">Available Cap.</th>
                                </tr>
                            </thead>
                            <tbody className="divide-y divide-gray-100 bg-white">
                                {pools.map((pool, idx) => (
                                    <tr key={`${pool.pool_id}-${pool.channel}-${idx}`} className="hover:bg-gray-50 transition-colors">
                                        <td className="whitespace-nowrap px-6 py-4 text-sm font-medium text-gray-900">
                                            {pool.pool_id || <span className="text-gray-400 italic">default</span>}
                                        </td>
                                        <td className="whitespace-nowrap px-6 py-4 text-sm text-gray-600">
                                            <span className="inline-flex items-center rounded-md bg-indigo-50 px-2 py-1 text-xs font-medium text-indigo-700 ring-1 ring-inset ring-indigo-600/10">
                                                {pool.channel}
                                            </span>
                                        </td>
                                        <td className="whitespace-nowrap px-6 py-4 text-center">
                                            <div className="flex items-center justify-center gap-2">
                                                <span className="text-sm font-bold text-gray-900">{pool.agent_count}</span>
                                                {pool.circuit_open_count > 0 && (
                                                    <span className="inline-flex items-center rounded-full bg-red-100 px-1.5 py-0.5 text-[10px] font-medium text-red-700" title={`${pool.circuit_open_count} agents offline`}>
                                                        {pool.circuit_open_count} offline
                                                    </span>
                                                )}
                                            </div>
                                        </td>
                                        <td className="whitespace-nowrap px-6 py-4 text-center text-sm font-medium text-gray-900">
                                            {pool.active_leases}
                                        </td>
                                        <td className="whitespace-nowrap px-6 py-4 text-right">
                                            <span className={`text-sm font-black ${pool.available_capacity > 0 ? 'text-emerald-600' : 'text-red-500'}`}>
                                                {pool.available_capacity}
                                            </span>
                                            <span className="text-xs text-gray-400 font-medium ml-1">/ {pool.concurrency_limit_total}</span>
                                        </td>
                                    </tr>
                                ))}
                            </tbody>
                        </table>
                    </div>
                )}
            </section>
        </div>
    );
}
