import type { SettingsResponse, User } from "./types";

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

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers);
  headers.set("Accept", "application/json");
  const response = await fetch(BASE + path, {
    ...init,
    headers,
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
    // Cookies are HttpOnly; the server clears them when reachable.
  }
}

export const api = {
  get<T>(path: string): Promise<T> {
    return request<T>(path);
  },
  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
  },
  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "PATCH",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
  },
  put<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: body === undefined ? undefined : JSON.stringify(body)
    });
  },
  me(): Promise<User> {
    return request<User>("/auth/me");
  },
  async download(path: string, filename: string): Promise<void> {
    const response = await fetch(BASE + path, {
      credentials: "same-origin",
      cache: "no-store"
    });
    if (!response.ok) {
      const payload = await response.json().catch(() => null);
      throw new ApiError(errorMessage(payload, "Download failed"), response.status);
    }
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  },
  settings(): Promise<SettingsResponse> {
    return request<SettingsResponse>("/admin/settings");
  },
  updateSettings(settings: Record<string, Record<string, unknown>>): Promise<SettingsResponse> {
    return request<SettingsResponse>("/admin/settings", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ settings })
    });
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
