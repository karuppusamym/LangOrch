"use client";

import { useEffect, useRef, useState } from "react";
import { usePathname } from "next/navigation";
import Link from "next/link";
import { useTheme } from "@/components/ThemeProvider";
import { listApprovals, listRuns } from "@/lib/api";

//  tiny icon helpers 
const SearchIcon = () => (
  <svg className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-neutral-400 pointer-events-none"
    fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <circle cx="11" cy="11" r="8" />
    <path d="M21 21l-4.35-4.35" strokeLinecap="round" />
  </svg>
);
const SunIcon = () => (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <circle cx="12" cy="12" r="5" />
    <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
  </svg>
);
const MoonIcon = () => (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
  </svg>
);
const BellIcon = () => (
  <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
    <path strokeLinecap="round" strokeLinejoin="round" d="M15 17h5l-1.405-1.405A2.032 2.032 0 0118 14.158V11a6.002 6.002 0 00-4-5.659V5a2 2 0 10-4 0v.341C7.67 6.165 6 8.388 6 11v3.159c0 .538-.214 1.055-.595 1.436L4 17h5m6 0v1a3 3 0 11-6 0v-1m6 0H9" />
  </svg>
);

interface Notification { id: string; title: string; desc: string; href: string; type: "warning" | "info" }

export default function Header() {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();
  const [bellOpen, setBellOpen] = useState(false);
  const [notifications, setNotifications] = useState<Notification[]>([]);
  const bellRef = useRef<HTMLDivElement>(null);

  const segment = pathname.split("/").filter(Boolean)[0] ?? "";
  const pageLabel = segment
    ? segment.charAt(0).toUpperCase() + segment.slice(1)
    : "Dashboard";

  useEffect(() => {
    async function load() {
      try {
        const [approvals, runs] = await Promise.all([listApprovals(), listRuns({ limit: 50 })]);
        const pending = approvals.filter((a) => a.status === "pending").length;
        const failed = runs.filter((r) => r.status === "failed").length;
        const notifs: Notification[] = [];
        if (pending > 0)
          notifs.push({ id: "approvals", title: "Pending Approvals", desc: `${pending} approval${pending > 1 ? "s" : ""} awaiting review`, href: "/approvals", type: "warning" });
        if (failed > 0)
          notifs.push({ id: "failed", title: "Failed Runs", desc: `${failed} run${failed > 1 ? "s" : ""} ended with errors`, href: "/runs?status=failed", type: "info" });
        setNotifications(notifs);
      } catch { /* noop */ }
    }
    load();
    const id = setInterval(load, 30_000);
    return () => clearInterval(id);
  }, []);

  useEffect(() => {
    function handler(e: MouseEvent) {
      if (bellRef.current && !bellRef.current.contains(e.target as Node)) setBellOpen(false);
    }
    document.addEventListener("mousedown", handler);
    return () => document.removeEventListener("mousedown", handler);
  }, []);

  return (
    <header className="sticky top-0 z-20 flex h-[var(--header-height)] items-center gap-4 px-6 bg-white dark:bg-neutral-900 border-b border-neutral-200 dark:border-neutral-800">

      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-sm shrink-0">
        <Link href="/" className="text-neutral-500 dark:text-neutral-400 hover:text-neutral-700 dark:hover:text-neutral-200 transition-colors">
          LangOrch
        </Link>
        {pathname !== "/" && (
          <>
            <svg className="h-3.5 w-3.5 text-neutral-300 dark:text-neutral-600" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 5l7 7-7 7" />
            </svg>
            <span className="font-semibold text-neutral-900 dark:text-neutral-100">{pageLabel}</span>
          </>
        )}
      </div>

      {/* Search bar */}
      <div className="relative flex-1 max-w-lg mx-auto">
        <SearchIcon />
        <input
          type="text"
          placeholder="Search procedures, runs, agents..."
          className="w-full rounded-lg border border-neutral-200 dark:border-neutral-700 bg-neutral-50 dark:bg-neutral-800 pl-9 pr-4 py-2 text-sm text-neutral-900 dark:text-neutral-100 placeholder:text-neutral-400 focus:outline-none focus:ring-2 focus:ring-blue-500/30 focus:border-blue-400 transition-all"
        />
      </div>

      {/* Right actions */}
      <div className="flex items-center gap-1 shrink-0">
        <button
          onClick={toggle}
          className="p-2 rounded-lg text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? <SunIcon /> : <MoonIcon />}
        </button>

        <div ref={bellRef} className="relative">
          <button
            onClick={() => setBellOpen((o) => !o)}
            className="relative p-2 rounded-lg text-neutral-500 dark:text-neutral-400 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
            title="Notifications"
          >
            <BellIcon />
            {notifications.length > 0 && (
              <span className="absolute top-1.5 right-1.5 h-2 w-2 rounded-full bg-red-500" />
            )}
          </button>

          {bellOpen && (
            <div className="absolute right-0 top-full mt-2 w-80 rounded-xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-900 shadow-xl z-50">
              <div className="flex items-center justify-between px-4 py-3 border-b border-neutral-100 dark:border-neutral-800">
                <span className="text-sm font-semibold text-neutral-900 dark:text-neutral-100">Notifications</span>
                {notifications.length > 0 && (
                  <span className="text-xs font-medium text-white bg-red-500 rounded-full px-2 py-0.5">{notifications.length}</span>
                )}
              </div>
              {notifications.length === 0 ? (
                <div className="flex flex-col items-center gap-2 py-8 text-center">
                  <p className="text-sm text-neutral-500">All clear  no notifications</p>
                </div>
              ) : (
                <ul>
                  {notifications.map((n) => (
                    <li key={n.id}>
                      <Link
                        href={n.href}
                        onClick={() => setBellOpen(false)}
                        className="flex items-start gap-3 px-4 py-3 hover:bg-neutral-50 dark:hover:bg-neutral-800 transition-colors"
                      >
                        <span className={`mt-0.5 h-2 w-2 rounded-full shrink-0 ${n.type === "warning" ? "bg-amber-500" : "bg-blue-500"}`} />
                        <div className="min-w-0">
                          <p className="text-sm font-medium text-neutral-900 dark:text-neutral-100">{n.title}</p>
                          <p className="text-xs text-neutral-500 dark:text-neutral-400 mt-0.5">{n.desc}</p>
                        </div>
                      </Link>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </div>
    </header>
  );
}
