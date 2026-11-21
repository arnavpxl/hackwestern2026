"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { API, post, useApi, when } from "@/lib/api";
import { allowed, useMe } from "./auth-gate";

const NAV = [
  ["/", "Live spend"],
  ["/close", "Close"],
  ["/recon", "Reconciliation"],
  ["/uth", "Under the hood"],
];

export default function Header() {
  const path = usePathname();
  const { data: s, mutate } = useApi("/api/state", 1000);
  const me = useMe();
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);

  // anomaly cases are opened by a job inside the database; it NOTIFYs, the API relays over SSE
  useEffect(() => {
    const es = new EventSource(`${API}/api/events`, { withCredentials: true });
    es.addEventListener("case", (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        if (d.event === "anomaly_opened") setToast(`Anomaly detected: case #${d.case_id}`);
        if (d.event === "invoices_received") setToast("Provider invoices received");
      } catch {}
    });
    return () => es.close();
  }, []);
  useEffect(() => {
    if (!toast) return;
    const t = setTimeout(() => setToast(null), 6000);
    return () => clearTimeout(t);
  }, [toast]);

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try { await fn(); } catch (e) { setToast(`${label} failed: ${(e as Error).message}`); }
    setBusy(null);
    mutate();
  };

  const signOut = async () => {
    await post("/api/auth/logout").catch(() => {});
    window.location.reload();
  };

  return (
    <header className="sticky top-0 z-10 border-b border-slate-200 bg-white">
      <div className="bg-amber-100 px-4 py-1 text-center text-xs font-semibold tracking-wide text-amber-900">
        SYNTHETIC DATA: every provider, key, invoice and dollar here is simulated
      </div>
      <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3">
        <span className="text-lg font-bold text-ink">TokenTrueUp</span>
        <nav className="flex gap-1">
          {NAV.map(([href, label]) => (
            <Link key={href} href={href}
              className={`rounded px-2.5 py-1 text-sm ${path === href ? "bg-indigo-50 font-semibold text-indigo-700" : "text-slate-600 hover:bg-slate-100"}`}>
              {label}
            </Link>
          ))}
        </nav>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-sm">
          <span className="tabular-nums text-slate-600" title="sim clock">
            {s ? when(s.sim_now) : "connecting…"}
            {s && <span className="ml-2 text-xs text-slate-400">{Math.round(s.ingest_eps ?? 0).toLocaleString()} ev/s</span>}
          </span>
          {s && allowed(me, "admin") && (s.paused
            ? <button className="btn" onClick={() => act("play", () => post("/api/sim/play"))}>▶ Play</button>
            : <button className="btn" onClick={() => act("pause", () => post("/api/sim/pause"))}>⏸ Pause</button>)}
          {allowed(me, "admin") && <select className="btn" value="" disabled={!!busy}
            onChange={(e) => {
              const v = e.target.value;
              if (v.startsWith("ff:")) act("fast-forward", () => post("/api/sim-fast-forward", { target: v.slice(3) }));
              else if (v === "reset") act("reset", () => post("/api/sim/reset"));
              else if (v) act(v, () => post(`/api/scenario/${v}`));
            }}>
            <option value="">{busy ? `${busy}…` : "Simulate…"}</option>
            <option value="runaway">Runaway agent (support-triage-agent)</option>
            <option value="stealth_price">Unannounced price change (Nimbus)</option>
            <option value="duplicate_invoice">Duplicate invoice (Stratus)</option>
            <option value="price_change">Announced price change (Cortexa)</option>
            <option value="late_data">Late-arriving metering (Helio)</option>
            <option value="ff:month_end">⏩ Fast-forward to month end</option>
            <option value="ff:invoices">⏩ Fast-forward to invoices</option>
            <option value="reset">↺ Reset demo</option>
          </select>}
          {me && <span className="text-slate-600">{me.name} · <span className="font-semibold">{me.role}</span></span>}
          <button className="btn" onClick={signOut}>Sign out</button>
          <span className={`pill ${s?.llm_mode === "live" ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}
            title={s?.llm_model ?? "deterministic fallback agents"}>
            agents: {s?.llm_mode ?? "?"}
          </span>
        </div>
      </div>
      {toast && (
        <div className="fixed bottom-4 right-4 rounded-md bg-ink px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
    </header>
  );
}
