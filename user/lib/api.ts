import type { User } from "./types";

const BASE = "/api/backend";
export const UNAUTHORIZED_EVENT = "sensibull:unauthorized";

export class ApiError extends Error {
  status: number;
  code?: string;

  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.code = code;
  }
}

function errorMessage(payload: unknown, fallback: string): string {
  if (!payload || typeof payload !== "object") return fallback;
  const detail = (payload as { detail?: unknown }).detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((item) =>
        item && typeof item === "object" && "msg" in item
          ? String((item as { msg: unknown }).msg)
          : JSON.stringify(item)
      )
      .join("; ");
  }
  return fallback;
}

async function parse<T>(response: Response): Promise<T> {
  const text = await response.text();
  const payload = text ? JSON.parse(text) : null;
  if (!response.ok) {
    throw new ApiError(
      errorMessage(payload, `Request failed (${response.status})`),
      response.status,
      payload?.code
    );
  }
  return payload as T;
}

async function request<T>(path: string): Promise<T> {
  const response = await fetch(BASE + path, {
    headers: { Accept: "application/json" },
    credentials: "same-origin",
    cache: "no-store"
  });
  if (response.status === 401 && typeof window !== "undefined") {
    window.dispatchEvent(new Event(UNAUTHORIZED_EVENT));
  }
  return parse<T>(response);
}

export async function login(email: string, password: string): Promise<User> {
  const response = await fetch("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json", Accept: "application/json" },
    body: JSON.stringify({ email, password }),
    credentials: "same-origin",
    cache: "no-store"
  });
  const payload = await parse<{ user: User }>(response);
  return payload.user;
}

export async function logout(): Promise<void> {
  try {
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store"
    });
  } catch {
    // The server clears the HttpOnly cookies when reachable.
  }
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path);
  },
  me(): Promise<User> {
    return request<User>("/auth/me");
  }
};

export function buildQuery(params: Record<string, string | number | boolean | undefined | null>): string {
  const query = new URLSearchParams();
  Object.entries(params).forEach(([key, value]) => {
    if (value === undefined || value === null || value === "") return;
    query.set(key, String(value));
  });
  const text = query.toString();
  return text ? `?${text}` : "";
}

export type { Page } from "./types";
