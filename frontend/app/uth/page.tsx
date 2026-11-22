"use client";
import { useState } from "react";
import { post, useApi, when } from "@/lib/api";
import { allowed, useMe } from "../auth-gate";
import LoadingState from "@/components/LoadingState";

const mb = (b: number | null | undefined) => (b ? `${(b / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })} MB` : "—");

export default function UnderTheHood() {
  const { data: s } = useApi("/api/uth/stats", 3000);
  const [race, setRace] = useState<any>(null);
  const [fresh, setFresh] = useState<any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const me = useMe();
  const go =async (k: string, fn: () => Promise<void>) => { setBusy(k); try { await fn(); } finally { setBusy(null); } };
  if (!s) return <LoadingState label="Loading system details" detail="Fetching ingestion, storage, and detection metrics…" />;

  return (
    <>
      <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
        <Tile label="Usage events" value={Number(s.usage_rows).toLocaleString()} sub={`${s.chunks} daily chunks, ${s.compressed_chunks} in columnstore`} />
        <Tile label="Live ingest" value={`${Math.round(s.ingest_eps ?? 0).toLocaleString()} ev/s`} sub={s.paused ? "paused" : "streaming"} />
        {s.columnstore.filter((c: any) => c.name === "usage_events").map((c: any) => (
          <Tile key="c" label="Columnstore, raw events" value={`${c.ratio_pct ?? "—"}% smaller`} sub={`${mb(c.before)} → ${mb(c.after)}`} />
        ))}
        <Tile label="Last anomaly detection" value={s.anomaly_latency[0] ? `${(s.anomaly_latency[0].detection_latency_ms / 1000).toFixed(1)} s` : "—"} sub="spike to case opened" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2">
        <div className="card">
          <div className="flex items-center gap-2">
            <h2 className="font-serif text-xl">Query speed</h2>
            <button className="btn ml-auto" disabled={!!busy || !allowed(me, "admin")} onClick={() => go("race", async () => setRace(await post("/api/uth/race")))}>{busy === "race" ? "Running…" : "Run"}</button>
          </div>
          {race ? (
            <div className="mt-3 space-y-2 text-sm">
              <Bar label="Raw hypertable" ms={race.raw.ms} max={race.raw.ms} color="bg-slate-400" />
              <Bar label="usage_1d continuous aggregate" ms={race.cagg.ms} max={race.raw.ms} color="bg-green-2" />
              <p className="text-ink-2">{race.speedup}× faster · totals match: {race.totals_match ? "yes" : "no"}</p>
            </div>
          ) : <p className="mt-3 text-sm text-ink-3">Same query on raw events vs. the daily rollup.</p>}
        </div>
        <div className="card">
          <div className="flex items-center gap-2">
            <h2 className="font-serif text-xl">Freshness</h2>
            <button className="btn ml-auto" disabled={!!busy || !allowed(me, "admin")} onClick={() => go("fresh", async () => setFresh(await post("/api/uth/freshness")))}>{busy === "fresh" ? "Running…" : "Run"}</button>
          </div>
          {fresh ? <p className="mt-3 text-sm text-ink-2">A new event showed up after {fresh.visible_after_ms} ms.</p>
            : <p className="mt-3 text-sm text-ink-3">Time for a new event to show up.</p>}
        </div>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-serif text-xl">Compression</h2>
        <table className="tbl"><thead><tr><th>Table</th><th className="num">Before</th><th className="num">After</th><th className="num">Smaller</th><th className="num">Chunks compressed</th></tr></thead>
          <tbody>{s.columnstore.map((c: any) => (
            <tr key={c.name}><td className="font-mono text-xs">{c.name}</td><td className="num">{mb(c.before)}</td><td className="num">{mb(c.after)}</td>
              <td className="num">{c.ratio_pct != null ? `${c.ratio_pct}%` : "—"}</td><td className="num">{c.number_compressed_chunks ?? 0}/{c.total_chunks ?? 0}</td></tr>
          ))}</tbody></table>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-serif text-xl">Rollups</h2>
        <table className="tbl"><thead><tr><th>View</th><th>Real-time</th><th>Watermark</th><th>Refresh every</th><th>Last refresh</th></tr></thead>
          <tbody>{s.caggs.map((c: any) => (
            <tr key={c.view_name}><td className="font-mono text-xs">{c.view_name}</td><td>{c.materialized_only ? "no" : "yes"}</td>
              <td>{when(c.watermark)}</td><td>{c.every ?? "—"}</td><td>{when(c.last_refresh)}</td></tr>
          ))}</tbody></table>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-serif text-xl">Background jobs</h2>
        <table className="tbl"><thead><tr><th>Job</th><th>Target</th><th>Every</th><th>Status</th><th className="num">Runs</th><th className="num">Failures</th><th className="num">Last ms</th></tr></thead>
          <tbody>{s.jobs.map((j: any) => (
            <tr key={j.job_id}><td>{j.proc_name}</td><td className="font-mono text-xs">{j.target || "—"}</td><td>{j.every}</td><td>{j.last_run_status ?? "—"}</td>
              <td className="num">{j.total_runs}</td><td className="num">{j.total_failures}</td><td className="num">{j.last_ms ?? "—"}</td></tr>
          ))}</tbody></table>
      </div>
    </>
  );
}

function Tile({ label, value, sub }: { label: string; value: string; sub: string }) {
  return <div className="card"><div className="text-xs text-ink-3">{label}</div>
    <div className="mt-1 font-serif text-2xl tabular-nums">{value}</div><div className="text-xs text-ink-3">{sub}</div></div>;
}

function Bar({ label, ms, max, color }: { label: string; ms: number; max: number; color: string }) {
  return <div><div className="flex justify-between text-xs"><span>{label}</span><span className="tabular-nums">{ms} ms</span></div>
    <div className="h-3 rounded bg-slate-100"><div className={`h-3 rounded ${color}`} style={{ width: `${Math.max(0.5, (ms / max) * 100)}%` }} /></div></div>;
}
