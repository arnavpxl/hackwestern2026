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
  const { data: s } = useApi(demoMode ? "/api/state" : null, 15_000);
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
    const alertTimers = new Set<ReturnType<typeof setTimeout>>();
    const es = new EventSource(`${API}/api/events`, { withCredentials: true });
    es.addEventListener("case", (e) => {
      try {
        const d = JSON.parse((e as MessageEvent).data);
        if (d.event === "anomaly_opened") {
          const initial = { caseId: Number(d.case_id), apiKeyId: Number(d.api_key_id) };
          get(`/api/cases/${d.case_id}`).then((payload) => {
            const c = payload.case;
            const calc = c?.calc?.estimate ?? c?.calc ?? {};
            return {
              ...initial,
              keyLabel: c?.key_label,
              model: calc.model,
              projectedHourlyCents: Number(calc.projected_hourly_cents),
              baselineHourlyCents: Number(calc.baseline_mean_cents),
            };
          }).catch(() => initial).then((alert) => {
            const timer = setTimeout(() => {
              alertTimers.delete(timer);
              setRunawayAlert(alert);
            }, 5000);
            alertTimers.add(timer);
          });
        }
        if (d.event === "invoices_received") setToast("Provider invoices received");
        if (d.event === "demo_email_sent" && Number(d.user_id) === me?.id) {
          setToast("Runaway alert emailed to your account");
        }
      } catch {}
    });
    return () => {
      es.close();
      alertTimers.forEach(clearTimeout);
    };
  }, [demoMode, me?.id]);
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
        {demoMode && <p className="mb-1 rounded-lg bg-amber-bg px-2.5 py-1.5 text-xs text-amber">Demo · all data is simulated</p>}

        <nav aria-label={navLabel} className="mt-3 flex flex-col gap-0.5">
          {nav.map(([href, label]) => (
            <Link key={href} href={href} aria-current={active(href) ? "page" : undefined}
              className={`tu-focus rounded-lg px-2.5 py-2 text-sm ${active(href)
                ? "bg-surface text-ink shadow-[inset_0_0_0_1px_var(--color-line)]"
                : "text-ink-2 hover:bg-surface-2 hover:text-ink"}`}>
              {label}
            </Link>
          ))}
        </nav>

        {!demoMode && (
          <Link href="/demo" className="tu-focus mt-4 rounded-lg px-2.5 py-2 text-sm text-green hover:bg-green-bg">
            Try the demo
          </Link>
        )}

        {demoMode && (
          <Link href={me?.email === "demo@tokentrueup.local" ? "/" : "/app"}
            className="tu-focus mt-4 rounded-lg px-2.5 py-2 text-sm text-green hover:bg-green-bg">
            {me?.email === "demo@tokentrueup.local" ? "Leave demo" : "Back to your workspace"}
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
              <span className="min-w-0 truncate">{me.name} · {me.role}</span>
              <button type="button" className="tu-focus rounded text-green hover:underline" onClick={signOut}>Sign out</button>
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
    <div className="fixed inset-x-4 top-4 z-[70] ml-auto max-w-[420px] rounded-xl border-l-4 border-red-600 bg-white p-5 shadow-[0_16px_48px_rgba(127,29,29,0.22)]"
      role="alert" aria-live="assertive" aria-labelledby="runaway-alert-title" aria-describedby="runaway-alert-description">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 id="runaway-alert-title" className="font-serif text-xl leading-tight text-red-700">Runaway spend detected</h2>
          <p id="runaway-alert-description" className="mt-1 text-sm text-ink-2">
            {alert.keyLabel ? <><span className="font-mono text-ink">{alert.keyLabel}</span>{alert.model ? <> on {alert.model}</> : null}</> : "A key is spending far above normal."}
          </p>
        </div>
        <button type="button" onClick={dismiss} aria-label="Dismiss runaway spend alert"
          className="tu-focus -mt-1 rounded p-1 text-2xl leading-none text-ink-3 hover:text-ink">×</button>
      </div>

      {projected != null && baseline != null && (
        <div className="mt-4 grid grid-cols-3 divide-x divide-red-100 rounded-lg bg-red-50 py-2.5">
          <AlertMetric label="Now" value={`${usd(projected)}/h`} />
          <AlertMetric label="Normal" value={`${usd(baseline)}/h`} />
          <AlertMetric label="Increase" value={multiple == null ? "—" : `${multiple}×`} danger />
        </div>
      )}

      <div className="mt-4 flex items-center gap-2">
        <Link href={`${caseRoot}/${alert.caseId}`} onClick={dismiss} className="tu-btn flex-1 bg-red-700 text-white hover:bg-red-800">
          Open case #{alert.caseId}
        </Link>
        <button type="button" onClick={dismiss} className="tu-btn-ghost">Dismiss</button>
      </div>
    </div>
  );
}

function AlertMetric({ label, value, danger = false }: { label: string; value: string; danger?: boolean }) {
  return (
    <div className="min-w-0 px-3 text-center">
      <div className="text-xs text-ink-3">{label}</div>
      <div className={`mt-1 truncate text-sm font-medium tabular-nums ${danger ? "text-red-700" : "text-ink"}`}>{value}</div>
    </div>
  );
}
