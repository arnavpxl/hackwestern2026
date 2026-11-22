"use client";

import { useEffect, useRef, useState } from "react";
import { post, useApi, when } from "@/lib/api";
import { allowed, useMe } from "@/app/auth-gate";

const SELECTION_KEY = "ttu-simulation-selection";
const SCENARIO_VALUES = new Set(["runaway", "stealth_price", "duplicate_invoice", "price_change", "late_data"]);
const SCENARIOS = [
  { value: "runaway", label: "Runaway agent", detail: "Support triage" },
  { value: "stealth_price", label: "Hidden price change", detail: "Nimbus" },
  { value: "duplicate_invoice", label: "Duplicate invoice", detail: "Stratus" },
  { value: "price_change", label: "Announced price change", detail: "Cortexa" },
  { value: "late_data", label: "Late usage data", detail: "Helio" },
] as const;
const TIME_JUMPS = [
  { value: "ff:month_end", label: "Skip to month end" },
  { value: "ff:invoices", label: "Skip to invoices" },
] as const;

export default function DemoControlBar() {
  const { data: state, mutate } = useApi("/api/state", 1000);
  const me = useMe();
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);
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
  const activeScenarios = Object.entries(state?.scenario ?? {}).filter(([, value]: [string, any]) =>
    value && (typeof value !== "object" || value.active !== false));
  const canControl = allowed(me, "admin");

  return (
    <>
      <section className="rounded-[10px] border border-line bg-surface px-4 py-3" aria-labelledby="demo-controls-title">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div className="flex min-w-0 items-center gap-3">
            <span className={`size-2.5 shrink-0 rounded-full ${state?.paused ? "bg-amber-500" : "bg-green-2"}`} aria-hidden />
            <div className="min-w-0">
              <h1 id="demo-controls-title" className="text-sm font-medium text-ink">
                {state ? (state.paused ? "Simulation paused" : "Simulation running") : "Connecting to simulation…"}
              </h1>
              <p className="truncate text-[11px] text-ink-3 tabular-nums">
                {state ? `${when(state.sim_now)} · ${Math.round(state.ingest_eps ?? 0).toLocaleString()} events/s` : "Loading demo clock"}
              </p>
            </div>
          </div>

          {canControl && <div className="flex flex-wrap items-center justify-end gap-2">
            {state && (state.paused
              ? <button type="button" className="tu-btn-secondary" disabled={!!busy} onClick={() => act("Play", () => post("/api/sim/play"))}>Play</button>
              : <button type="button" className="tu-btn-secondary" disabled={!!busy} onClick={() => act("Pause", () => post("/api/sim/pause"))}>Pause</button>)}
            <ScenarioMenu value={selection} busy={busy} onSelect={(value) => {
              if (value.startsWith("ff:")) {
                remember("");
                act("Fast-forward", () => post("/api/sim-fast-forward", { target: value.slice(3) }));
              } else {
                remember(value);
                act("Start scenario", () => post(`/api/scenario/${value}`));
              }
            }} />
            <button type="button" className="tu-btn-ghost" disabled={!!busy}
              title="Rebuild a smooth normal last hour"
              onClick={() => { remember(""); act("Reset baseline", () => post("/api/sim/baseline")); }}>
              Reset baseline
            </button>
            {activeScenarios.length > 0 && <button type="button" className="tu-btn-ghost text-red-700 hover:text-red-800" disabled={!!busy}
              onClick={() => { remember(""); act("Stop scenario", () => post("/api/scenario/stop")); }}>
              Stop {activeScenarios.length === 1 ? "scenario" : "scenarios"}
            </button>}
          </div>}
        </div>
        {activeScenarios.length > 0 && <div className="mt-2 flex items-center gap-2 border-t border-line pt-2 text-[11px] text-red-700">
          <span>Running:</span>
          {activeScenarios.map(([name]) => name.replaceAll("_", " ")).join(", ")}
        </div>}
      </section>

      {message && <div role="status" className="fixed right-4 bottom-4 z-50 rounded-lg bg-ink px-4 py-2 text-sm text-white shadow-lg">{message}</div>}
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
      <span className="max-w-[150px] truncate">{busy ?? selected?.label ?? "Scenarios"}</span>
      <span aria-hidden className="text-ink-3">⌄</span>
    </button>
    {open && <div role="menu" className="absolute top-[calc(100%+6px)] right-0 z-50 w-[248px] rounded-xl border border-line-2 bg-surface p-1.5 shadow-[0_16px_40px_rgba(22,33,27,0.18)]">
      <div className="px-2 py-1.5 text-xs text-ink-3">Scenarios</div>
      {SCENARIOS.map((scenario) => <button key={scenario.value} type="button" role="menuitemradio" aria-checked={scenario.value === value}
        onClick={() => choose(scenario.value)} className={`tu-focus flex w-full items-start gap-2 rounded-lg px-2 py-2 text-left ${scenario.value === value ? "bg-green-bg text-green" : "text-ink hover:bg-surface-2"}`}>
        <span aria-hidden className={`mt-1 size-2 shrink-0 rounded-full ${scenario.value === value ? "bg-green" : "border border-line-2"}`} />
        <span><span className="block text-sm">{scenario.label}</span><span className="block text-xs text-ink-3">{scenario.detail}</span></span>
      </button>)}
      <div className="my-1 border-t border-line" />
      <div className="px-2 py-1.5 text-xs text-ink-3">Skip ahead</div>
      {TIME_JUMPS.map((jump) => <button key={jump.value} type="button" role="menuitem" onClick={() => choose(jump.value)}
        className="tu-focus flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-sm text-ink hover:bg-surface-2">
        {jump.label}
      </button>)}
    </div>}
  </div>;
}
