import { NextRequest, NextResponse } from "next/server";

import { API_BASE, API_PREFIX, clearSession, readSession, sameOrigin } from "@/lib/server/session";

export async function POST(request: NextRequest) {
  if (!sameOrigin(request)) {
    return NextResponse.json({ detail: "Invalid request origin" }, { status: 403 });
  }

  const { refresh } = await readSession();
  if (refresh) {
    try {
      await fetch(API_BASE + API_PREFIX + "/auth/logout", {
        method: "POST",
        headers: { "Content-Type": "application/json", Accept: "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
        cache: "no-store"
      });
    } catch {
      // Local cookies are cleared even if the backend is unreachable.
    }
  }

  const response = NextResponse.json({ detail: "Logged out" });
  return clearSession(response);
}
