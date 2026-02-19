"use client";

import { usePathname } from "next/navigation";
import { useTheme } from "@/components/ThemeProvider";

const TITLES: Record<string, string> = {
  "/": "Dashboard",
  "/procedures": "Procedures",
  "/runs": "Runs",
  "/approvals": "Approvals",
  "/agents": "Agents",
};

export default function Header() {
  const pathname = usePathname();
  const { theme, toggle } = useTheme();

  // Find matching title (longest prefix match)
  const title =
    Object.entries(TITLES)
      .filter(([p]) => pathname.startsWith(p))
      .sort((a, b) => b[0].length - a[0].length)[0]?.[1] ?? "LangOrch";

  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-gray-200 bg-white px-8 dark:border-gray-700 dark:bg-gray-900">
      <h1 className="text-lg font-semibold text-gray-900 dark:text-gray-100">{title}</h1>
      <div className="flex items-center gap-4">
        <button
          onClick={toggle}
          className="rounded-lg border border-gray-200 p-2 text-gray-500 hover:bg-gray-100 dark:border-gray-600 dark:text-gray-400 dark:hover:bg-gray-800"
          title={theme === "dark" ? "Switch to light mode" : "Switch to dark mode"}
        >
          {theme === "dark" ? (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <circle cx="12" cy="12" r="5" />
              <path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42" />
            </svg>
          ) : (
            <svg className="h-4 w-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" />
            </svg>
          )}
        </button>
        <span className="text-sm text-gray-500 dark:text-gray-400">Orchestrator</span>
      </div>
    </header>
  );
}
