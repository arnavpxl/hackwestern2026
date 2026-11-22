"use client";

import { useEffect, useRef, useState } from "react";
import { post, useApi, when } from "@/lib/api";
import { allowed, useMe } from "@/app/auth-gate";

const SELECTION_KEY = "ttu-simulation-selection";
const SCENARIO_VALUES = new Set(["runaway", "stealth_price", "duplicate_invoice", "price_change", "late_data"]);
const SCENARIOS = [
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

export default function DemoControlBar() {
  const { data: state, mutate } = useApi("/api/state", 1000);
  const me = useMe();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [guideOpen, setGuideOpen] = useState(false);
  const [selection, setSelection] = useState("");

  useEffect(() => {
    const saved = localStorage.getItem(SELECTION_KEY) ?? "";
    if (SCENARIO_VALUES.has(saved)) setSelection(saved);
  }, []);
  useEffect(() => {
    if (!message) return;
    const timeout = setTimeout(() => setMessage(null), 5000);
    return () => clearTimeout(timeout);
  }, [message]);

  const remember = (value: string) => {
    setSelection(value);
    if (value) localStorage.setItem(SELECTION_KEY, value);
    else localStorage.removeItem(SELECTION_KEY);
  };
  const act = async (label: string, action: () => Promise<unknown>) => {
    setBusy(label);
    try {
      await action();
    } catch (error) {
      setMessage(`${label} failed: ${(error as Error).message}`);
    } finally {
      setBusy(null);
      mutate();
    }
  };
  const startGuide = async () => {
    setBusy("Preparing demo");
    try {
      await post("/api/demo/start");
      remember("runaway");
      setGuideOpen(false);
      setMessage("Guided demo started: watch for the automated spend alert");
      mutate();
    } catch (error) {
      setMessage(`Could not start the demo: ${(error as Error).message}`);
    } finally {
      setBusy(null);
    }
  };

  const activeScenarios = Object.entries(state?.scenario ?? {}).filter(([, value]: [string, any]) =>
    value && (typeof value !== "object" || value.active !== false));
  const canControl = allowed(me, "admin");

  return (
    <>
      <section className="rounded-lg border border-line bg-surface px-4 py-3 shadow-sm" aria-labelledby="demo-controls-title">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className={`size-2.5 shrink-0 rounded-full ${state?.paused ? "bg-amber-500" : "bg-green-2"}`} aria-hidden />
            <div className="min-w-0">
              <h1 id="demo-controls-title" className="text-sm font-semibold text-ink">
                {state ? (state.paused ? "Simulation paused" : "Simulation running") : "Connecting to simulation…"}
              </h1>
              <p className="truncate text-[11px] text-ink-3 tabular-nums">
                {state ? `${when(state.sim_now)} · ${Math.round(state.ingest_eps ?? 0).toLocaleString()} events/s` : "Loading demo clock"}
              </p>
            </div>
          </div>

          {canControl && <div className="flex flex-wrap items-center justify-end gap-2">
            {state && (state.paused
              ? <button type="button" className="tu-btn-secondary" disabled={!!busy} onClick={() => act("Play", () => post("/api/sim/play"))}>▶ Play</button>
              : <button type="button" className="tu-btn-secondary" disabled={!!busy} onClick={() => act("Pause", () => post("/api/sim/pause"))}>⏸ Pause</button>)}
            <ScenarioMenu value={selection} busy={busy} onSelect={(value) => {
              if (value.startsWith("ff:")) {
                remember("");
                act("Fast-forward", () => post("/api/sim-fast-forward", { target: value.slice(3) }));
              } else {
                remember(value);
                act("Start scenario", () => post(`/api/scenario/${value}`));
              }
            }} />
            <button type="button" className="tu-btn-secondary" disabled={!!busy}
              title="Rebuild a smooth normal last hour"
              onClick={() => { remember(""); act("Reset baseline", () => post("/api/sim/baseline")); }}>
              ↺ Reset baseline
            </button>
            {activeScenarios.length > 0 && <button type="button" className="tu-btn-secondary text-red-700" disabled={!!busy}
              onClick={() => { remember(""); act("Stop scenario", () => post("/api/scenario/stop")); }}>
              ■ Stop {activeScenarios.length === 1 ? "scenario" : "scenarios"}
            </button>}
            <button type="button" className="tu-btn-primary" disabled={!!busy} onClick={() => setGuideOpen(true)}>
              <span aria-hidden>▶</span> Guided demo
            </button>
          </div>}
        </div>
        {activeScenarios.length > 0 && <div className="mt-2 flex items-center gap-2 border-t border-line pt-2 text-[11px] text-red-700">
          <span className="font-semibold">Active:</span>
          {activeScenarios.map(([name]) => name.replaceAll("_", " ")).join(", ")}
        </div>}
      </section>

      {message && <div role="status" className="fixed right-4 bottom-4 z-50 rounded-lg bg-ink px-4 py-2 text-sm text-white shadow-lg">{message}</div>}
      {guideOpen && <GuidedDemoDialog busy={busy} close={() => setGuideOpen(false)} start={startGuide} />}
    </>
  );
}

function ScenarioMenu({ value, busy, onSelect }: { value: string; busy: string | null; onSelect: (value: string) => void }) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);
  const selected = SCENARIOS.find((scenario) => scenario.value === value);
  useEffect(() => {
    if (!open) return;
    const outside = (event: PointerEvent) => !root.current?.contains(event.target as Node) && setOpen(false);
    const escape = (event: KeyboardEvent) => event.key === "Escape" && setOpen(false);
    document.addEventListener("pointerdown", outside);
    document.addEventListener("keydown", escape);
    return () => { document.removeEventListener("pointerdown", outside); document.removeEventListener("keydown", escape); };
  }, [open]);

  const choose = (next: string) => { setOpen(false); onSelect(next); };
  return <div ref={root} className="relative">
    <button type="button" className={`tu-btn-secondary min-w-[150px] justify-between ${open ? "border-green" : ""}`}
      aria-haspopup="menu" aria-expanded={open} disabled={!!busy} onClick={() => setOpen((current) => !current)}>
      <span className="max-w-[150px] truncate">{busy ?? selected?.label ?? "Trigger scenario"}</span>
      <span aria-hidden className="text-ink-3">⌄</span>
    </button>
    {open && <div role="menu" className="absolute top-[calc(100%+6px)] right-0 z-50 w-[248px] rounded-xl border border-line-2 bg-surface p-1.5 shadow-[0_16px_40px_rgba(22,33,27,0.18)]">
      <div className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] text-ink-3 uppercase">Trigger a scenario</div>
      {SCENARIOS.map((scenario) => <button key={scenario.value} type="button" role="menuitemradio" aria-checked={scenario.value === value}
        onClick={() => choose(scenario.value)} className={`tu-focus flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left ${scenario.value === value ? "bg-green-bg text-green" : "text-ink hover:bg-surface-2"}`}>
        <span aria-hidden className={`mt-1 size-2 shrink-0 rounded-full ${scenario.value === value ? "bg-green" : "border border-line-2"}`} />
        <span><span className="block text-xs font-semibold">{scenario.label}</span><span className="block text-[10px] text-ink-3">{scenario.detail}</span></span>
      </button>)}
      <div className="my-1 border-t border-line" />
      <div className="px-2 py-1.5 text-[10px] font-semibold tracking-[0.1em] text-ink-3 uppercase">Jump the clock</div>
      {TIME_JUMPS.map((jump) => <button key={jump.value} type="button" role="menuitem" onClick={() => choose(jump.value)}
        className="tu-focus flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs font-semibold text-ink hover:bg-surface-2">
        <span aria-hidden className="text-green">»</span>{jump.label}
      </button>)}
    </div>}
  </div>;
}

function GuidedDemoDialog({ busy, close, start }: { busy: string | null; close: () => void; start: () => void }) {
  return <div className="fixed inset-0 z-50 flex items-center justify-center bg-ink/40 p-4" role="dialog" aria-modal="true" aria-labelledby="guided-demo-title" onMouseDown={(event) => event.target === event.currentTarget && close()}>
    <div className="w-full max-w-2xl rounded-xl bg-surface p-6 shadow-2xl">
      <div className="flex items-start gap-4">
        <div className="flex size-11 shrink-0 items-center justify-center rounded-lg bg-green text-xl text-white">▶</div>
        <div className="flex-1"><div className="tu-eyebrow text-green">Guided product demo · about 3 minutes</div><h2 id="guided-demo-title" className="mt-1 font-serif text-3xl text-ink">See the AI spend control loop</h2><p className="mt-2 text-ink-2">Catch a runaway agent, close unbilled spend, then reconcile an invoice discrepancy.</p></div>
        <button type="button" className="tu-focus rounded text-2xl leading-none text-ink-3 hover:text-ink" aria-label="Close" onClick={close}>×</button>
      </div>
      <ol className="mt-6 grid gap-3 sm:grid-cols-3">
        <GuideStep number="1" label="Detect" title="Catch runaway spend" copy="An 80× retry loop is detected against the live baseline." />
        <GuideStep number="2" label="Close" title="Accrue the month" copy="Usage, contracts, and purchases become evidence-backed cases." />
        <GuideStep number="3" label="Learn" title="Reconcile invoices" copy="A price discrepancy becomes a replayable rule." />
      </ol>
      <div className="mt-6 flex flex-wrap items-center justify-between gap-3 border-t border-line pt-4">
        <p className="text-xs text-ink-3">Starting resets the synthetic data and removes the current run.</p>
        <div className="flex gap-2"><button type="button" className="tu-btn-secondary" onClick={close}>Cancel</button><button type="button" className="tu-btn-primary px-5" disabled={!!busy} onClick={start}>{busy ?? "Start guided demo"}</button></div>
      </div>
    </div>
  </div>;
}

function GuideStep({ number, label, title, copy }: { number: string; label: string; title: string; copy: string }) {
  return <li className="rounded-lg border border-line p-3"><div className="text-xs font-semibold text-green">{number} · {label.toUpperCase()}</div><div className="mt-1 font-semibold text-ink">{title}</div><p className="mt-1 text-sm text-ink-2">{copy}</p></li>;
}
