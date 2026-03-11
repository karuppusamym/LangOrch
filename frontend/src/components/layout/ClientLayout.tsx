"use client";

import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import { isAuthenticated } from "@/lib/auth";
import { useRouter } from "next/navigation";

const NO_SHELL_PATHS = ["/login"];
const SIDEBAR_COLLAPSED_STORAGE_KEY = "langorch.sidebar.collapsed";

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isShellless = NO_SHELL_PATHS.some((p) => pathname?.startsWith(p));
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);
  const [isMobile, setIsMobile] = useState(false);
  const [mobileSidebarOpen, setMobileSidebarOpen] = useState(false);

  // Client-side auth guard
  useEffect(() => {
    if (!isShellless && !isAuthenticated()) {
      router.replace(`/login?from=${encodeURIComponent(pathname ?? "/")}`);
    }
  }, [isShellless, pathname, router]);

  useEffect(() => {
    if (typeof window === "undefined") return;
    const stored = window.localStorage.getItem(SIDEBAR_COLLAPSED_STORAGE_KEY);
    setSidebarCollapsed(stored === "true");
  }, []);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const mediaQuery = window.matchMedia("(max-width: 1023px)");
    const applyViewportMode = (matches: boolean) => {
      setIsMobile(matches);
      if (!matches) {
        setMobileSidebarOpen(false);
      }
    };

    applyViewportMode(mediaQuery.matches);
    const handleChange = (event: MediaQueryListEvent) => applyViewportMode(event.matches);
    mediaQuery.addEventListener("change", handleChange);
    return () => mediaQuery.removeEventListener("change", handleChange);
  }, []);

  useEffect(() => {
    setMobileSidebarOpen(false);
  }, [pathname]);

  useEffect(() => {
    if (typeof document === "undefined") return;
    if (!(isMobile && mobileSidebarOpen)) return;

    const previousOverflow = document.body.style.overflow;
    document.body.style.overflow = "hidden";
    return () => {
      document.body.style.overflow = previousOverflow;
    };
  }, [isMobile, mobileSidebarOpen]);

  function toggleSidebar() {
    if (isMobile) {
      setMobileSidebarOpen((current) => !current);
      return;
    }

    setSidebarCollapsed((current) => {
      const next = !current;
      if (typeof window !== "undefined") {
        window.localStorage.setItem(SIDEBAR_COLLAPSED_STORAGE_KEY, String(next));
      }
      return next;
    });
  }

  if (isShellless) {
    return <>{children}</>;
  }

  return (
    <>
      <Sidebar
        collapsed={sidebarCollapsed}
        isMobile={isMobile}
        isOpen={mobileSidebarOpen}
        onClose={() => setMobileSidebarOpen(false)}
        onToggleCollapse={toggleSidebar}
      />
      {isMobile && mobileSidebarOpen ? (
        <button
          type="button"
          aria-label="Close navigation menu"
          onClick={() => setMobileSidebarOpen(false)}
          className="fixed inset-0 z-20 bg-neutral-950/30 backdrop-blur-[1px]"
        />
      ) : null}
      <div
        className={`flex min-h-screen flex-col transition-[margin] duration-200 ${isMobile ? "ml-0" : sidebarCollapsed ? "ml-20" : "ml-64"}`}
      >
        <Header
          isMobile={isMobile}
          sidebarCollapsed={sidebarCollapsed}
          sidebarOpen={mobileSidebarOpen}
          onToggleSidebar={toggleSidebar}
        />
        <main className="flex-1 animate-fade-in">{children}</main>
      </div>
    </>
  );
}
