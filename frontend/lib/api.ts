"use client";
import useSWR from "swr";

export const API = process.env.NEXT_PUBLIC_API ?? "http://localhost:8000";

async function unwrap(r: Response) {
  const body = await r.json().catch(() => ({}));
  // Session expired mid-use: reload to show the sign-in form (not for the sign-in calls themselves).
  if (r.status === 401 && !r.url.includes("/api/auth/")) window.location.reload();
  if (!r.ok) throw new Error(body?.detail ?? `HTTP ${r.status}`);
  return body.data;
}

// Cookies carry the session, so every request includes credentials (the API allows only the web origin).
export const get = (path: string) => fetch(API + path, { credentials: "include" }).then(unwrap);

export const post = (path: string, body?: unknown) =>
  fetch(API + path, {
    method: "POST",
    credentials: "include",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  }).then(unwrap);

/** "price_change" -> "Price change" for labels that come straight from the API. */
export const humanize = (s: string | null | undefined) => {
  const t = String(s ?? "").replace(/_/g, " ").trim();
  return t ? t[0].toUpperCase() + t.slice(1) : "";
};

/** Poll an endpoint (every 5 s unless a page asks for faster). */
export function useApi<T = any>(path: string | null, refreshInterval = 5000) {
  return useSWR<T>(path, get, { refreshInterval });
}

export const usd = (cents: number | null | undefined) =>
  cents == null ? "—" : (cents / 100).toLocaleString("en-US", { style: "currency", currency: "USD" });

export const dollars = (d: number | null | undefined) =>
  d == null ? "—" : Number(d).toLocaleString("en-US", { style: "currency", currency: "USD" });

export const when = (ts: string | null | undefined) =>
  ts ? new Date(ts).toLocaleString("en-US", {
    month: "short", day: "numeric", hour: "2-digit", minute: "2-digit",
    timeZone: "America/New_York", timeZoneName: "short",
  }) : "—";
