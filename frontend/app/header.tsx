"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { API, post, useApi, when } from "@/lib/api";
import { allowed, useMe } from "./auth-gate";

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
  const me = useMe();
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [demoOpen, setDemoOpen] = useState(false);
  const [demo, setDemo] = useState<DemoState>(null);
  const [navOpen, setNavOpen] = useState(false);

  useEffect(() => setNavOpen(false), [path]);

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
    const es = new EventSource(`${API}/api/events`, { withCredentials: true });
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

  const signOut = async () => {
    await post("/api/auth/logout").catch(() => {});
    window.location.reload();
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

  const active = (href: string) => path === href || (href === "/close" && path.startsWith("/cases/"));
  const live = s?.llm_mode === "live";

  return (
    <aside className="sticky top-0 z-20 border-b border-line bg-paper min-[761px]:flex min-[761px]:h-screen min-[761px]:w-[232px] min-[761px]:shrink-0 min-[761px]:flex-col min-[761px]:border-r min-[761px]:border-b-0 min-[761px]:overflow-y-auto min-[761px]:px-3.5 min-[761px]:py-5">
      <div className="flex items-center justify-between px-4 py-3 min-[761px]:px-2 min-[761px]:pt-1 min-[761px]:pb-4">
        <Link href="/" className="tu-focus rounded text-[13px] font-bold tracking-[0.22em] text-ink">TOKENTRUEUP</Link>
        <button type="button" className="tu-btn-ghost px-2.5 py-1.5 min-[761px]:hidden" aria-expanded={navOpen}
          aria-controls="sidebar-body" aria-label={navOpen ? "Close navigation" : "Open navigation"}
          onClick={() => setNavOpen(!navOpen)}>
          <span aria-hidden className="text-base leading-none">{navOpen ? "×" : "☰"}</span>
        </button>
      </div>

      <div id="sidebar-body" className={`${navOpen ? "flex" : "hidden"} flex-1 flex-col gap-0.5 px-3.5 pb-4 min-[761px]:flex min-[761px]:px-0 min-[761px]:pb-0`}>
        <p className="mb-3 rounded-lg border border-amber-line bg-amber-bg px-2.5 py-2 text-[11px] leading-snug font-semibold text-amber">
          Synthetic data: every provider, key, invoice and dollar here is simulated
        </p>
        <nav aria-label="Primary" className="flex flex-col gap-0.5">
          {NAV.map(([href, label]) => (
            <Link key={href} href={href} aria-current={active(href) ? "page" : undefined}
              className={`tu-focus flex items-center gap-2.5 rounded-lg border px-2.5 py-2 text-sm ${active(href)
                ? "border-line bg-surface font-semibold text-ink"
                : "border-transparent text-ink-2 hover:bg-surface-2"}`}>
              <span aria-hidden className="size-3.5 shrink-0 rounded-[3px] border-[1.5px] border-ink-3" />
              {label}
            </Link>
          ))}
        </nav>

        <div className="min-h-4 flex-1" />

        {demo && (
          <div className="mb-3 rounded-lg border border-green-2/30 bg-green-bg p-3 text-[13px] text-ink">
            <span className="inline-block rounded-full bg-green px-2 py-0.5 text-[11px] font-semibold text-white">
              DEMO · {demo.phase === "detecting" ? "DETECT" : "CASE"}
            </span>
            <p className="mt-2 font-semibold">
              {demo.phase === "detecting" ? "Catch runaway AI spend" : "Investigate the detected anomaly"}
            </p>
            <p className="mt-1 text-xs text-ink-2">
              {demo.phase === "detecting"
                ? "A retry loop is driving one key to 80× normal usage. Watch TimescaleDB detect it automatically."
                : "The database opened a case with the spike window, financial impact, and reproducible evidence."}
            </p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              {demo.phase === "investigate" && demo.caseId
                ? <Link className="tu-btn-primary px-2.5 py-1.5" href={`/cases/${demo.caseId}`}>Open case #{demo.caseId}</Link>
                : path !== "/" && <Link className="tu-btn-secondary px-2.5 py-1.5" href="/">View live spend</Link>}
              <button type="button" className="tu-focus rounded text-xs font-semibold text-green hover:underline" onClick={() => saveDemo(null)}>Exit demo</button>
            </div>
          </div>
        )}

        <div className="flex flex-col gap-2.5 border-t border-line pt-3.5">
          <span className="flex items-center gap-1.5 px-2.5 text-xs text-ink-2" title={s?.llm_model ?? "deterministic fallback agents"}>
            {live
              ? <img src="/trueup/dot-live.svg" alt="" width={7} height={7} />
              : <span aria-hidden className="size-[7px] rounded-full bg-ink-3" />}
            {s ? (live ? "Model live" : `Agents: ${s.llm_mode ?? "?"}`) : "Agents: ?"}
          </span>
          <div className="rounded-lg border border-line bg-surface px-2.5 py-2" title="sim clock">
            <div className="text-[13px] font-semibold text-ink tabular-nums">{s ? when(s.sim_now) : "connecting…"}</div>
            <div className="text-xs text-ink-3 tabular-nums">
              {s ? `${Math.round(s.ingest_eps ?? 0).toLocaleString()} ev/s` : " "}
            </div>
          </div>
          {me && (
            <div className="flex items-center justify-between gap-2 px-2.5 text-xs text-ink-2">
              <span className="min-w-0 truncate">{me.name} · <span className="font-semibold text-ink">{me.role}</span></span>
              <button type="button" className="tu-focus rounded font-semibold text-green hover:underline" onClick={signOut}>Sign out</button>
            </div>
          )}
          {allowed(me, "admin") && <div className="flex gap-2">
            {s && (s.paused
              ? <button type="button" className="tu-btn-secondary px-2.5 py-1.5" onClick={() => act("play", () => post("/api/sim/play"))}>▶ Play</button>
              : <button type="button" className="tu-btn-secondary px-2.5 py-1.5" onClick={() => act("pause", () => post("/api/sim/pause"))}>⏸ Pause</button>)}
            <select aria-label="Simulate a scenario" className="tu-focus min-w-0 flex-1 rounded-lg border border-line-2 bg-surface px-2 py-1.5 text-[13px] text-ink" value="" disabled={!!busy}
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
          </div>}
          {allowed(me, "admin") && (
            <button type="button" className="tu-btn-primary w-full" disabled={!!busy} onClick={() => setDemoOpen(true)}>
              <span aria-hidden>▶</span> Run product demo
            </button>
          )}
        </div>
      </div>

      {toast && (
        <div role="status" className="fixed right-4 bottom-4 z-40 rounded-lg bg-ink px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
      {demoOpen && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4" role="dialog" aria-modal="true" aria-labelledby="demo-title" onMouseDown={(e) => e.target === e.currentTarget && setDemoOpen(false)}>
          <div className="w-full max-w-2xl rounded-xl bg-surface p-6 shadow-2xl">
            <div className="flex items-start gap-4">
              <div className="flex h-11 w-11 shrink-0 items-center justify-center rounded-lg bg-green text-xl text-white">▶</div>
              <div className="flex-1">
                <div className="tu-eyebrow text-green">Product demo · about 3 minutes</div>
                <h2 id="demo-title" className="mt-1 font-serif text-3xl text-ink">See the AI spend control loop</h2>
                <p className="mt-2 text-ink-2">Start from a clean month, catch a runaway agent in seconds, close unbilled spend, then find an invoice discrepancy and learn from it.</p>
              </div>
              <button type="button" className="tu-focus rounded text-2xl leading-none text-ink-3 hover:text-ink" aria-label="Close" onClick={() => setDemoOpen(false)}>×</button>
            </div>
            <ol className="mt-6 grid gap-3 sm:grid-cols-3">
              <li className="rounded-lg border border-line p-3"><div className="text-xs font-semibold text-green">1 · DETECT</div><div className="mt-1 font-semibold text-ink">Catch runaway spend</div><p className="mt-1 text-sm text-ink-2">An 80× retry loop is detected against the live baseline.</p></li>
              <li className="rounded-lg border border-line p-3"><div className="text-xs font-semibold text-green">2 · CLOSE</div><div className="mt-1 font-semibold text-ink">Accrue the month</div><p className="mt-1 text-sm text-ink-2">Usage, contracts, and purchases become evidence-backed cases.</p></li>
              <li className="rounded-lg border border-line p-3"><div className="text-xs font-semibold text-green">3 · LEARN</div><div className="mt-1 font-semibold text-ink">Reconcile invoices</div><p className="mt-1 text-sm text-ink-2">An unannounced price change becomes a replayable rule.</p></li>
            </ol>
            <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
              <p className="text-xs text-ink-3">This resets the synthetic demo and removes the current run.</p>
              <div className="flex gap-2">
                <button type="button" className="tu-btn-secondary" onClick={() => setDemoOpen(false)}>Cancel</button>
                <button type="button" className="tu-btn-primary px-5" disabled={!!busy} onClick={startDemo}>{busy ? "Preparing clean demo…" : "Start demo"}</button>
              </div>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
