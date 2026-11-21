"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API, post, useApi, when } from "@/lib/api";

const NAV = [
  ["/", "Live spend"],
  ["/close", "Close"],
  ["/recon", "Reconciliation"],
  ["/uth", "Under the hood"],
];

type DemoState = { phase: "detecting" | "investigate"; caseId?: number } | null;

export default function Header() {
  const path = usePathname();
  const router = useRouter();
  const { data: s, mutate } = useApi("/api/state", 1000);
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [demoOpen, setDemoOpen] = useState(false);
  const [demo, setDemo] = useState<DemoState>(null);

  useEffect(() => {
    try {
      const saved = localStorage.getItem("ttu-demo");
      if (saved) setDemo(JSON.parse(saved));
    } catch {}
  }, []);

  const saveDemo = (next: DemoState) => {
    setDemo(next);
    if (next) localStorage.setItem("ttu-demo", JSON.stringify(next));
    else localStorage.removeItem("ttu-demo");
  };

  // anomaly cases are opened by a job inside the database; it NOTIFYs, the API relays over SSE
  useEffect(() => {
    const es = new EventSource(`${API}/api/events`);
    es.addEventListener("case", (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        if (d.event === "anomaly_opened") {
          setToast(`Anomaly detected: case #${d.case_id}`);
          if (localStorage.getItem("ttu-demo")) saveDemo({ phase: "investigate", caseId: d.case_id });
        }
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

  const startDemo = async () => {
    setBusy("starting demo");
    try {
      await post("/api/demo/start");
      saveDemo({ phase: "detecting" });
      setDemoOpen(false);
      setToast("Demo started: an AI agent is entering a runaway retry loop");
      router.push("/");
      mutate();
    } catch (e) {
      setToast(`Demo failed to start: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
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
        <button className="btn-demo" disabled={!!busy} onClick={() => setDemoOpen(true)}>
          <span aria-hidden>▶</span> Run product demo
        </button>
        <div className="ml-auto flex flex-wrap items-center gap-2 text-sm">
          <span className="tabular-nums text-slate-600" title="sim clock">
            {s ? when(s.sim_now) : "connecting…"}
            {s && <span className="ml-2 text-xs text-slate-400">{Math.round(s.ingest_eps ?? 0).toLocaleString()} ev/s</span>}
          </span>
          {s && (s.paused
            ? <button className="btn" onClick={() => act("play", () => post("/api/sim/play"))}>▶ Play</button>
            : <button className="btn" onClick={() => act("pause", () => post("/api/sim/pause"))}>⏸ Pause</button>)}
          <select className="btn" value="" disabled={!!busy}
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
          </select>
          <span className={`pill ${s?.llm_mode === "live" ? "bg-emerald-100 text-emerald-800" : "bg-slate-100 text-slate-600"}`}
            title={s?.llm_model ?? "deterministic fallback agents"}>
            agents: {s?.llm_mode ?? "?"}
          </span>
        </div>
      </div>
      {demo && (
        <div className="border-t border-indigo-200 bg-indigo-50 px-4 py-2 text-sm text-indigo-950">
          <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-4 gap-y-2">
            <span className="pill bg-indigo-600 text-white">DEMO · {demo.phase === "detecting" ? "DETECT" : "CASE"}</span>
            <div className="flex-1">
              <span className="font-semibold">
                {demo.phase === "detecting" ? "Catch runaway AI spend" : "Investigate the detected anomaly"}
              </span>
              <span className="ml-2 text-indigo-700">
                {demo.phase === "detecting"
                  ? "A retry loop is driving one key to 80× normal usage. Watch TimescaleDB detect it automatically."
                  : "The database opened a case with the spike window, financial impact, and reproducible evidence."}
              </span>
            </div>
            {demo.phase === "investigate" && demo.caseId
              ? <Link className="btn-primary" href={`/cases/${demo.caseId}`}>Open case #{demo.caseId}</Link>
              : path !== "/" && <Link className="btn" href="/">View live spend</Link>}
            <button className="text-xs font-medium text-indigo-700 hover:underline" onClick={() => saveDemo(null)}>Exit demo</button>
          </div>
        </div>
      )}
      {toast && (
        <div className="fixed bottom-4 right-4 rounded-md bg-ink px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
      {demoOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/40 p-4" role="dialog" aria-modal="true" aria-labelledby="demo-title" onMouseDown={(e) => e.target === e.currentTarget && setDemoOpen(false)}>
          <div className="w-full max-w-2xl rounded-xl bg-white p-6 shadow-2xl">
            <div className="flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-indigo-600 text-xl text-white">▶</div>
              <div className="flex-1">
                <div className="text-xs font-semibold uppercase tracking-wider text-indigo-600">Product demo · about 3 minutes</div>
                <h2 id="demo-title" className="mt-1 text-2xl font-bold text-slate-950">See the AI spend control loop</h2>
                <p className="mt-2 text-slate-600">Start from a clean month, catch a runaway agent in seconds, close unbilled spend, then find an invoice discrepancy and learn from it.</p>
              </div>
              <button className="text-2xl leading-none text-slate-400 hover:text-slate-700" aria-label="Close" onClick={() => setDemoOpen(false)}>×</button>
            </div>
            <ol className="mt-6 grid gap-3 sm:grid-cols-3">
              <li className="rounded-lg border border-slate-200 p-3"><div className="text-xs font-semibold text-indigo-600">1 · DETECT</div><div className="mt-1 font-semibold">Catch runaway spend</div><p className="mt-1 text-sm text-slate-600">An 80× retry loop is detected against the live baseline.</p></li>
              <li className="rounded-lg border border-slate-200 p-3"><div className="text-xs font-semibold text-indigo-600">2 · CLOSE</div><div className="mt-1 font-semibold">Accrue the month</div><p className="mt-1 text-sm text-slate-600">Usage, contracts, and purchases become evidence-backed cases.</p></li>
              <li className="rounded-lg border border-slate-200 p-3"><div className="text-xs font-semibold text-indigo-600">3 · LEARN</div><div className="mt-1 font-semibold">Reconcile invoices</div><p className="mt-1 text-sm text-slate-600">An unannounced price change becomes a replayable rule.</p></li>
            </ol>
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-slate-200 pt-4">
              <p className="text-xs text-slate-500">This resets the synthetic demo and removes the current run.</p>
              <div className="flex gap-2">
                <button className="btn" onClick={() => setDemoOpen(false)}>Cancel</button>
                <button className="btn-primary px-5 py-2" disabled={!!busy} onClick={startDemo}>{busy ? "Preparing clean demo…" : "Start demo"}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </header>
  );
}
