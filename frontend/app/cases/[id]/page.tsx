"use client";
import { use, useState } from "react";
import { post, usd, useApi, when } from "@/lib/api";
import Status from "../../status";

export default function CaseDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, mutate } = useApi(`/api/cases/${id}`);
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState(false);
  const [reruns, setReruns] = useState<Record<number, any>>({});
  if (!data) return <div className="card">Loading…</div>;
  const c = data.case;
  const calc = c.calc?.estimate ?? c.calc;
  const queries: any[] = calc?.queries ?? [];
  const exp = c.explanation;

  const send = async () => {
    setBusy(true);
    try { await post(`/api/cases/${id}/reply`, { body: reply }); setReply(""); } finally { setBusy(false); mutate(); }
  };
  const rerun = async (i: number) => setReruns({ ...reruns, [i]: await post(`/api/cases/${id}/rerun/${i}`) });

  return (
    <>
      <div className="card">
        <div className="flex flex-wrap items-center gap-3">
          <h1 className="text-xl font-semibold">{c.title}</h1><Status s={c.status} />
          {c.status === "pending_approval" && <button className="btn-primary" onClick={async () => { await post(`/api/cases/${id}/approve`); mutate(); }}>Approve</button>}
        </div>
        <div className="mt-1 text-sm text-slate-600">
          {c.type} · {c.provider_name}{c.key_label && <> · key <span className="font-mono">{c.key_label}</span></>} · opened {when(c.opened_at)}
        </div>
        <div className="mt-3 text-3xl font-semibold tabular-nums">{usd(c.estimate_cents)}
          {c.confidence != null && <span className="ml-2 text-base font-normal text-slate-500">{Math.round(c.confidence * 100)}% confidence</span>}</div>
      </div>

      {exp && (
        <div className="card">
          <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
            Explanation · agent {exp.agent?.mode} · {exp.agent?.verified ? "✓ every number verified against the query results" : "fallback text"}
          </div>
          <div className="font-medium">{exp.headline}</div>
          <ul className="mt-1 list-disc pl-5 text-sm">{exp.bullets?.map((b: string, i: number) => <li key={i}>{b}</li>)}</ul>
        </div>
      )}

      {data.outreach.length > 0 && (
        <div className="card space-y-2">
          <h2 className="font-semibold">Outreach</h2>
          {data.outreach.map((m: any) => (
            <div key={m.id} className={`rounded p-2 text-sm ${m.direction === "out" ? "bg-slate-50" : "bg-indigo-50"}`}>
              <div className="text-xs text-slate-500">{m.direction === "out" ? `to ${m.owner_name ?? "?"} <${m.email ?? "?"}>` : "reply"}</div>
              {m.body}
            </div>
          ))}
          <div className="flex gap-2">
            <input className="flex-1 rounded border border-slate-300 px-2 py-1 text-sm" placeholder="Reply as the key owner…"
              value={reply} onChange={(e) => setReply(e.target.value)} />
            <button className="btn-primary" disabled={!reply || busy} onClick={send}>{busy ? "Interpreting…" : "Send reply"}</button>
          </div>
        </div>
      )}

      <div className="card space-y-3">
        <h2 className="font-semibold">How the number was computed</h2>
        {calc?.summary && <p className="text-sm">{calc.summary}</p>}
        {queries.map((q, i) => (
          <div key={i}>
            <div className="mb-1 flex items-center gap-2 text-xs text-slate-500">
              Query {i + 1} · {q.ms?.toFixed(1)} ms · {q.rows?.length} rows
              <button className="btn" onClick={() => rerun(i)}>Re-run</button>
              {reruns[i] && <span className={reruns[i].matches_stored ? "text-emerald-700" : "text-rose-700"}>
                {reruns[i].matches_stored ? `✓ same result (${reruns[i].ms} ms)` : `result changed since close (${reruns[i].ms} ms)`}</span>}
            </div>
            <pre className="sql">{q.sql.trim()}</pre>
          </div>
        ))}
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">Audit trail</h2>
        <table className="tbl">
          <thead><tr><th>When</th><th>Actor</th><th>Action</th><th>Detail</th></tr></thead>
          <tbody>{data.audit.map((a: any) => (
            <tr key={a.id}><td className="whitespace-nowrap">{when(a.ts)}</td><td>{a.actor}</td><td>{a.action}</td>
              <td className="max-w-xl truncate font-mono text-xs" title={JSON.stringify(a.detail)}>{JSON.stringify(a.detail)}</td></tr>
          ))}</tbody>
        </table>
      </div>
    </>
  );
}
