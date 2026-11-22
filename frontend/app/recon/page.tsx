"use client";
import { useState } from "react";
import { post, usd, useApi, when } from "@/lib/api";
import { allowed, useMe } from "../auth-gate";
import Status from "../status";
import LoadingState from "@/components/LoadingState";

export default function Recon() {
  const { data, mutate } = useApi("/api/recon");
  const me = useMe();
  const [busy, setBusy] = useState<string | null>(null);
  if (!data) return <LoadingState label="Loading reconciliation" detail="Fetching invoices, variances, and learned rules…" />;
  const act = async (label: string, path: string) => { setBusy(label); try { await post(path); } finally { setBusy(null); mutate(); } };
  const period = String(data.period);
  const current = data.invoices.filter((i: any) => String(i.period_start) >= period);
  const pending = current.filter((i: any) => i.status === "received").length;

  return (
    <>
      <div className="card flex flex-wrap items-center gap-4">
        <div>
          <h1 className="text-lg font-semibold">Invoices for {period.slice(0, 7)}</h1>
          <div className="text-sm text-slate-600">
            {current.length === 0 ? "None yet. Fast-forward to invoices from the Simulate menu." : `${current.length} received, ${pending} waiting to reconcile`}
          </div>
        </div>
        <button className="btn-primary ml-auto" disabled={!pending || !!busy || !allowed(me, "controller")} onClick={() => act("recon", "/api/recon/run")}>
          {busy === "recon" ? "Reconciling…" : "Reconcile"}
        </button>
      </div>

      {current.map((inv: any) => {
        const r = inv.recon ?? {};
        return (
          <div key={inv.id} className="card">
            <div className="flex flex-wrap items-center gap-3">
              <span className="font-mono text-sm">{inv.invoice_no}</span><span>{inv.provider_id}</span><Status s={inv.status} />
              <span className="ml-auto text-lg font-semibold tabular-nums">{usd(inv.amount_cents)}</span>
            </div>
            <div className="text-xs text-slate-500">received {when(inv.received_at)}</div>
            {r.duplicate_of && <p className="mt-2 text-sm text-rose-700">Duplicate of {r.duplicate_of_invoice_no}: {r.detail}. Not paid twice.</p>}
            {r.variance_cents != null && (
              <div className="mt-2 text-sm">
                <div>Accrued {usd(r.accrued_cents)} · variance <b className={Math.abs(r.variance_pct) > 1 ? "text-rose-700" : ""}>{usd(r.variance_cents)} ({r.variance_pct}%)</b></div>
                {r.narrative && <div className="mt-1 text-slate-700">{r.narrative.summary}</div>}
                <ul className="mt-1 list-disc pl-5">{(r.causes ?? []).map((c: any, i: number) => <li key={i}><b>{c.cause.replace(/_/g, " ")}</b> ({usd(c.amount_cents)}): {c.detail}</li>)}</ul>
              </div>
            )}
          </div>
        );
      })}

      <div className="card">
        <h2 className="mb-2 font-semibold">Learned rules</h2>
        {data.rules.length === 0 && <p className="text-sm text-slate-500">Reconciliation proposes rules when it can explain a variance.</p>}
        <div className="space-y-4">
          {data.rules.map((rule: any) => (
            <div key={rule.id} className="rounded border border-slate-200 p-3">
              <div className="flex flex-wrap items-center gap-2">
                <b>#{rule.id} {rule.kind.replace(/_/g, " ")}</b><span className="text-sm">{rule.provider_id}</span><Status s={rule.status} />
                <span className="font-mono text-xs text-slate-500">{JSON.stringify(rule.params)}</span>
                {rule.status === "proposed" && allowed(me, "controller") && <span className="ml-auto flex gap-2">
                  <button className="btn" disabled={!!busy} onClick={() => act(`r${rule.id}`, `/api/rules/${rule.id}/replay`)}>Replay</button>
                  <button className="btn-primary" disabled={!!busy} onClick={() => act(`a${rule.id}`, `/api/rules/${rule.id}/activate`)}>Activate</button>
                  <button className="btn" disabled={!!busy} onClick={() => act(`x${rule.id}`, `/api/rules/${rule.id}/reject`)}>Reject</button>
                </span>}
              </div>
              <p className="mt-1 text-sm text-slate-700">{rule.rationale}</p>
              {rule.replay && (
                <table className="tbl mt-2 max-w-2xl">
                  <thead><tr><th>Month</th><th className="num">Invoice</th><th className="num">Accrual before</th><th className="num">Error before</th><th className="num">Accrual with rule</th><th className="num">Error with rule</th></tr></thead>
                  <tbody>{rule.replay.months.map((m: any) => (
                    <tr key={m.period}><td>{m.period.slice(0, 7)}</td><td className="num">{usd(m.invoice_cents)}</td>
                      <td className="num">{usd(m.before_cents)}</td><td className="num">{m.before_err_pct}%</td>
                      <td className="num">{usd(m.after_cents)}</td><td className="num font-semibold">{m.after_err_pct}%</td></tr>
                  ))}</tbody>
                  <tfoot><tr><td colSpan={6} className="pt-1 text-xs text-slate-500">Replayed in {rule.replay.ms} ms on {rule.replay.source}. Mean abs. error {rule.replay.mape_before}% → {rule.replay.mape_after}%.</td></tr></tfoot>
                </table>
              )}
            </div>
          ))}
        </div>
      </div>

      <details className="card">
        <summary className="cursor-pointer font-semibold">Earlier invoices ({data.invoices.length - current.length})</summary>
        <table className="tbl mt-2"><tbody>{data.invoices.filter((i: any) => String(i.period_start) < period).map((i: any) => (
          <tr key={i.id}><td className="font-mono text-xs">{i.invoice_no}</td><td>{i.provider_id}</td><td className="num">{usd(i.amount_cents)}</td><td><Status s={i.status} /></td></tr>
        ))}</tbody></table>
      </details>
    </>
  );
}
