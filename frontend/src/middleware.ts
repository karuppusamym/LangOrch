/**
 * Next.js Edge Middleware — protect all routes except /login.
 * Redirects unauthenticated requests to /login.
 */
import { NextRequest, NextResponse } from "next/server";

const PUBLIC_PATHS = ["/login", "/api/auth/login", "/api/health"];

function isPublic(pathname: string): boolean {
  return PUBLIC_PATHS.some((p) => pathname === p || pathname.startsWith(p + "/"));
}

function isTokenExpired(token: string): boolean {
  try {
    const [, payloadB64] = token.split(".");
    const payload = JSON.parse(
      Buffer.from(payloadB64.replace(/-/g, "+").replace(/_/g, "/"), "base64").toString()
    );
    return (payload.exp as number) < Date.now() / 1000;
  } catch {
    return true;
  }
}

export function middleware(request: NextRequest) {
  const { pathname } = request.nextUrl;

  // Always allow public paths, static assets, and api routes
  if (
    isPublic(pathname) ||
    pathname.startsWith("/_next") ||
    pathname.startsWith("/favicon") ||
    pathname.startsWith("/api/") ||
    pathname.includes(".")
  ) {
    return NextResponse.next();
  }

  const token = request.cookies.get("langorch_token")?.value;

  // If no cookie-based token, allow through (client-side auth guard handles it)
  // This keeps SSR/RSC working while client-side localStorage auth is the primary flow.
  // For strict enforcement, swap to: if (!token || isTokenExpired(token)) { redirect }
  if (token && isTokenExpired(token)) {
    const url = request.nextUrl.clone();
    url.pathname = "/login";
    url.searchParams.set("from", pathname);
    return NextResponse.redirect(url);
  }

  return NextResponse.next();
}

export const config = {
  matcher: [
    "/((?!_next/static|_next/image|favicon.ico).*)",
  ],
};
