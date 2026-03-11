"use client";

import { useEffect, useMemo, useState } from "react";

import { fetchAgentPools, fetchOrchestrators } from "@/lib/api";
import type { AgentPoolStats, OrchestratorWorkerOut } from "@/lib/types";

function statusTone(status: string) {
    return status === "online"
        ? "bg-emerald-100 text-emerald-700"
        : "bg-red-100 text-red-700";
}

function formatPoolName(poolId: string) {
    return poolId || "default";
}

function capacityWidthClass(availableCapacity: number, totalCapacity: number) {
    if (totalCapacity <= 0) return "w-0";
    const ratio = availableCapacity / totalCapacity;
    if (ratio >= 0.95) return "w-full";
    if (ratio >= 0.875) return "w-11/12";
    if (ratio >= 0.8) return "w-10/12";
    if (ratio >= 0.7) return "w-9/12";
    if (ratio >= 0.6) return "w-8/12";
    if (ratio >= 0.5) return "w-6/12";
    if (ratio >= 0.4) return "w-5/12";
    if (ratio >= 0.3) return "w-4/12";
    if (ratio >= 0.2) return "w-3/12";
    if (ratio >= 0.1) return "w-2/12";
    if (ratio > 0) return "w-1/12";
    return "w-0";
}

export default function HealthPage() {
    const [orchestrators, setOrchestrators] = useState<OrchestratorWorkerOut[]>([]);
    const [pools, setPools] = useState<AgentPoolStats[]>([]);
    const [loading, setLoading] = useState(true);
    const [refreshing, setRefreshing] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);

    async function loadData({ silent = false }: { silent?: boolean } = {}) {
        if (silent) {
            setRefreshing(true);
        } else {
            setLoading(true);
        }

        try {
            const [orchData, poolData] = await Promise.all([
                fetchOrchestrators(),
                fetchAgentPools(),
            ]);
            setOrchestrators(orchData);
            setPools(poolData);
            setError(null);
            setLastUpdatedAt(new Date().toISOString());
        } catch (err) {
            setError(err instanceof Error ? err.message : "Failed to load health metrics");
        } finally {
            setLoading(false);
            setRefreshing(false);
        }
    }

    useEffect(() => {
        void loadData();
        const interval = setInterval(() => {
            void loadData({ silent: true });
        }, 5000);
        return () => clearInterval(interval);
    }, []);

    const summary = useMemo(() => {
        const onlineOrchestrators = orchestrators.filter((worker) => worker.status === "online").length;
        const leaderCount = orchestrators.filter((worker) => worker.is_leader).length;
        const totalAgents = pools.reduce((sum, pool) => sum + pool.agent_count, 0);
        const totalCapacity = pools.reduce((sum, pool) => sum + pool.concurrency_limit_total, 0);
        const totalAvailableCapacity = pools.reduce((sum, pool) => sum + pool.available_capacity, 0);
        const totalActiveLeases = pools.reduce((sum, pool) => sum + pool.active_leases, 0);
        const offlineAgents = pools.reduce((sum, pool) => sum + pool.circuit_open_count, 0);
        return {
            onlineOrchestrators,
            leaderCount,
            totalAgents,
            totalCapacity,
            totalAvailableCapacity,
            totalActiveLeases,
            offlineAgents,
        };
    }, [orchestrators, pools]);

    return (
        <div className="min-h-[calc(100vh-4rem)] bg-neutral-50 p-6">
            <div className="space-y-6">
                <section className="rounded-2xl border border-neutral-200 bg-white px-6 py-6 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                    <div className="flex flex-wrap items-start justify-between gap-4">
                        <div className="min-w-0 flex-1">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.24em] text-neutral-400">Platform Workspace</p>
                            <h1 className="mt-1 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">System Health</h1>
                            <p className="mt-2 max-w-3xl text-sm leading-6 text-neutral-600 dark:text-neutral-400">
                                Live health telemetry for orchestrator workers and agent pools, refreshed every five seconds in the same workspace style as the rest of the product.
                            </p>
                        </div>
                        <div className="flex flex-wrap items-center gap-3">
                            <div className="rounded-full border border-neutral-200 bg-white px-4 py-2 text-xs text-neutral-500 shadow-sm dark:border-neutral-800 dark:bg-neutral-900 dark:text-neutral-400">
                                {lastUpdatedAt ? `Last updated ${new Date(lastUpdatedAt).toLocaleTimeString()}` : "Waiting for first refresh..."}
                            </div>
                            <button
                                onClick={() => void loadData({ silent: true })}
                                className="rounded-full border border-neutral-300 bg-white px-4 py-2 text-sm font-medium text-neutral-700 transition hover:border-neutral-400 hover:bg-neutral-50 dark:border-neutral-700 dark:bg-neutral-900 dark:text-neutral-300 dark:hover:bg-neutral-800"
                            >
                                {refreshing ? "Refreshing..." : "Refresh now"}
                            </button>
                        </div>
                    </div>

                    <div className="mt-6 grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
                        <div className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">Orchestrators Online</p>
                            <div className="mt-3 flex items-end justify-between gap-3">
                                <p className="text-3xl font-semibold text-neutral-900 dark:text-neutral-100">{summary.onlineOrchestrators}</p>
                                <p className="text-xs text-neutral-500 dark:text-neutral-400">of {orchestrators.length || 0}</p>
                            </div>
                        </div>
                        <div className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">Leader Count</p>
                            <div className="mt-3 flex items-end justify-between gap-3">
                                <p className="text-3xl font-semibold text-neutral-900 dark:text-neutral-100">{summary.leaderCount}</p>
                                <p className="text-xs text-neutral-500 dark:text-neutral-400">active leaders</p>
                            </div>
                        </div>
                        <div className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">Agent Capacity</p>
                            <div className="mt-3 flex items-end justify-between gap-3">
                                <p className="text-3xl font-semibold text-neutral-900 dark:text-neutral-100">{summary.totalAvailableCapacity}</p>
                                <p className="text-xs text-neutral-500 dark:text-neutral-400">free of {summary.totalCapacity}</p>
                            </div>
                        </div>
                        <div className="rounded-2xl border border-neutral-200 bg-white px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                            <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">Active Leases</p>
                            <div className="mt-3 flex items-end justify-between gap-3">
                                <p className="text-3xl font-semibold text-neutral-900 dark:text-neutral-100">{summary.totalActiveLeases}</p>
                                <p className="text-xs text-neutral-500 dark:text-neutral-400">{summary.offlineAgents} agents offline</p>
                            </div>
                        </div>
                    </div>
                </section>

                {error && (
                    <div className="rounded-[24px] border border-red-200 bg-red-50 px-5 py-4 text-sm text-red-700 shadow-sm">
                        {error}
                    </div>
                )}

                <section className="grid gap-6 xl:grid-cols-[minmax(0,1.1fr)_minmax(0,1.4fr)]">
                    <div className="rounded-2xl border border-neutral-200 bg-white px-6 py-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">Runtime Control</p>
                                <h2 className="mt-1 text-lg font-semibold text-neutral-900 dark:text-neutral-100">Orchestrator Workers</h2>
                            </div>
                            <span className="rounded-full bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                                {orchestrators.length} total
                            </span>
                        </div>

                        {loading && orchestrators.length === 0 ? (
                            <p className="mt-6 text-sm text-neutral-500 dark:text-neutral-400">Loading orchestrators...</p>
                        ) : orchestrators.length === 0 ? (
                            <div className="mt-6 rounded-2xl border border-dashed border-neutral-300 bg-neutral-50 px-5 py-10 text-center text-sm text-neutral-500 dark:border-neutral-700 dark:bg-neutral-950/40 dark:text-neutral-400">
                                No orchestrators detected. Check whether the backend worker plane is running.
                            </div>
                        ) : (
                            <div className="mt-5 space-y-3">
                                {orchestrators.map((orch) => (
                                    <div
                                        key={orch.worker_id}
                                        className={`rounded-2xl border px-5 py-4 shadow-sm ${
                                            orch.is_leader ? "border-emerald-200 bg-emerald-50/70 dark:border-emerald-900/40 dark:bg-emerald-950/20" : "border-neutral-200 bg-neutral-50/80 dark:border-neutral-800 dark:bg-neutral-950/40"
                                        }`}
                                    >
                                        <div className="flex items-start justify-between gap-4">
                                            <div className="min-w-0">
                                                <div className="flex flex-wrap items-center gap-2">
                                                    <p className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{orch.worker_id}</p>
                                                    {orch.is_leader && (
                                                        <span className="rounded-full bg-emerald-600 px-2 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-white">
                                                            Leader
                                                        </span>
                                                    )}
                                                </div>
                                                <p className="mt-2 text-xs text-neutral-500 dark:text-neutral-400">
                                                    Last heartbeat {new Date(orch.last_heartbeat_at).toLocaleString()}
                                                </p>
                                            </div>
                                            <span className={`rounded-full px-3 py-1 text-xs font-medium ${statusTone(orch.status)}`}>
                                                {orch.status}
                                            </span>
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>

                    <div className="rounded-2xl border border-neutral-200 bg-white px-6 py-5 shadow-sm dark:border-neutral-800 dark:bg-neutral-900">
                        <div className="flex items-center justify-between gap-3">
                            <div>
                                <p className="text-[11px] font-semibold uppercase tracking-[0.2em] text-neutral-400">Worker Pools</p>
                                <h2 className="mt-1 text-lg font-semibold text-neutral-900 dark:text-neutral-100">Agent Capacity Overview</h2>
                            </div>
                            <span className="rounded-full bg-neutral-100 px-3 py-1 text-xs font-medium text-neutral-600 dark:bg-neutral-800 dark:text-neutral-300">
                                {summary.totalAgents} registered agents
                            </span>
                        </div>

                        {loading && pools.length === 0 ? (
                            <p className="mt-6 text-sm text-neutral-500 dark:text-neutral-400">Loading agent pools...</p>
                        ) : pools.length === 0 ? (
                            <div className="mt-6 rounded-2xl border border-dashed border-neutral-300 bg-neutral-50 px-5 py-10 text-center text-sm text-neutral-500 dark:border-neutral-700 dark:bg-neutral-950/40 dark:text-neutral-400">
                                No agent pools registered yet.
                            </div>
                        ) : (
                            <div className="mt-5 grid gap-4 lg:grid-cols-2">
                                {pools.map((pool, idx) => (
                                    <div key={`${pool.pool_id}-${pool.channel}-${idx}`} className="rounded-2xl border border-neutral-200 bg-neutral-50/80 px-5 py-4 shadow-sm dark:border-neutral-800 dark:bg-neutral-950/40">
                                        <div className="flex items-start justify-between gap-3">
                                            <div className="min-w-0">
                                                <p className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">{formatPoolName(pool.pool_id)}</p>
                                                <p className="mt-1 text-xs text-neutral-500 dark:text-neutral-400">Channel {pool.channel}</p>
                                            </div>
                                            <span className="rounded-full bg-sky-100 px-3 py-1 text-xs font-medium text-sky-700">
                                                {pool.available_capacity} free
                                            </span>
                                        </div>

                                        <div className="mt-4 grid grid-cols-2 gap-3">
                                            <div className="rounded-2xl border border-white bg-white px-4 py-3 dark:border-neutral-800 dark:bg-neutral-900">
                                                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-neutral-400">Agents</p>
                                                <p className="mt-2 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">{pool.agent_count}</p>
                                            </div>
                                            <div className="rounded-2xl border border-white bg-white px-4 py-3 dark:border-neutral-800 dark:bg-neutral-900">
                                                <p className="text-[11px] font-semibold uppercase tracking-[0.18em] text-neutral-400">Leases</p>
                                                <p className="mt-2 text-2xl font-semibold text-neutral-900 dark:text-neutral-100">{pool.active_leases}</p>
                                            </div>
                                        </div>

                                        <div className="mt-4 rounded-2xl border border-white bg-white px-4 py-3 dark:border-neutral-800 dark:bg-neutral-900">
                                            <div className="flex items-center justify-between gap-3 text-xs text-neutral-500 dark:text-neutral-400">
                                                <span>Available capacity</span>
                                                <span>
                                                    {pool.available_capacity} / {pool.concurrency_limit_total}
                                                </span>
                                            </div>
                                            <div className="mt-2 h-2 overflow-hidden rounded-full bg-neutral-200 dark:bg-neutral-800">
                                                <div
                                                    className={`h-full rounded-full bg-sky-500 ${capacityWidthClass(pool.available_capacity, pool.concurrency_limit_total)}`}
                                                />
                                            </div>
                                        </div>

                                        <div className="mt-4 flex flex-wrap gap-2">
                                            {Object.entries(pool.status_breakdown).map(([status, count]) => (
                                                <span key={status} className="rounded-full bg-white px-3 py-1 text-xs font-medium text-neutral-600 shadow-sm dark:bg-neutral-900 dark:text-neutral-300">
                                                    {status}: {count}
                                                </span>
                                            ))}
                                            {pool.circuit_open_count > 0 && (
                                                <span className="rounded-full bg-red-100 px-3 py-1 text-xs font-medium text-red-700">
                                                    {pool.circuit_open_count} offline
                                                </span>
                                            )}
                                        </div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                </section>
            </div>
        </div>
    );
}
