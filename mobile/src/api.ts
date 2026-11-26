import { API_URL } from "./config";

export class ApiError extends Error {
  constructor(public code: string, public status: number) {
    super(code);
  }
}

let token: string | null = null;
let onUnauthorized: (() => void) | null = null;

export function setToken(t: string | null) {
  token = t;
}
export function getToken() {
  return token;
}
export function setUnauthorizedHandler(fn: () => void) {
  onUnauthorized = fn;
}

export function authHeaders(): Record<string, string> {
  return token ? { Authorization: `Bearer ${token}` } : {};
}

/** POST /m/api/<path> с JSON. Ошибки сервера → ApiError(code), нет сети → ApiError("network"). */
export async function api<T = any>(path: string, body?: object, timeoutMs = 25000): Promise<T> {
  if (!API_URL) throw new ApiError("no_server", 0);
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  let r: Response;
  try {
    r = await fetch(`${API_URL}/m/api/${path}`, {
      method: "POST",
      headers: { "Content-Type": "application/json", Accept: "application/json", ...authHeaders() },
      body: JSON.stringify(body ?? {}),
      signal: ctrl.signal,
    });
  } catch {
    throw new ApiError("network", 0);
  } finally {
    clearTimeout(timer);
  }
  let data: any = null;
  try {
    data = await r.json();
  } catch {
    data = null;
  }
  if (!r.ok) {
    const code = (data && data.error) || `http_${r.status}`;
    if (r.status === 401 && code === "auth" && token) onUnauthorized?.();
    throw new ApiError(code, r.status);
  }
  return data as T;
}

export function chartUrl(id: number) {
  return `${API_URL}/m/api/chart/${id}.png`;
}
