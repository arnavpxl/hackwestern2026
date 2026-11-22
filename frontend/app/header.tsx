"use client";
import Link from "next/link";
import Image from "next/image";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { API, get, post, usd, useApi } from "@/lib/api";
import { useMe } from "./auth-gate";

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
  const { data: s } = useApi(demoMode ? "/api/state" : null, 1000);
  const me = useMe();
  const [toast, setToast] = useState<string | null>(null);
  const [runawayAlert, setRunawayAlert] = useState<RunawayAlert | null>(null);
  const [navOpen, setNavOpen] = useState(false);
  const root = demoMode ? "/demo" : "/app";
  const nav = demoMode
    ? [[root, "Spend monitoring"], [`${root}/close`, "Month-end close"], [`${root}/recon`, "Invoice reconciliation"], [`${root}/uth`, "How it works"]]
    : [[root, "Overview"], [`${root}/connections`, "Connections"]];
  const navLabel = demoMode ? "Synthetic demo" : "Your workspace";

  useEffect(() => setNavOpen(false), [path]);

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

  const signOut = async () => {
    await post("/api/auth/logout").catch(() => {});
    window.location.reload();
  };

  const active = (href: string) => path === href || (href === `${root}/close` && path.startsWith(`${root}/cases/`));
  const live = s?.llm_mode === "live";

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
        {demoMode && <div className="mb-1 rounded-lg border border-amber-line bg-amber-bg px-2.5 py-2">
          <div className="text-[11px] font-semibold text-amber">Synthetic demo</div>
          <div className="mt-0.5 text-[10px] leading-snug text-ink-2">Simulated providers, usage, invoices, and spend</div>
        </div>}

        <nav aria-label={navLabel} className="mt-3 flex flex-col gap-0.5 border-t border-line pt-3">
          <h2 className="mb-1 px-2.5 text-[10px] font-semibold tracking-[0.1em] text-ink-3 uppercase">{navLabel}</h2>
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

        {!demoMode && (
          <section className="mt-4 rounded-lg border border-amber-line bg-amber-bg p-3" aria-labelledby="product-demo-title">
            <h2 id="product-demo-title" className="text-xs font-semibold text-ink">Explore the full product</h2>
            <p className="mt-1 text-[11px] leading-snug text-ink-2">
              Provider APIs report hourly usage. The synthetic demo shows real-time detection, close, and reconciliation with simulated direct telemetry.
            </p>
            <Link href="/demo" className="tu-focus mt-2 inline-flex rounded text-xs font-semibold text-green hover:underline">
              Open product demo →
            </Link>
          </section>
        )}

        {demoMode && (
          <Link href={me?.email === "demo@tokentrueup.local" ? "/" : "/app"}
            className="tu-focus mt-3 flex items-center gap-2 rounded-lg px-2.5 py-2 text-xs font-semibold text-green hover:bg-green-bg">
            <span aria-hidden>←</span>
            {me?.email === "demo@tokentrueup.local" ? "Leave demo" : "Return to your workspace"}
          </Link>
        )}

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
    </aside>
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
