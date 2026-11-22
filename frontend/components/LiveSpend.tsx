"use client";
import { useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { dollars, useApi } from "@/lib/api";
import Tabs, { TabPanel, type TabDef } from "@/components/trueup/Tabs";
import LoadingState from "@/components/LoadingState";

const COLORS = ["#4f46e5", "#0891b2", "#d97706", "#db2777", "#16a34a"];
type SpendView = "minute" | "daily" | "keys";

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

const hhmm = (ts: string) => new Date(ts).toLocaleTimeString("en-GB", {
  hour: "2-digit", minute: "2-digit", timeZone: "America/New_York",
});
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
  const [view, setView] = useState<SpendView>("minute");
  const { data, error } = useApi("/api/spend/live?minutes=60");
  if (error) return <div className="card text-red-700">API unreachable: {String(error.message)}. Is `make demo` running?</div>;
  if (!data) return <LoadingState variant="dashboard" label="Loading demo analytics" detail="Preparing the live spend feed and synthetic usage data…" />;
  const teams = [...new Set<string>(data.keys.map((key: any) => key.team))].sort();
  const minute = minutePivot(data.series, teams, data.sim_now);
  const daily = pivot(data.daily, "day", day);
  const mtd = data.keys.reduce((a: number, k: any) => a + Number(k.mtd_dollars), 0);
  const proj = data.keys.reduce((a: number, k: any) => a + Number(k.projected_month_end), 0);
  const burn = data.keys.reduce((a: number, k: any) => a + Number(k.run_rate_hourly), 0);
  const pauses = data.pauses ?? [];
  const views: TabDef<SpendView>[] = [
    { key: "minute", label: "Minute-by-minute" },
    { key: "daily", label: "Daily spend" },
    { key: "keys", label: "API keys", count: data.keys.length },
  ];

  return (
    <>
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Month-to-date usage spend" value={dollars(mtd)} />
        <Stat label="Projected at month end" value={dollars(proj)} />
        <Stat label="Current burn rate (last 5 min)" value={`${dollars(burn)}/h`} />
      </div>

      <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
        <div className="px-5 pt-2">
          <Tabs tabs={views} value={view} onChange={setView} idPrefix="spend-view" ariaLabel="Live spend views" />
        </div>
        <div className="p-5">
          <TabPanel idPrefix="spend-view" k="minute" value={view}>
            <div className="mb-4 flex flex-wrap items-center justify-between gap-2">
              <div>
                <h2 className="font-semibold">Spend per minute, last hour</h2>
                <p className="mt-0.5 text-xs text-ink-3">Real-time aggregate · usage_1m · Eastern time</p>
              </div>
              {data.paused && <span className="pill bg-amber-100 text-amber-800">Paused · simulation clock frozen</span>}
            </div>
            <div className="h-[clamp(270px,42vh,420px)]">
            <ResponsiveContainer width="100%" height="100%">
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
          </TabPanel>

          <TabPanel idPrefix="spend-view" k="daily" value={view}>
            <div className="mb-4">
              <h2 className="font-semibold">Daily spend this period</h2>
              <p className="mt-0.5 text-xs text-ink-3">Daily cost aggregate · usage_1d_cost</p>
            </div>
            <div className="h-[clamp(270px,42vh,420px)]">
            <ResponsiveContainer width="100%" height="100%">
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
          </TabPanel>

          <TabPanel idPrefix="spend-view" k="keys" value={view}>
            <div className="mb-4">
              <h2 className="font-semibold">API keys</h2>
              <p className="mt-0.5 text-xs text-ink-3">Credentials are write-only and never displayed. Only ownership and spend metadata are shown.</p>
            </div>
            <div className="max-h-[42vh] overflow-auto">
              <table className="tbl min-w-[760px]">
                <thead><tr><th>Provider</th><th>Team</th><th>Owner</th><th className="num">MTD</th><th className="num">Avg/h (24h)</th><th className="num">Now/h</th><th className="num">Projected</th></tr></thead>
                <tbody>
                  {data.keys.map((k: any) => {
                    const hot = Number(k.run_rate_hourly) > 3 * Math.max(Number(k.avg_hourly_24h), 1);
                    return (
                      <tr key={k.id} className={hot ? "bg-red-50" : ""}>
                        <td>{k.provider_id}</td><td>{k.team}</td>
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
          </TabPanel>
        </div>
      </div>
    </>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="card"><div className="text-xs uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div></div>;
}
