"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { listApprovals, listRuns } from "@/lib/api";
import { getUser, logout, ROLE_COLORS } from "@/lib/auth";

function NavIcon({ d, d2 }: { d: string; d2?: string }) {
  return (
    <svg className="w-4 h-4 shrink-0" fill="none" stroke="currentColor" strokeWidth={1.75} viewBox="0 0 24 24">
      <path strokeLinecap="round" strokeLinejoin="round" d={d} />
      {d2 && <path strokeLinecap="round" strokeLinejoin="round" d={d2} />}
    </svg>
  );
}

const NAV_SECTIONS: { title?: string; items: { href: string; label: string; d: string; d2?: string; badge?: "failed" | "pending" }[] }[] = [
  {
    title: "Overview",
    items: [
      { href: "/", label: "Dashboard", d: "M3 12l2-2m0 0l7-7 7 7M5 10v10a1 1 0 001 1h3m10-11l2 2m-2-2v10a1 1 0 01-1 1h-3m-6 0a1 1 0 001-1v-4a1 1 0 011-1h2a1 1 0 011 1v4a1 1 0 001 1m-6 0h6" },
      { href: "/projects", label: "Projects", d: "M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v9a2 2 0 01-2 2H5a2 2 0 01-2-2V7z" },
    ],
  },
  {
    title: "Automation",
    items: [
      { href: "/procedures", label: "Procedures", d: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" },
      { href: "/builder", label: "Graph Viewer", d: "M4 5a1 1 0 011-1h14a1 1 0 011 1v2a1 1 0 01-1 1H5a1 1 0 01-1-1V5zM4 13a1 1 0 011-1h6a1 1 0 011 1v6a1 1 0 01-1 1H5a1 1 0 01-1-1v-6zM16 13a1 1 0 011-1h2a1 1 0 011 1v6a1 1 0 01-1 1h-2a1 1 0 01-1-1v-6z" },
      { href: "/runs", label: "Runs", d: "M14.752 11.168l-3.197-2.132A1 1 0 0010 9.87v4.263a1 1 0 001.555.832l3.197-2.132a1 1 0 000-1.664z", d2: "M21 12a9 9 0 11-18 0 9 9 0 0118 0z", badge: "failed" },
      { href: "/approvals", label: "Approvals", d: "M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z", badge: "pending" },
      { href: "/triggers", label: "Triggers", d: "M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" },
    ],
  },
  {
    title: "Infrastructure",
    items: [
      { href: "/health", label: "System Health", d: "M9 12l2 2 4-4M7.835 4.697a3.42 3.42 0 001.946-.806 3.42 3.42 0 014.438 0 3.42 3.42 0 001.946.806 3.42 3.42 0 013.138 3.138 3.42 3.42 0 00.806 1.946 3.42 3.42 0 010 4.438 3.42 3.42 0 00-.806 1.946 3.42 3.42 0 01-3.138 3.138 3.42 3.42 0 00-1.946.806 3.42 3.42 0 01-4.438 0 3.42 3.42 0 00-1.946-.806 3.42 3.42 0 01-3.138-3.138 3.42 3.42 0 00-.806-1.946 3.42 3.42 0 010-4.438 3.42 3.42 0 00.806-1.946 3.42 3.42 0 013.138-3.138z" },
      { href: "/agents", label: "Agents", d: "M17 20h5v-2a3 3 0 00-5.356-1.857M17 20H7m10 0v-2c0-.656-.126-1.283-.356-1.857M7 20H2v-2a3 3 0 015.356-1.857M7 20v-2c0-.656.126-1.283.356-1.857m0 0a5.002 5.002 0 019.288 0M15 7a3 3 0 11-6 0 3 3 0 016 0z" },
      { href: "/leases", label: "Resources", d: "M12 15v2m-6 4h12a2 2 0 002-2v-6a2 2 0 00-2-2H6a2 2 0 00-2 2v6a2 2 0 002 2zm10-10V7a4 4 0 00-8 0v4h8z" },
      { href: "/secrets", label: "Secrets", d: "M15 7a2 2 0 012 2m4 0a6 6 0 01-7.743 5.743L11 17H9v2H7v2H4a1 1 0 01-1-1v-2.586a1 1 0 01.293-.707l5.964-5.964A6 6 0 1121 9z" },
    ],
  },
  {
    title: "Platform",
    items: [
      { href: "/audit", label: "Audit Logs", d: "M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-3 7h3m-3 4h3m-6-4h.01M9 16h.01" },
      { href: "/users", label: "Users", d: "M12 4.354a4 4 0 110 5.292M15 21H3v-1a6 6 0 0112 0v1zm0 0h6v-1a6 6 0 00-9-5.197M13 7a4 4 0 11-8 0 4 4 0 018 0z" },
      { href: "/settings", label: "Settings", d: "M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z", d2: "M15 12a3 3 0 11-6 0 3 3 0 016 0z" },
    ],
  },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [mounted, setMounted] = useState(false);
  const [pendingCount, setPendingCount] = useState(0);
  const [failedCount, setFailedCount] = useState(0);
  const [user, setUser] = useState(() => {
    if (typeof window === "undefined") return null;
    return getUser();
  });
  const [showUserMenu, setShowUserMenu] = useState(false);

  useEffect(() => {
    setMounted(true);
    setUser(getUser());
  }, []);

  useEffect(() => {
    async function refresh() {
      try {
        const [approvals, runs] = await Promise.all([listApprovals(), listRuns({ limit: 50 })]);
        setPendingCount(approvals.filter((a) => a.status === "pending").length);
        setFailedCount(runs.filter((r) => r.status === "failed").length);
      } catch { /* noop */ }
    }
    refresh();
    const id = setInterval(refresh, 30_000);
    return () => clearInterval(id);
  }, []);

  const badge = (type?: "failed" | "pending") => {
    const count = type === "failed" ? failedCount : type === "pending" ? pendingCount : 0;
    if (!count) return null;
    return (
      <span className="ml-auto flex h-5 min-w-5 items-center justify-center rounded-full bg-red-600 px-1.5 text-[10px] font-bold text-white">
        {count}
      </span>
    );
  };

  const initials = user?.full_name
    ? user.full_name.split(" ").map((w) => w[0]).join("").toUpperCase().slice(0, 2)
    : (user?.identity ?? "U").slice(0, 2).toUpperCase();

  const roleColor = ROLE_COLORS[user?.role ?? "viewer"] ?? ROLE_COLORS.viewer;

  return (
    <aside
      className="fixed inset-y-0 left-0 z-30 flex flex-col bg-white dark:bg-neutral-900 border-r border-neutral-200 dark:border-neutral-800"
      style={{ width: "var(--sidebar-width)" }}
    >
      {/* Logo */}
      <div className="flex h-[var(--header-height)] shrink-0 items-center gap-2 px-6 border-b border-neutral-200 dark:border-neutral-800">
        <svg className="w-6 h-6 text-blue-600" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
          <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
        </svg>
        <span className="font-bold text-lg text-neutral-900 dark:text-neutral-100">LangOrch</span>
      </div>

      {/* Nav */}
      <nav className="flex-1 overflow-y-auto py-3 space-y-1">
        {NAV_SECTIONS.map((section) => (
          <div key={section.title ?? "default"}>
            {section.title && (
              <p className="px-6 pt-3 pb-1 text-[10px] font-semibold uppercase tracking-widest text-neutral-400 dark:text-neutral-600 select-none">
                {section.title}
              </p>
            )}
            {section.items.map((item) => {
              const isActive = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center gap-3 mx-2 px-4 py-2 rounded-lg text-sm transition-colors ${isActive
                    ? "bg-blue-50 dark:bg-blue-950/50 text-blue-600 dark:text-blue-400 font-medium"
                    : "text-neutral-600 dark:text-neutral-400 hover:bg-neutral-50 dark:hover:bg-neutral-800 hover:text-neutral-900 dark:hover:text-neutral-200"
                    }`}
                >
                  <NavIcon d={item.d} d2={item.d2} />
                  <span className="flex-1">{item.label}</span>
                  {badge(item.badge)}
                </Link>
              );
            })}
          </div>
        ))}
      </nav>

      {/* User profile */}
      <div className="shrink-0 p-3 border-t border-neutral-200 dark:border-neutral-800 relative">
        <button
          onClick={() => setShowUserMenu((v) => !v)}
          className="flex w-full items-center gap-3 rounded-lg p-2 hover:bg-neutral-100 dark:hover:bg-neutral-800 transition-colors"
        >
          <div className="h-8 w-8 rounded-full bg-blue-600 flex items-center justify-center text-white text-xs font-bold shrink-0">
            {mounted ? initials : "U"}
          </div>
          <div className="flex-1 min-w-0 text-left">
            <div className="text-sm font-medium text-neutral-900 dark:text-neutral-100 truncate">
              {mounted ? (user?.full_name ?? user?.identity ?? "User") : "User"}
            </div>
            <div className={`text-xs font-medium px-1.5 py-0.5 rounded-full inline-block mt-0.5 ${mounted ? roleColor : ROLE_COLORS.viewer}`}>
              {mounted ? (user?.role ?? "viewer") : "viewer"}
            </div>
          </div>
          <svg className="w-4 h-4 text-neutral-400 shrink-0" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </button>

        {showUserMenu && (
          <div className="absolute bottom-full left-3 right-3 mb-1 rounded-xl border border-neutral-200 dark:border-neutral-700 bg-white dark:bg-neutral-800 shadow-lg py-1 z-50">
            <Link href="/settings" className="flex items-center gap-2 px-4 py-2 text-sm text-neutral-700 dark:text-neutral-300 hover:bg-neutral-50 dark:hover:bg-neutral-700 transition-colors">
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M16 7a4 4 0 11-8 0 4 4 0 018 0zM12 14a7 7 0 00-7 7h14a7 7 0 00-7-7z" /></svg>
              Profile
            </Link>
            <button
              onClick={() => logout()}
              className="flex w-full items-center gap-2 px-4 py-2 text-sm text-red-600 dark:text-red-400 hover:bg-red-50 dark:hover:bg-red-950/30 transition-colors"
            >
              <svg className="w-4 h-4" fill="none" stroke="currentColor" strokeWidth={2} viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" d="M17 16l4-4m0 0l-4-4m4 4H7m6 4v1a3 3 0 01-3 3H6a3 3 0 01-3-3V7a3 3 0 013-3h4a3 3 0 013 3v1" /></svg>
              Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );
}
