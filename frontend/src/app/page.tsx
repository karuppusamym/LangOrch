"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import { listProcedures, listRuns, listApprovals, listAgents, listProjects, getMetricsSummary } from "@/lib/api";
import { StatusBadge } from "@/components/shared/StatusBadge";
import type { Procedure, Run, Approval, AgentInstance, MetricsSummary } from "@/lib/types";

interface Stats {
  procedures: number;
  runs: number;
  pendingApprovals: number;
  onlineAgents: number;
  projects: number;
  recentRuns: Run[];
  runsByStatus: Record<string, number>;
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [metrics, setMetrics] = useState<MetricsSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = async () => {
    try {
      const [procs, runs, approvals, agents, projects] = await Promise.all([
        listProcedures(),
        listRuns(),
        listApprovals(),
        listAgents(),
        listProjects(),
      ]);
      // Count runs by status
      const runsByStatus: Record<string, number> = {};
      for (const r of runs) {
        runsByStatus[r.status] = (runsByStatus[r.status] ?? 0) + 1;
      }
      setStats({
        procedures: procs.length,
        runs: runs.length,
        pendingApprovals: approvals.filter((a) => a.status === "pending").length,
        onlineAgents: agents.filter((a) => a.status === "online").length,
        projects: projects.length,
        recentRuns: runs.slice(0, 8),
        runsByStatus,
      });
      getMetricsSummary().then(setMetrics).catch(() => null);
    } catch (err) {
      console.error("Dashboard load error", err);
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    load();
    timerRef.current = setInterval(load, 30000);
    return () => { if (timerRef.current) clearInterval(timerRef.current); };
  }, []);

  if (loading) return <div className="text-gray-500">Loading dashboard...</div>;
  if (!stats) return <div className="text-red-500">Failed to load dashboard</div>;

  const cards = [
    { label: "Projects", value: stats.projects, href: "/projects", color: "text-orange-600" },
    { label: "Procedures", value: stats.procedures, href: "/procedures", color: "text-primary-600" },
    { label: "Total Runs", value: stats.runs, href: "/runs", color: "text-green-600" },
    { label: "Pending Approvals", value: stats.pendingApprovals, href: "/approvals", color: "text-yellow-600" },
    { label: "Online Agents", value: stats.onlineAgents, href: "/agents", color: "text-purple-600" },
  ];

  return (
    <div className="space-y-8">
      {/* Stat cards */}
      <div className="grid grid-cols-1 gap-6 sm:grid-cols-2 lg:grid-cols-5">
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
      {metrics && (
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Counters */}
          {metrics.counters && Object.keys(metrics.counters).length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <h2 className="mb-4 text-base font-semibold text-gray-900">Counters</h2>
              <div className="grid grid-cols-2 gap-3">
                {Object.entries(metrics.counters).map(([key, val]) => (
                  <div key={key} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                    <p className="text-[10px] text-gray-500 break-all">{key}</p>
                    <p className="mt-1 text-sm font-bold text-gray-800">
                      {typeof val === "number" ? val.toLocaleString() : typeof val === "object" && val !== null ? Object.entries(val).map(([k, v]) => `${k}: ${v}`).join(", ") : String(val)}
                    </p>
                  </div>
                ))}
              </div>
            </div>
          )}
          {/* Histograms */}
          {metrics.histograms && Object.keys(metrics.histograms).length > 0 && (
            <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
              <h2 className="mb-4 text-base font-semibold text-gray-900">Histograms</h2>
              <div className="space-y-3">
                {Object.entries(metrics.histograms).map(([key, h]) => {
                  const hist = h as { count: number; sum: number; min: number; max: number; avg: number };
                  return (
                    <div key={key} className="rounded-lg border border-gray-100 bg-gray-50 p-3">
                      <p className="text-[10px] text-gray-500 break-all mb-2">{key}</p>
                      <div className="grid grid-cols-5 gap-2 text-center">
                        {([["Count", hist.count, ""], ["Sum", hist.sum, "s"], ["Min", hist.min, "s"], ["Max", hist.max, "s"], ["Avg", hist.avg, "s"]] as const).map(([label, value, unit]) => (
                          <div key={label}>
                            <p className="text-[9px] text-gray-400">{label}</p>
                            <p className="text-xs font-semibold text-gray-700">{typeof value === "number" ? value.toFixed(2) : value}{unit}</p>
                          </div>
                        ))}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
        </div>
      )}

      {/* Run status breakdown */}
      {stats.runsByStatus && Object.keys(stats.runsByStatus).length > 0 && (
        <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
          <h2 className="mb-4 text-base font-semibold text-gray-900">Runs by Status</h2>
          <div className="flex flex-wrap gap-3">
            {Object.entries(stats.runsByStatus).map(([status, count]) => (
              <Link key={status} href={`/runs?status=${status}`} className="flex items-center gap-2 rounded-lg border border-gray-100 bg-gray-50 px-4 py-2 transition hover:shadow-sm">
                <StatusBadge status={status} />
                <span className="text-sm font-bold text-gray-800">{count}</span>
              </Link>
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
