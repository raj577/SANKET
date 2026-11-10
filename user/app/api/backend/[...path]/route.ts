import { NextRequest, NextResponse } from "next/server";

import {
  applySession,
  backendRequest,
  clearSession,
  readSession,
  refreshSessionOnce,
  sameOrigin
} from "@/lib/server/session";

type RouteContext = { params: Promise<{ path: string[] }> };

const UNSAFE_METHODS = new Set(["POST", "PUT", "PATCH", "DELETE"]);
const MAX_BODY_BYTES = 30 * 1024 * 1024;

async function forward(upstream: Response): Promise<NextResponse> {
  const body = await upstream.arrayBuffer();
  const headers = new Headers();
  for (const name of ["content-type", "content-disposition", "x-checksum-sha256"]) {
    const value = upstream.headers.get(name);
    if (value) headers.set(name, value);
  }
  return new NextResponse(body, { status: upstream.status, headers });
}

async function proxy(request: NextRequest, context: RouteContext): Promise<NextResponse> {
  if (UNSAFE_METHODS.has(request.method) && !sameOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }

  const { path } = await context.params;
  const target = "/" + (path || []).map((part) => encodeURIComponent(part)).join("/") + request.nextUrl.search;

  const headers = new Headers();
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("Content-Type", contentType);
  const accept = request.headers.get("accept");
  if (accept) headers.set("Accept", accept);

  const declaredLength = Number(request.headers.get("content-length") || 0);
  if (declaredLength > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: "Request body is too large" }, { status: 413 });
  }
  const rawBody =
    request.method === "GET" || request.method === "HEAD"
      ? null
      : Buffer.from(await request.arrayBuffer());
  if (rawBody && rawBody.byteLength > MAX_BODY_BYTES) {
    return NextResponse.json({ detail: "Request body is too large" }, { status: 413 });
  }
  const body = rawBody && rawBody.byteLength > 0 ? rawBody : undefined;

  const { access, refresh } = await readSession();
  let upstream = await backendRequest(target, {
    method: request.method,
    body,
    access,
    headers
  });

  let refreshed = null;
  if (upstream.status === 401 && refresh) {
    refreshed = await refreshSessionOnce(refresh);
    if (refreshed) {
      upstream = await backendRequest(target, {
        method: request.method,
        body,
        access: refreshed.access_token,
        headers
      });
    }
  }

  const response = await forward(upstream);
  if (refreshed) return applySession(response, refreshed);
  if (upstream.status === 401) return clearSession(response);
  return response;
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
export const DELETE = proxy;
