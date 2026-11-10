import { NextRequest, NextResponse } from "next/server";

import { applySession, backendRequest, loginBackend, sameOrigin } from "@/lib/server/session";

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }

  let payload: { email?: string; password?: string };
  try {
    payload = await request.json();
  } catch {
    return NextResponse.json({ detail: "Invalid JSON body" }, { status: 400 });
  }
  if (!payload.email || !payload.password) {
    return NextResponse.json({ detail: "Email and password are required" }, { status: 422 });
  }

  const { response, tokens } = await loginBackend(payload.email, payload.password);
  if (!tokens) {
    const body = await response.text();
    return new NextResponse(body, {
      status: response.status,
      headers: { "Content-Type": response.headers.get("content-type") || "application/json" }
    });
  }

  const me = await backendRequest("/auth/me", { access: tokens.access_token });
  if (!me.ok) {
    const body = await me.text();
    return new NextResponse(body, {
      status: me.status,
      headers: { "Content-Type": me.headers.get("content-type") || "application/json" }
    });
  }
  const user = await me.json();
  const result = NextResponse.json({ user });
  return applySession(result, tokens);
}
