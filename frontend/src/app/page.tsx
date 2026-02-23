"use client";

import { useEffect, useState, useRef } from "react";
import Link from "next/link";
import {
  AreaChart, Area, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer,
} from "recharts";
import { listProcedures, listRuns, listApprovals, listAgents, listProjects } from "@/lib/api";
import { StatusBadge } from "@/components/shared/StatusBadge";
import type { Run, AgentInstance } from "@/lib/types";

//  inline icon helper 
const Icon = ({ path, path2, cls = "" }: { path: string; path2?: string; cls?: string }) => (
  <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.75"
    strokeLinecap="round" strokeLinejoin="round" className={`w-5 h-5 ${cls}`}>
    <path d={path} />
    {path2 && <path d={path2} />}
  </svg>
);

// Build 24-hour chart data from a list of runs
function buildChartData(runs: Run[]) {
  // bucket runs by hour relative to now
  const now = Date.now();
  const hours: { time: string; runs: number }[] = [];
  for (let i = 23; i >= 0; i--) {
    const h = new Date(now - i * 3600_000);
    hours.push({ time: `${h.getHours().toString().padStart(2, "0")}:00`, runs: 0 });
  }
  for (const r of runs) {
    const ts = new Date(r.created_at).getTime();
    const diffH = Math.floor((now - ts) / 3600_000);
    if (diffH >= 0 && diffH < 24) {
      hours[23 - diffH].runs++;
    }
  }
  return hours;
}

interface Stats {
  totalRuns: number;
  activeRuns: number;
  failedRuns: number;
  pendingApprovals: number;
  recentRuns: Run[];
  agents: AgentInstance[];
  chartData: { time: string; runs: number }[];
}

function SkeletonDash() {
  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {[...Array(4)].map((_, i) => <div key={i} className="h-28 rounded-xl bg-neutral-100 dark:bg-neutral-800 animate-pulse" />)}
      </div>
      <div className="h-64 rounded-xl bg-neutral-100 dark:bg-neutral-800 animate-pulse" />
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">
        {[...Array(2)].map((_, i) => <div key={i} className="h-48 rounded-xl bg-neutral-100 dark:bg-neutral-800 animate-pulse" />)}
      </div>
    </div>
  );
}

export default function DashboardPage() {
  const [stats, setStats] = useState<Stats | null>(null);
  const [loading, setLoading] = useState(true);
  const timerRef = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = async () => {
    try {
      const [procs, allRuns, approvals, agents, _projects] = await Promise.all([
        listProcedures(),
        listRuns({ limit: 100 }),
        listApprovals(),
        listAgents(),
        listProjects(),
      ]);
      setStats({
        totalRuns: allRuns.length,
        activeRuns: allRuns.filter((r) => r.status === "running").length,
        failedRuns: allRuns.filter((r) => r.status === "failed").length,
        pendingApprovals: approvals.filter((a) => a.status === "pending").length,
        recentRuns: allRuns.slice(0, 8),
        agents,
        chartData: buildChartData(allRuns),
      });
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

  if (loading) return <SkeletonDash />;
  if (!stats) return (
    <div className="flex h-64 flex-col items-center justify-center gap-3">
      <Icon path="M12 9v4M12 17h.01M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z" cls="w-10 h-10 text-red-400" />
      <p className="text-sm text-neutral-500 dark:text-neutral-400">Failed to load dashboard data.</p>
      <button onClick={load} className="px-4 py-2 rounded-lg bg-blue-600 text-white text-sm font-medium hover:bg-blue-700 transition-colors">Retry</button>
    </div>
  );

  const onlineAgents = stats.agents.filter((a) => a.status === "online");
  const totalAgents = stats.agents.length || 1;
  const capacityPct = Math.round((onlineAgents.length / totalAgents) * 100);

  const agentDots = ["bg-green-500", "bg-blue-500", "bg-amber-500", "bg-purple-500", "bg-red-500"];

  return (
    <div className="space-y-6 animate-fade-in">

      {/* Page header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-neutral-900 dark:text-neutral-100">Dashboard</h1>
          <p className="mt-0.5 text-sm text-neutral-500 dark:text-neutral-400">Welcome back, Admin User</p>
        </div>
        <button onClick={load}
          className="flex items-center gap-2 px-3 py-2 rounded-lg border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 text-sm text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors">
          <Icon path="M4 4v5h.582M20 20v-5h-.581M5.077 9A8.004 8.004 0 0112 4c2.618 0 4.952 1.26 6.41 3.2M18.923 15A8.004 8.004 0 0112 20a8 8 0 01-6.41-3.2" cls="w-3.5 h-3.5" />
          Refresh
        </button>
      </div>

      {/* 4 KPI cards */}
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        {/* Total Runs */}
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm text-neutral-500 dark:text-neutral-400">Total Runs</p>
            <Icon path="M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z" path2="M21 12a9 9 0 11-18 0 9 9 0 0118 0z" cls="w-5 h-5 text-neutral-400" />
          </div>
          <p className="text-3xl font-bold text-neutral-900 dark:text-neutral-100">{stats.totalRuns}</p>
          <p className="mt-1 text-xs text-neutral-400 dark:text-neutral-500">All time</p>
        </div>

        {/* Active Runs */}
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm text-neutral-500 dark:text-neutral-400">Active Runs</p>
            <Icon path="M22 12h-4l-3 9L9 3l-3 9H2" cls="w-5 h-5 text-blue-500" />
          </div>
          <p className="text-3xl font-bold text-blue-600 dark:text-blue-400">{stats.activeRuns}</p>
          <p className="mt-1 text-xs text-neutral-400 dark:text-neutral-500">Currently executing</p>
        </div>

        {/* Failed Runs */}
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm text-neutral-500 dark:text-neutral-400">Failed Runs</p>
            <Icon path="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" cls="w-5 h-5 text-red-500" />
          </div>
          <p className="text-3xl font-bold text-red-600 dark:text-red-400">{stats.failedRuns}</p>
          <Link href="/runs?status=failed" className="mt-1 text-xs text-red-500 hover:underline">Review failures </Link>
        </div>

        {/* Pending Approvals */}
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
          <div className="flex items-center justify-between mb-3">
            <p className="text-sm text-neutral-500 dark:text-neutral-400">Pending Approvals</p>
            <Icon path="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" cls="w-5 h-5 text-amber-500" />
          </div>
          <p className="text-3xl font-bold text-amber-600 dark:text-amber-400">{stats.pendingApprovals}</p>
          <Link href="/approvals" className="mt-1 text-xs text-amber-500 hover:underline">Review approvals </Link>
        </div>
      </div>

      {/* Charts row */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-3">

        {/* Area chart */}
        <div className="lg:col-span-2 rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100 mb-4">Run Activity (Last 24 Hours)</h2>
          <ResponsiveContainer width="100%" height={200}>
            <AreaChart data={stats.chartData} margin={{ top: 4, right: 4, bottom: 0, left: -20 }}>
              <defs>
                <linearGradient id="runsGrad" x1="0" y1="0" x2="0" y2="1">
                  <stop offset="5%" stopColor="#2563eb" stopOpacity={0.25} />
                  <stop offset="95%" stopColor="#2563eb" stopOpacity={0} />
                </linearGradient>
              </defs>
              <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
              <XAxis dataKey="time" tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} />
              <YAxis tick={{ fontSize: 11, fill: "#9ca3af" }} tickLine={false} axisLine={false} allowDecimals={false} />
              <Tooltip contentStyle={{ fontSize: 12, borderRadius: 8, border: "1px solid #e5e7eb" }} />
              <Area type="monotone" dataKey="runs" stroke="#2563eb" strokeWidth={2} fill="url(#runsGrad)" />
            </AreaChart>
          </ResponsiveContainer>
        </div>

        {/* Agent Capacity */}
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5 flex flex-col">
          <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100 mb-1">Agent Capacity</h2>
          <p className="text-xs text-neutral-400 dark:text-neutral-500 mb-4">{onlineAgents.length} of {totalAgents} online</p>
          {/* Progress bar */}
          <div className="h-2 w-full rounded-full bg-neutral-100 dark:bg-neutral-700 mb-4">
            <div
              className="h-2 rounded-full bg-blue-600 transition-all duration-500"
              style={{ width: `${capacityPct}%` }}
            />
          </div>
          {/* Agent list */}
          <ul className="flex-1 space-y-2 overflow-y-auto">
            {stats.agents.slice(0, 5).map((agent, i) => (
              <li key={agent.agent_id} className="flex items-center gap-2.5">
                <span className={`h-2 w-2 rounded-full shrink-0 ${agentDots[i % agentDots.length]}`} />
                <span className="flex-1 text-xs text-neutral-700 dark:text-neutral-300 truncate">{agent.agent_id.slice(0, 16)}</span>
                <span className={`text-xs font-medium ${agent.status === "online" ? "text-green-600" : "text-neutral-400"}`}>
                  {agent.status}
                </span>
              </li>
            ))}
            {stats.agents.length === 0 && (
              <li className="text-xs text-neutral-400 py-2">No agents registered</li>
            )}
          </ul>
          <Link href="/agents" className="mt-4 block text-center text-xs font-medium text-blue-600 hover:underline">
            View All Agents 
          </Link>
        </div>
      </div>

      {/* Recent Activity */}
      <div className="grid grid-cols-1 gap-4 lg:grid-cols-2">

        {/* Recent Runs */}
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Recent Runs</h2>
            <Link href="/runs" className="text-xs text-blue-600 hover:underline">View all </Link>
          </div>
          {stats.recentRuns.length === 0 ? (
            <p className="text-sm text-neutral-400 py-4 text-center">No runs yet</p>
          ) : (
            <ul className="space-y-3">
              {stats.recentRuns.map((run) => (
                <li key={run.run_id} className="flex items-center gap-3">
                  <div className="flex-1 min-w-0">
                    <Link href={`/runs/${run.run_id}`} className="text-sm font-medium text-neutral-900 dark:text-neutral-100 hover:underline truncate block">
                      {run.procedure_id}
                    </Link>
                    <p className="text-xs text-neutral-400 tabular-nums">
                      {new Date(run.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                    </p>
                  </div>
                  <StatusBadge status={run.status} />
                </li>
              ))}
            </ul>
          )}
        </div>

        {/* Recent Events (derived from runs) */}
        <div className="rounded-xl border border-neutral-200 dark:border-neutral-800 bg-white dark:bg-neutral-900 p-5">
          <div className="flex items-center justify-between mb-4">
            <h2 className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Recent Events</h2>
          </div>
          {stats.recentRuns.length === 0 ? (
            <p className="text-sm text-neutral-400 py-4 text-center">No recent events</p>
          ) : (
            <ul className="space-y-3">
              {stats.recentRuns.slice(0, 6).map((run, i) => {
                const colors = ["bg-blue-100 text-blue-600", "bg-amber-100 text-amber-600", "bg-green-100 text-green-600", "bg-purple-100 text-purple-600"];
                const cls = colors[i % colors.length];
                const verbs: Record<string, string> = { completed: "completed", failed: "failed", running: "started", pending: "queued" };
                const verb = verbs[run.status] ?? "updated";
                return (
                  <li key={run.run_id} className="flex items-start gap-3">
                    <span className={`mt-0.5 h-7 w-7 rounded-full flex items-center justify-center text-xs font-bold shrink-0 ${cls}`}>
                      {run.procedure_id.charAt(0).toUpperCase()}
                    </span>
                    <div className="flex-1 min-w-0">
                      <p className="text-sm text-neutral-700 dark:text-neutral-300">
                        Run <span className="font-medium">{run.run_id.slice(0, 8)}</span> {verb}
                      </p>
                      <p className="text-xs text-neutral-400">
                        {new Date(run.created_at).toLocaleString(undefined, { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" })}
                      </p>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </div>
  );
}
