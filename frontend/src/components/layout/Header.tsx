"use client";

import { usePathname } from "next/navigation";

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/procedures": "Procedures",
  "/runs": "Runs",
  "/approvals": "Approvals",
  "/agents": "Agents",
};

export default function Header() {
  const pathname = usePathname();

  // Find matching title (longest prefix match)
  const title =
    Object.entries(TITLES)
      .filter(([p]) => pathname.startsWith(p))
      .sort((a, b) => b[0].length - a[0].length)[0]?.[1] ?? "LangOrch";

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-gray-200 bg-white px-8">
      <h1 className="text-lg font-semibold text-gray-900">{title}</h1>
      <div className="flex items-center gap-4">
        <span className="text-sm text-gray-500">Orchestrator</span>
      </div>
    </header>
  );
}
