import { cookies } from "next/headers";
import { NextResponse } from "next/server";

export const ACCESS_COOKIE = "sensibull_admin_access";
export const REFRESH_COOKIE = "sensibull_admin_refresh";
const ACCESS_MAX_AGE = 60 * 60;
const REFRESH_MAX_AGE = 14 * 24 * 60 * 60;
const SECURE = process.env.NODE_ENV === "production";
const APP_ORIGIN = process.env.APP_ORIGIN;

export const API_BASE = (process.env.API_BASE_URL || "http://127.0.0.1:8000").replace(/\/+$/, "");
export const API_PREFIX = "/api/v1";

export interface TokenPair {
  access_token: string;
  refresh_token: string;
  token_type: string;
  expires_in: number;
}

export async function readSession(): Promise<{ access: string | null; refresh: string | null }> {
  const store = await cookies();
  return {
    access: store.get(ACCESS_COOKIE)?.value ?? null,
    refresh: store.get(REFRESH_COOKIE)?.value ?? null
  };
}

export function applySession(response: NextResponse, tokens: TokenPair): NextResponse {
  response.cookies.set(ACCESS_COOKIE, tokens.access_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: SECURE,
    path: "/",
    maxAge: ACCESS_MAX_AGE
  });
  response.cookies.set(REFRESH_COOKIE, tokens.refresh_token, {
    httpOnly: true,
    sameSite: "lax",
    secure: SECURE,
    path: "/",
    maxAge: REFRESH_MAX_AGE
  });
  return response;
}

export function clearSession(response: NextResponse): NextResponse {
  for (const name of [ACCESS_COOKIE, REFRESH_COOKIE]) {
    response.cookies.set(name, "", {
      httpOnly: true,
      sameSite: "lax",
      secure: SECURE,
      path: "/",
      maxAge: 0
    });
  }
  return response;
}

export function sameOrigin(request: Request): boolean {
  const origin = request.headers.get("origin");
  if (!origin) return true;
  if (APP_ORIGIN) return origin === APP_ORIGIN;
  return origin === new URL(request.url).origin;
}

export async function backendRequest(
  path: string,
  options: { method?: string; body?: BodyInit; access?: string | null; headers?: HeadersInit } = {}
): Promise<Response> {
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (options.access) headers.set("Authorization", `Bearer ${options.access}`);
  return fetch(API_BASE + API_PREFIX + path, {
    method: options.method || "GET",
    headers,
    body: options.body,
    cache: "no-store"
  });
}

export async function loginBackend(email: string, password: string): Promise<{ response: Response; tokens: TokenPair | null }> {
  const response = await fetch(API_BASE + API_PREFIX + "/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ email, password }),
    cache: "no-store"
  });
  if (!response.ok) return { response, tokens: null };
  return { response, tokens: (await response.json()) as TokenPair };
}

async function refreshBackend(refresh: string): Promise<TokenPair | null> {
  const response = await fetch(API_BASE + API_PREFIX + "/auth/refresh", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ refresh_token: refresh }),
    cache: "no-store"
  });
  if (!response.ok) return null;
  return (await response.json()) as TokenPair;
}

let refreshInFlight: Promise<TokenPair | null> | null = null;
let refreshInFlightToken: string | null = null;

export async function refreshSessionOnce(refresh: string): Promise<TokenPair | null> {
  if (refreshInFlight && refreshInFlightToken === refresh) return refreshInFlight;
  refreshInFlightToken = refresh;
  refreshInFlight = refreshBackend(refresh).finally(() => {
    refreshInFlight = null;
    refreshInFlightToken = null;
  });
  return refreshInFlight;
}
