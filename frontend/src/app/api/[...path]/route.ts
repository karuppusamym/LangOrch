import type { NextRequest } from "next/server";

export const runtime = "nodejs";

type RouteContext = {
  params: Promise<{ path: string[] }>;
};

const DEV_FALLBACK_BACKEND_URLS = ["http://localhost:8000", "http://127.0.0.1:8000", "http://localhost:8010", "http://127.0.0.1:8010"];

function getBackendCandidates(): string[] {
  const configured = [process.env.BACKEND_URL, process.env.NEXT_PUBLIC_BACKEND_URL]
    .filter((value): value is string => Boolean(value))
    .map((value) => value.replace(/\/$/, ""));

  if (process.env.NODE_ENV !== "development") {
    return configured.length > 0 ? configured : ["http://localhost:8000"];
  }

  return [...new Set([...configured, ...DEV_FALLBACK_BACKEND_URLS])];
}

function buildUpstreamUrl(baseUrl: string, path: string[], search: string): string {
  const normalizedPath = path.map(encodeURIComponent).join("/");
  return `${baseUrl}/api/${normalizedPath}${search}`;
}

async function proxyRequest(request: NextRequest, path: string[]): Promise<Response> {
  const candidates = getBackendCandidates();
  const method = request.method.toUpperCase();
  const body = method === "GET" || method === "HEAD" ? undefined : await request.arrayBuffer();

  let lastError: unknown = null;

  for (const candidate of candidates) {
    const upstreamUrl = buildUpstreamUrl(candidate, path, request.nextUrl.search);

    try {
      const upstreamResponse = await fetch(upstreamUrl, {
        method,
        headers: filterRequestHeaders(request.headers),
        body,
        redirect: "manual",
        cache: "no-store",
      });

      return new Response(await upstreamResponse.arrayBuffer(), {
        status: upstreamResponse.status,
        statusText: upstreamResponse.statusText,
        headers: filterResponseHeaders(upstreamResponse.headers),
      });
    } catch (error) {
      lastError = error;
    }
  }

  const message = formatProxyError(lastError);
  return Response.json({ detail: message }, { status: 502 });
}

function formatProxyError(error: unknown): string {
  if (!(error instanceof Error)) {
    return "Unable to reach backend service";
  }

  const cause = error.cause;
  if (cause instanceof Error && cause.message) {
    return `${error.message}: ${cause.message}`;
  }

  return error.message || "Unable to reach backend service";
}

function filterRequestHeaders(headers: Headers): Headers {
  const nextHeaders = new Headers(headers);
  nextHeaders.delete("host");
  nextHeaders.delete("connection");
  nextHeaders.delete("content-length");
  nextHeaders.delete("expect");
  nextHeaders.delete("keep-alive");
  nextHeaders.delete("proxy-authenticate");
  nextHeaders.delete("proxy-authorization");
  nextHeaders.delete("te");
  nextHeaders.delete("trailer");
  nextHeaders.delete("upgrade");
  return nextHeaders;
}

function filterResponseHeaders(headers: Headers): Headers {
  const nextHeaders = new Headers(headers);
  nextHeaders.delete("content-length");
  nextHeaders.delete("content-encoding");
  nextHeaders.delete("transfer-encoding");
  return nextHeaders;
}

async function handle(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;
  return proxyRequest(request, path ?? []);
}

export async function GET(request: NextRequest, context: RouteContext): Promise<Response> {
  return handle(request, context);
}

export async function POST(request: NextRequest, context: RouteContext): Promise<Response> {
  return handle(request, context);
}

export async function PUT(request: NextRequest, context: RouteContext): Promise<Response> {
  return handle(request, context);
}

export async function PATCH(request: NextRequest, context: RouteContext): Promise<Response> {
  return handle(request, context);
}

export async function DELETE(request: NextRequest, context: RouteContext): Promise<Response> {
  return handle(request, context);
}

export async function OPTIONS(request: NextRequest, context: RouteContext): Promise<Response> {
  return handle(request, context);
}

export async function HEAD(request: NextRequest, context: RouteContext): Promise<Response> {
  return handle(request, context);
}