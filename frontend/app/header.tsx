"use client";
import Link from "next/link";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";
import { API, get, post, usd, useApi, when } from "@/lib/api";
import { allowed, useMe } from "./auth-gate";

const SIMULATION_SELECTION_KEY = "ttu-simulation-selection";
const SCENARIO_OPTIONS = new Set(["runaway", "stealth_price", "duplicate_invoice", "price_change", "late_data"]);
const SIMULATION_OPTIONS = [
  { value: "runaway", label: "Runaway agent", detail: "Support triage agent" },
  { value: "stealth_price", label: "Unannounced price change", detail: "Nimbus" },
  { value: "duplicate_invoice", label: "Duplicate invoice", detail: "Stratus" },
  { value: "price_change", label: "Announced price change", detail: "Cortexa" },
  { value: "late_data", label: "Late-arriving metering", detail: "Helio" },
] as const;
const TIME_JUMPS = [
  { value: "ff:month_end", label: "Fast-forward to month end" },
  { value: "ff:invoices", label: "Fast-forward to invoices" },
] as const;

type RunawayAlert = {
  caseId: number;
  apiKeyId?: number;
  keyLabel?: string;
  model?: string;
  projectedHourlyCents?: number;
  baselineHourlyCents?: number;
};

export default function Header({ demoMode = false }: { demoMode?: boolean }) {
  const path = usePathname();
  const router = useRouter();
  const { data: s, mutate } = useApi(demoMode ? "/api/state" : null, 1000);
  const me = useMe();
  const [busy, setBusy] = useState<string | null>(null);
  const [toast, setToast] = useState<string | null>(null);
  const [runawayAlert, setRunawayAlert] = useState<RunawayAlert | null>(null);
  const [demoOpen, setDemoOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [selectedSimulation, setSelectedSimulation] = useState("");
  const root = demoMode ? "/demo" : "/app";
  const nav = demoMode
    ? [[root, "Live spend"], [`${root}/close`, "Close"], [`${root}/recon`, "Reconciliation"], [`${root}/uth`, "Under the hood"]]
    : [[root, "Overview"], [`${root}/connections`, "Connections"]];

  useEffect(() => setNavOpen(false), [path]);
  useEffect(() => {
    const saved = localStorage.getItem(SIMULATION_SELECTION_KEY) ?? "";
    if (SCENARIO_OPTIONS.has(saved)) setSelectedSimulation(saved);
  }, []);

  const rememberSimulation = (value: string) => {
    setSelectedSimulation(value);
    if (value) localStorage.setItem(SIMULATION_SELECTION_KEY, value);
    else localStorage.removeItem(SIMULATION_SELECTION_KEY);
  };

  // anomaly cases are opened by a job inside the database; it NOTIFYs, the API relays over SSE
  useEffect(() => {
    if (!demoMode) return;
    const es = new EventSource(`${API}/api/events`, { withCredentials: true });
    es.addEventListener("case", (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        if (d.event === "anomaly_opened") {
          const initial = { caseId: Number(d.case_id), apiKeyId: Number(d.api_key_id) };
          setRunawayAlert(initial);
          get(`/api/cases/${d.case_id}`).then((payload) => {
            const c = payload.case;
            const calc = c?.calc?.estimate ?? c?.calc ?? {};
            setRunawayAlert((current) => current?.caseId === initial.caseId ? {
              ...current,
              keyLabel: c?.key_label,
              model: calc.model,
              projectedHourlyCents: Number(calc.projected_hourly_cents),
              baselineHourlyCents: Number(calc.baseline_mean_cents),
            } : current);
          }).catch(() => {});
        }
        if (d.event === "invoices_received") setToast("Provider invoices received");
      } catch {}
    });
    return () => es.close();
  }, [demoMode]);
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
    setRunawayAlert(null);
    try {
      await post("/api/demo/start");
      rememberSimulation("runaway");
      setDemoOpen(false);
      setToast("Demo started: an AI agent is entering a runaway retry loop");
      router.push(root);
      mutate();
    } catch (e) {
      setToast(`Demo failed to start: ${(e as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const active = (href: string) => path === href || (href === `${root}/close` && path.startsWith(`${root}/cases/`));
  const live = s?.llm_mode === "live";
  const activeScenarios = Object.entries(s?.scenario ?? {}).filter(([, value]: [string, any]) =>
    value && (typeof value !== "object" || value.active !== false));

  return (
    <aside className="sticky top-0 z-20 border-b border-line bg-paper min-[761px]:flex min-[761px]:h-screen min-[761px]:w-[232px] min-[761px]:shrink-0 min-[761px]:flex-col min-[761px]:border-r min-[761px]:border-b-0 min-[761px]:overflow-y-auto min-[761px]:px-3.5 min-[761px]:py-5">
      <div className="flex items-center justify-between px-4 py-3 min-[761px]:px-2 min-[761px]:pt-1 min-[761px]:pb-4">
        <Link href="/" className="tu-focus rounded" aria-label="True Token Up home">
          <Image src="/tokentrueup-logo.svg" alt="True Token Up" width={420} height={200} priority
            className="h-auto w-[128px] min-[761px]:w-[150px]" />
        </Link>
        <button type="button" className="tu-btn-ghost px-2.5 py-1.5 min-[761px]:hidden" aria-expanded={navOpen}
          aria-controls="sidebar-body" aria-label={navOpen ? "Close navigation" : "Open navigation"}
          onClick={() => setNavOpen(!navOpen)}>
          <span aria-hidden className="text-base leading-none">{navOpen ? "×" : "☰"}</span>
        </button>
      </div>

      <div id="sidebar-body" className={`${navOpen ? "flex" : "hidden"} flex-1 flex-col gap-0.5 px-3.5 pb-4 min-[761px]:flex min-[761px]:px-0 min-[761px]:pb-0`}>
        {demoMode && <p className="mb-3 rounded-lg border border-amber-line bg-amber-bg px-2.5 py-2 text-[11px] leading-snug font-semibold text-amber">
          Synthetic data: every provider, key, invoice and dollar here is simulated
        </p>}
        {demoMode && <section aria-labelledby="simulation-controls" className="flex flex-col gap-2.5">
          <h2 id="simulation-controls" className="px-1 text-[11px] font-semibold tracking-[0.1em] text-ink-3 uppercase">Simulation</h2>
          <div className="rounded-lg border border-line bg-surface px-2.5 py-2" title="sim clock">
            <div className="text-[13px] font-semibold text-ink tabular-nums">{s ? when(s.sim_now) : "connecting…"}</div>
            <div className="text-xs text-ink-3 tabular-nums">
              {s ? `${Math.round(s.ingest_eps ?? 0).toLocaleString()} ev/s` : " "}
            </div>
          </div>
          <p className="px-1 text-[11px] leading-snug text-ink-3">
            Pause the live feed, trigger one scenario, or jump the demo clock forward.
          </p>
          {allowed(me, "admin") && <div className="flex gap-2">
            {s && (s.paused
              ? <button type="button" className="tu-btn-secondary px-2.5 py-1.5" onClick={() => act("play", () => post("/api/sim/play"))}>▶ Play</button>
              : <button type="button" className="tu-btn-secondary px-2.5 py-1.5" onClick={() => act("pause", () => post("/api/sim/pause"))}>⏸ Pause</button>)}
            <SimulationMenu value={selectedSimulation} busy={busy} onSelect={(v) => {
                if (v.startsWith("ff:")) {
                  rememberSimulation("");
                  act("fast-forward", () => post("/api/sim-fast-forward", { target: v.slice(3) }));
                } else if (v) {
                  rememberSimulation(v);
                  act(v, () => post(`/api/scenario/${v}`));
                }
              }} />
          </div>}
          {allowed(me, "admin") && (
            <div className="grid grid-cols-1 gap-2">
              <button type="button" className="tu-btn-secondary w-full px-2.5 py-1.5" disabled={!!busy}
                title="Clear the current run, rebuild a smooth normal last hour, and start live usage"
                onClick={() => { rememberSimulation(""); act("clean baseline", () => post("/api/sim/baseline")); }}>
                ↺ Clean baseline
              </button>
              <button type="button" className="tu-btn-secondary w-full px-2.5 py-1.5 text-red-700" disabled={!!busy || activeScenarios.length === 0}
                title="Stop active scenarios; keep their usage and cases as evidence"
                onClick={() => { rememberSimulation(""); act("stop scenarios", () => post("/api/scenario/stop")); }}>
                ■ Stop scenarios
              </button>
            </div>
          )}
          {allowed(me, "admin") && activeScenarios.length > 0 && (
            <p className="px-1 text-[11px] leading-snug text-red-700">
              Active: {activeScenarios.map(([name]) => name.replaceAll("_", " ")).join(", ")}
            </p>
          )}
          {allowed(me, "admin") && (
            <div className="mt-1">
              <p className="mb-2 px-1 text-[11px] leading-snug text-ink-3">
                Run the guided walkthrough to reset the data and demonstrate detection, close, and reconciliation.
              </p>
              <button type="button" className="tu-btn-primary w-full" disabled={!!busy} onClick={() => setDemoOpen(true)}>
                <span aria-hidden>▶</span> Run product demo
              </button>
            </div>
          )}
        </section>}

        <nav aria-label="Primary" className="mt-3 flex flex-col gap-0.5 border-t border-line pt-3">
          {nav.map(([href, label]) => (
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

        <div className="flex flex-col gap-2.5 border-t border-line pt-3.5">
          {demoMode && (
          <span className="flex items-center gap-1.5 px-2.5 text-xs text-ink-2" title={s?.llm_model ?? "deterministic fallback agents"}>
            {live
              ? <img src="/trueup/dot-live.svg" alt="" width={7} height={7} />
              : <span aria-hidden className="size-[7px] rounded-full bg-ink-3" />}
            {s ? (live ? "Model live" : `Agents: ${s.llm_mode ?? "?"}`) : "Agents: ?"}
          </span>
          )}
          {me && !demoMode && (
            <div className="flex items-center justify-between gap-2 px-2.5 text-xs text-ink-2">
              <span className="min-w-0 truncate">{me.name} · <span className="font-semibold text-ink">{me.role}</span></span>
              <button type="button" className="tu-focus rounded font-semibold text-green hover:underline" onClick={signOut}>Sign out</button>
            </div>
          )}
        </div>
      </div>

      {toast && (
        <div role="status" className="fixed right-4 bottom-4 z-40 rounded-lg bg-ink px-4 py-2 text-sm text-white shadow-lg">{toast}</div>
      )}
      {runawayAlert && <RunawaySpendAlert alert={runawayAlert} caseRoot={`${root}/cases`} dismiss={() => setRunawayAlert(null)} />}
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

function SimulationMenu({ value, busy, onSelect }: {
  value: string;
  busy: string | null;
  onSelect: (value: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);
  const selected = SIMULATION_OPTIONS.find((option) => option.value === value);

  useEffect(() => {
    if (!open) return;
    const closeOutside = (event: PointerEvent) => {
      if (!rootRef.current?.contains(event.target as Node)) setOpen(false);
    };
    const closeOnEscape = (event: globalThis.KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false);
    };
    document.addEventListener("pointerdown", closeOutside);
    document.addEventListener("keydown", closeOnEscape);
    return () => {
      document.removeEventListener("pointerdown", closeOutside);
      document.removeEventListener("keydown", closeOnEscape);
    };
  }, [open]);

  const choose = (next: string) => {
    setOpen(false);
    onSelect(next);
  };

  return (
    <div ref={rootRef} className="relative min-w-0 flex-1">
      <button type="button" aria-haspopup="menu" aria-expanded={open} disabled={!!busy}
        onClick={() => setOpen((current) => !current)}
        className={`tu-focus flex w-full min-w-0 items-center justify-between gap-2 rounded-lg border bg-surface px-2.5 py-1.5 text-left text-[13px] transition-colors disabled:opacity-50 ${open ? "border-green ring-2 ring-green/10" : "border-line-2 hover:border-green/50"}`}>
        <span className="min-w-0 truncate font-medium text-ink">{busy ? `${busy}…` : selected?.label ?? "Simulate…"}</span>
        <svg aria-hidden viewBox="0 0 16 16" className={`size-3.5 shrink-0 text-ink-3 transition-transform ${open ? "rotate-180" : ""}`} fill="none" stroke="currentColor" strokeWidth="1.7">
          <path d="m3 6 5 5 5-5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
      </button>

      {open && (
        <div role="menu" aria-label="Simulation options"
          className="absolute top-[calc(100%+6px)] right-0 z-50 w-[204px] overflow-hidden rounded-xl border border-line-2 bg-surface p-1.5 shadow-[0_16px_40px_rgba(22,33,27,0.18)]">
          <div className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] text-ink-3 uppercase">Trigger a scenario</div>
          {SIMULATION_OPTIONS.map((option) => {
            const active = option.value === value;
            return (
              <button key={option.value} type="button" role="menuitemradio" aria-checked={active} onClick={() => choose(option.value)}
                className={`tu-focus flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left transition-colors ${active ? "bg-green-bg text-green" : "text-ink hover:bg-surface-2"}`}>
                <span aria-hidden className={`mt-1 size-2 shrink-0 rounded-full ${active ? "bg-green" : "border border-line-2"}`} />
                <span className="min-w-0"><span className="block text-xs font-semibold leading-snug">{option.label}</span><span className="mt-0.5 block text-[10px] leading-snug text-ink-3">{option.detail}</span></span>
              </button>
            );
          })}
          <div className="my-1 border-t border-line" />
          <div className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] text-ink-3 uppercase">Jump the clock</div>
          {TIME_JUMPS.map((option) => (
            <button key={option.value} type="button" role="menuitem" onClick={() => choose(option.value)}
              className="tu-focus flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left text-ink hover:bg-surface-2">
              <span aria-hidden className="mt-px text-xs text-green">»</span>
              <span className="text-xs font-semibold leading-snug">{option.label}</span>
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

function RunawaySpendAlert({ alert, caseRoot, dismiss }: { alert: RunawayAlert; caseRoot: string; dismiss: () => void }) {
  const projected = Number.isFinite(alert.projectedHourlyCents) ? alert.projectedHourlyCents : undefined;
  const baseline = Number.isFinite(alert.baselineHourlyCents) ? alert.baselineHourlyCents : undefined;
  const multiple = projected != null && baseline != null && baseline > 0 ? Math.round(projected / baseline) : null;

  return (
    <div className="fixed inset-x-4 top-4 z-[70] ml-auto max-w-[460px] overflow-hidden rounded-xl border border-red-300 bg-white shadow-[0_24px_80px_rgba(127,29,29,0.32)]"
      role="alert" aria-live="assertive" aria-labelledby="runaway-alert-title" aria-describedby="runaway-alert-description">
      <div className="h-1.5 bg-red-600" />
      <div className="p-5">
        <div className="flex items-start gap-3.5">
          <div className="relative mt-0.5 flex size-11 shrink-0 items-center justify-center rounded-full bg-red-100 text-red-700">
            <span className="absolute inset-0 animate-ping rounded-full bg-red-400 opacity-20" aria-hidden />
            <svg aria-hidden viewBox="0 0 24 24" className="relative size-6" fill="none" stroke="currentColor" strokeWidth="2.2">
              <path d="M12 8v5" strokeLinecap="round" /><path d="M12 17h.01" strokeLinecap="round" />
              <path d="M10.3 3.8 2.5 17.2A2 2 0 0 0 4.2 20h15.6a2 2 0 0 0 1.7-2.8L13.7 3.8a2 2 0 0 0-3.4 0Z" />
            </svg>
          </div>
          <div className="min-w-0 flex-1">
            <div className="text-[11px] font-bold tracking-[0.14em] text-red-700 uppercase">Automated spend alert</div>
            <h2 id="runaway-alert-title" className="mt-1 font-serif text-[26px] leading-tight text-ink">Runaway AI spend detected</h2>
            <p id="runaway-alert-description" className="mt-2 text-sm leading-relaxed text-ink-2">
              {alert.keyLabel ? <><span className="font-mono font-semibold text-ink">{alert.keyLabel}</span>{alert.model ? <> on {alert.model}</> : null} crossed its expected spend threshold.</> : "A key crossed its expected hourly spend threshold."}
            </p>
          </div>
          <button type="button" onClick={dismiss} aria-label="Dismiss runaway spend alert"
            className="tu-focus -mt-1 rounded p-1 text-2xl leading-none text-ink-3 hover:text-ink">×</button>
        </div>

        {projected != null && baseline != null && (
          <div className="mt-4 grid grid-cols-3 divide-x divide-red-200 rounded-lg border border-red-200 bg-red-50 py-3">
            <AlertMetric label="Current pace" value={`${usd(projected)}/h`} />
            <AlertMetric label="Normal baseline" value={`${usd(baseline)}/h`} />
            <AlertMetric label="Increase" value={multiple == null ? "—" : `${multiple}×`} danger />
          </div>
        )}

        <p className="mt-3 text-xs leading-relaxed text-ink-3">
          TokenTrueUp detected this automatically and opened case #{alert.caseId} with reproducible evidence.
        </p>
        <div className="mt-4 flex items-center gap-2">
          <Link href={`${caseRoot}/${alert.caseId}`} onClick={dismiss}
            className="tu-focus inline-flex flex-1 items-center justify-center rounded-lg bg-red-700 px-4 py-2.5 text-sm font-semibold text-white hover:bg-red-800">
            Investigate case #{alert.caseId} <span aria-hidden>→</span>
          </Link>
          <button type="button" onClick={dismiss} className="tu-btn-secondary px-4 py-2.5">Dismiss</button>
        </div>
      </div>
    </div>
  );
}

function AlertMetric({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="min-w-0 px-3 text-center">
      <div className="text-[10px] font-semibold tracking-wide text-ink-3 uppercase">{label}</div>
      <div className={`mt-1 truncate text-sm font-bold tabular-nums ${danger ? "text-red-700" : "text-ink"}`}>{value}</div>
    </div>
  );
}
