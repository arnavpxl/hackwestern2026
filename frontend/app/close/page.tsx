"use client";
import Link from "next/link";
import { useState } from "react";
import { post, usd, useApi, when } from "@/lib/api";
import { allowed, useMe } from "../auth-gate";
import Status from "../status";

export default function Close() {
  const { data, mutate } = useApi("/api/close/summary");
  const me = useMe();
  const [busy, setBusy] = useState(false);
  if (!data) return <div className="card">Loading…</div>;

  const run = async () => { setBusy(true); try { await post("/api/close/run"); } finally { setBusy(false); mutate(); } };
  const approve = async (id: number) => { await post(`/api/cases/${id}/approve`); mutate(); };

  return (
    <>
      <div className="card flex flex-wrap items-center gap-6">
        <div>
          <div className="text-xs uppercase tracking-wide text-slate-500">Close period {String(data.period).slice(0, 7)}</div>
          <div className="text-2xl font-semibold tabular-nums">{usd(data.accrued_cents)} <span className="text-base font-normal text-slate-500">accrued</span></div>
          <div className="text-sm text-slate-600">{usd(data.approved_cents)} approved · materiality {usd(data.materiality_cents)} · as of {when(data.sim_now)}</div>
        </div>
        <div className="flex flex-wrap gap-2">
          {Object.entries(data.by_status).map(([k, v]) => <span key={k}><Status s={k} /> {String(v)}</span>)}
        </div>
        <button className="btn-primary ml-auto" disabled={busy || !allowed(me, "controller")} onClick={run}>{busy ? "Running close…" : "Run close"}</button>
      </div>

      <div className="card overflow-x-auto">
        <table className="tbl">
          <thead><tr><th>#</th><th>Type</th><th>Case</th><th>Provider</th><th className="num">Estimate</th><th className="num">Conf.</th><th>Status</th><th></th></tr></thead>
          <tbody>
            {data.cases.length === 0 && <tr><td colSpan={8} className="py-6 text-center text-slate-500">No cases yet. Press "Run close".</td></tr>}
            {data.cases.map((c: any) => (
              <tr key={c.id} className={c.type === "anomaly" ? "bg-rose-50/50" : ""}>
                <td className="text-slate-400">{c.id}</td>
                <td>{c.type}</td>
                <td><Link className="text-indigo-700 hover:underline" href={`/cases/${c.id}`}>{c.title}</Link>
                  {c.detection_latency_ms != null && <div className="text-xs text-slate-500">detected {(c.detection_latency_ms / 1000).toFixed(1)} s after the spike began</div>}</td>
                <td>{c.provider_id}</td>
                <td className="num">{usd(c.estimate_cents)}</td>
                <td className="num">{c.confidence != null ? `${Math.round(c.confidence * 100)}%` : "—"}</td>
                <td><Status s={c.status} /></td>
                <td>{c.status === "pending_approval" && allowed(me, "controller") && <button className="btn" onClick={() => approve(c.id)}>Approve</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
