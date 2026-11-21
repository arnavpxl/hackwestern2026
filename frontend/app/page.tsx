"use client";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dollars, useApi } from "@/lib/api";

const COLORS = ["#4f46e5", "#0891b2", "#d97706", "#db2777", "#16a34a"];

function pivot(rows: any[], key: string, fmt: (v: string) => string) {
  const by = new Map<string, any>();
  const teams = new Set<string>();
  for (const r of rows ?? []) {
    const k = fmt(r[key]);
    teams.add(r.team);
    by.set(k, { ...(by.get(k) ?? { t: k }), [r.team]: Number(r.dollars) });
  }
  const sortedTeams = [...teams].sort();
  const data = [...by.values()].map((point) => {
    for (const team of sortedTeams) point[team] ??= 0;
    return point;
  });
  return { data, teams: sortedTeams };
}

const hhmm = (ts: string) => new Date(ts).toISOString().slice(11, 16);
const day = (d: string) => String(d).slice(5, 10);

function minutePivot(rows: any[], teams: string[], simNow: string, minutes = 60) {
  const end = new Date(simNow);
  end.setUTCSeconds(0, 0);
  const by = new Map<number, any>();

  for (let i = minutes - 1; i >= 0; i--) {
    const ts = end.getTime() - i * 60_000;
    // A missing aggregate bucket means ingestion stopped. Keep it null so Recharts
    // breaks the area instead of drawing a misleading fall to $0 and back.
    by.set(ts, Object.fromEntries([["t", hhmm(new Date(ts).toISOString())], ...teams.map((team) => [team, null])]));
  }

  for (const row of rows ?? []) {
    const bucket = new Date(row.bucket);
    bucket.setUTCSeconds(0, 0);
    const point = by.get(bucket.getTime());
    if (point && teams.includes(row.team)) point[row.team] = Number(row.dollars);
  }

  return { data: [...by.values()], teams };
}

export default function LiveSpend() {
  const { data, error } = useApi("/api/spend/live?minutes=60");
  if (error) return <div className="card text-red-700">API unreachable: {String(error.message)}. Is `make demo` running?</div>;
  if (!data) return <div className="card">Loading…</div>;
  const teams = [...new Set<string>(data.keys.map((key: any) => key.team))].sort();
  const minute = minutePivot(data.series, teams, data.sim_now);
  const daily = pivot(data.daily, "day", day);
  const mtd = data.keys.reduce((a: number, k: any) => a + Number(k.mtd_dollars), 0);
  const proj = data.keys.reduce((a: number, k: any) => a + Number(k.projected_month_end), 0);
  const burn = data.keys.reduce((a: number, k: any) => a + Number(k.run_rate_hourly), 0);
  const pauses = data.pauses ?? [];

  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Month-to-date usage spend" value={dollars(mtd)} />
        <Stat label="Projected at month end" value={dollars(proj)} />
        <Stat label="Current burn rate (last 5 min)" value={`${dollars(burn)}/h`} />
      </div>

      <div className="card">
        <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
          <h2 className="font-semibold">Spend per minute, last hour (usage_1m, real-time aggregate)</h2>
          {data.paused && <span className="pill bg-amber-100 text-amber-800">Paused · simulation clock frozen</span>}
        </div>
        <ResponsiveContainer width="100%" height={260}>
          <AreaChart data={minute.data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="t" fontSize={11} />
            <YAxis fontSize={11} tickFormatter={(v) => `$${v}`} />
            <Tooltip formatter={(v: number) => dollars(v)} />
            <Legend />
            {pauses.map((p: any, i: number) => {
              const seconds = Number(p.duration_seconds);
              const duration = seconds < 60 ? `${Math.max(1, Math.round(seconds))}s` : `${Math.round(seconds / 60)}m`;
              return <ReferenceLine key={`${p.sim_at}-${i}`} x={hhmm(p.sim_at)} stroke="#d97706" strokeDasharray="4 4"
                label={{ value: p.real_ended_at ? `Paused ${duration}` : "Paused", position: "insideTopRight", fill: "#92400e", fontSize: 11 }} />;
            })}
            {minute.teams.map((t, i) => (
              <Area key={t} type="linear" dataKey={t} stackId="1" connectNulls={false} stroke={COLORS[i % 5]} fill={COLORS[i % 5]} fillOpacity={0.35} isAnimationActive={false} />
            ))}
          </AreaChart>
        </ResponsiveContainer>
      </div>

      <div className="card">
        <h2 className="mb-2 font-semibold">Daily spend this period (usage_1d_cost)</h2>
        <ResponsiveContainer width="100%" height={220}>
          <BarChart data={daily.data}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="t" fontSize={11} />
            <YAxis fontSize={11} tickFormatter={(v) => `$${Math.round(v / 1000)}k`} />
            <Tooltip formatter={(v: number) => dollars(v)} />
            <Legend />
            {daily.teams.map((t, i) => <Bar key={t} dataKey={t} stackId="1" fill={COLORS[i % 5]} isAnimationActive={false} />)}
          </BarChart>
        </ResponsiveContainer>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-semibold">API keys</h2>
        <table className="tbl">
          <thead><tr><th>Key</th><th>Provider</th><th>Team</th><th>Owner</th><th className="num">MTD</th><th className="num">Avg/h (24h)</th><th className="num">Now/h</th><th className="num">Projected</th></tr></thead>
          <tbody>
            {data.keys.map((k: any) => {
              const hot = Number(k.run_rate_hourly) > 3 * Math.max(Number(k.avg_hourly_24h), 1);
              return (
                <tr key={k.id} className={hot ? "bg-red-50" : ""}>
                  <td className="font-mono text-xs">{k.label}</td><td>{k.provider_id}</td><td>{k.team}</td>
                  <td>{k.owner ?? <span className="pill bg-amber-100 text-amber-800">no owner</span>}</td>
                  <td className="num">{dollars(k.mtd_dollars)}</td><td className="num">{dollars(k.avg_hourly_24h)}</td>
                  <td className={`num ${hot ? "font-semibold text-red-700" : ""}`}>{dollars(k.run_rate_hourly)}</td>
                  <td className="num">{dollars(k.projected_month_end)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="card"><div className="text-xs uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div></div>;
}
