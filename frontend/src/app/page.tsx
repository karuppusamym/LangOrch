"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { listProcedures, listRuns, listApprovals, listAgents, getMetricsSummary } from "@/lib/api";
import { StatusBadge } from "@/components/shared/StatusBadge";
import type { Procedure, Run, Approval, AgentInstance, MetricsSummary } from "@/lib/types";

interface Stats {
  procedures: number;
  runs: number;
  pendingApprovals: number;
  onlineAgents: number;
  recentRuns: Run[];
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    async function load() {
      try {
        const [procs, runs, approvals, agents] = await Promise.all([
          listProcedures(),
          listRuns(),
          listApprovals(),
          listAgents(),
        ]);
        setStats({
          procedures: procs.length,
          runs: runs.length,
          pendingApprovals: approvals.filter((a) => a.status === "pending").length,
          onlineAgents: agents.filter((a) => a.status === "online").length,
          recentRuns: runs.slice(0, 5),
        });
        // Load metrics separately (best-effort)
        getMetricsSummary().then(setMetrics).catch(() => null);
      } catch (err) {
        console.error("Dashboard load error", err);
      } finally {
        setLoading(false);
      }
    }
    load();
  }, []);

  if (loading) return <div className="text-gray-500">Loading dashboard...</div>;
  if (!stats) return <div className="text-red-500">Failed to load dashboard</div>;

  const cards = [
    { label: "Procedures", value: stats.procedures, href: "/procedures", color: "text-primary-600" },
    { label: "Total Runs", value: stats.runs, href: "/runs", color: "text-green-600" },
    { label: "Pending Approvals", value: stats.pendingApprovals, href: "/approvals", color: "text-yellow-600" },
    { label: "Online Agents", value: stats.onlineAgents, href: "/agents", color: "text-purple-600" },
  ];

  return (
    <div className="space-y-8">
      {/* Stat cards */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map((card) => (
          <Link
            key={card.label}
            href={card.href}
            className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm transition hover:shadow-md"
          >
            <p className="text-sm text-gray-500">{card.label}</p>
            <p className={`mt-2 text-3xl font-bold ${card.color}`}>{card.value}</p>
          </Link>
        ))}
      </div>

      {/* Metrics panel */}
      {metrics?.counters && Object.keys(metrics.counters).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-base font-semibold text-gray-900">Runtime Metrics</h2>
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {Object.entries(metrics.counters).map(([key, val]) => (
              <div key={key} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                <p className="text-[10px] text-gray-500 break-all">{key}</p>
                <p className="mt-1 text-sm font-bold text-gray-800">
                  {typeof val === "object" ? JSON.stringify(val) : String(val)}
                </p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Recent runs */}
      <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
        <h2 className="mb-4 text-base font-semibold text-gray-900">Recent Runs</h2>
        {stats.recentRuns.length === 0 ? (
          <p className="text-sm text-gray-400">No runs yet</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b text-left text-gray-500">
                <th className="pb-2">Run ID</th>
                <th className="pb-2">Procedure</th>
                <th className="pb-2">Status</th>
                <th className="pb-2">Started</th>
              </tr>
            </thead>
            <tbody>
              {stats.recentRuns.map((run) => (
                <tr key={run.run_id} className="border-b last:border-0">
                  <td className="py-2">
                    <Link href={`/runs/${run.run_id}`} className="text-primary-600 hover:underline">
                      {run.run_id.slice(0, 8)}…
                    </Link>
                  </td>
                  <td className="py-2">{run.procedure_id}</td>
                  <td className="py-2">
                    <StatusBadge status={run.status} />
                  </td>
                  <td className="py-2 text-gray-400">{new Date(run.created_at).toLocaleString()}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </div>
  );
}
