"use client";

import { usePathname } from "next/navigation";
import { useEffect } from "react";
import Sidebar from "@/components/layout/Sidebar";
import Header from "@/components/layout/Header";
import { isAuthenticated } from "@/lib/auth";
import { useRouter } from "next/navigation";

const NO_SHELL_PATHS = ["/login"];

export default function ClientLayout({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const router = useRouter();
  const isShellless = NO_SHELL_PATHS.some((p) => pathname?.startsWith(p));

  // Client-side auth guard
  useEffect(() => {
    if (!isShellless && !isAuthenticated()) {
      router.replace(`/login?from=${encodeURIComponent(pathname ?? "/")}`);
    }
  }, [isShellless, pathname, router]);

  if (isShellless) {
    return <>{children}</>;
  }

  return (
    <>
      <Sidebar />
      <div
        className="flex min-h-screen flex-col"
        style={{ marginLeft: "var(--sidebar-width)" }}
      >
        <Header />
        <main className="flex-1 animate-fade-in">{children}</main>
      </div>
    </>
  );
}
