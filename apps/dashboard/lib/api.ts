/**
 * Local API client.
 *
 * The base URL is derived from the page host so a phone that loaded the worker
 * page from `http://<dgx-lan-ip>:3000/worker` talks to the API on the same
 * machine (spec section 8.4 mode A). Nothing here can point at a hosted service:
 * only a host and port are substituted, never a third-party domain.
 */

export const DEFAULT_API_PORT = process.env.NEXT_PUBLIC_RISKTWIN_API_PORT ?? "8000";

export function apiBase(): string {
  const configured = process.env.NEXT_PUBLIC_RISKTWIN_API;
  if (configured) return configured.replace(/\/$/, "");
  if (typeof window === "undefined") return `http://127.0.0.1:${DEFAULT_API_PORT}`;
  return `${window.location.protocol}//${window.location.hostname}:${DEFAULT_API_PORT}`;
}

export function wsUrl(): string {
  const base = apiBase();
  return `${base.replace(/^http/, "ws")}/ws`;
}

export async function getJson<T>(path: string): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { cache: "no-store" });
  if (!response.ok) throw new Error(`${path} -> ${response.status}`);
  return (await response.json()) as T;
}

export async function postJson<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) {
    // A policy block is a real, expected outcome, so the caller gets the body
    // rather than a generic error (spec section 10).
    throw Object.assign(new Error(`${path} -> ${response.status}`), {
      status: response.status,
      payload,
    });
  }
  return payload as T;
}

export async function postForm<T>(path: string, body: FormData): Promise<T> {
  const response = await fetch(`${apiBase()}${path}`, { method: "POST", body });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(`${path} -> ${response.status}`), { status: response.status, payload });
  return payload as T;
}

export const CASE_ID = process.env.NEXT_PUBLIC_RISKTWIN_CASE ?? "LIFT-042";
