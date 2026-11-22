"use client";

import Link from "next/link";
import { useState } from "react";
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import Tabs, { TabPanel, type TabDef } from "@/components/trueup/Tabs";
import { dollars, useApi, when } from "@/lib/api";

const COLORS = ["#4f46e5", "#0891b2", "#d97706", "#db2777", "#16a34a", "#7c3aed"];
type SpendView = "hourly" | "daily" | "ownership";

function pivot(rows: any[], bucketKey: string, format: (value: string) => string) {
  const points = new Map<string, any>();
  const teams = [...new Set<string>((rows ?? []).map((row: any) => row.team))].sort();
  for (const row of rows ?? []) {
    const key = String(row[bucketKey]);
    const point = points.get(key) ?? { raw: key, t: format(key) };
    point[row.team] = Number(row.dollars);
    points.set(key, point);
  }
  for (const point of points.values()) {
    for (const team of teams) point[team] ??= 0;
  }
  return { data: [...points.values()], teams };
}

const hourLabel = (value: string) => new Date(value).toLocaleString("en-US", {
  month: "short", day: "numeric", hour: "numeric", timeZone: "America/New_York",
});
const dayLabel = (value: string) => new Date(`${String(value).slice(0, 10)}T12:00:00`).toLocaleDateString("en-US", {
  month: "short", day: "numeric",
});

export default function ConnectedSpend() {
  const [view, setView] = useState<SpendView>("hourly");
  const { data, error } = useApi("/api/spend/connected?hours=168", 60_000);

  if (error) return (
    <div className="card border-red-200 bg-red-50 text-sm text-red-700">
      Could not load connected analytics: {error.message}
    </div>
  );
  if (!data) return <ConnectedSkeleton />;
  if (!data.connections.length) return <NoConnections />;

  const hourly = pivot(data.series, "bucket", hourLabel);
  const daily = pivot(data.daily, "day", dayLabel);
  const quality = data.quality;
  const hasUsage = quality.first_bucket != null;
  const hasPricedUsage = data.series.length > 0 || data.daily.length > 0;
  const tabs: TabDef<SpendView>[] = [
    { key: "hourly", label: "Hourly spend" },
    { key: "daily", label: "Daily spend" },
    { key: "ownership", label: "Ownership", count: data.keys.length },
  ];

  return (
    <div className="space-y-4">
      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <Stat label="Estimated month-to-date" value={dollars(data.summary.mtd)} />
        <Stat label="Projected at month end" value={dollars(data.summary.projected)} />
        <Stat label="Average burn rate (24h)" value={`${dollars(data.summary.burn_rate_hourly)}/h`} />
      </div>

      {!hasUsage ? <EmptyUsage connections={data.connections} /> : (
        <section className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-sm">
          <div className="px-5 pt-2">
            <Tabs tabs={tabs} value={view} onChange={setView} idPrefix="connected-spend" ariaLabel="Connected spend views" />
          </div>
          <div className="p-5">
            <TabPanel idPrefix="connected-spend" k="hourly" value={view}>
              <ChartHeading title="Hourly spend, last 7 days" subtitle="Provider usage reports · hourly resolution · Eastern time" />
              {hasPricedUsage ? <AreaSpend data={hourly.data} teams={hourly.teams} /> : <UnpricedEmpty />}
            </TabPanel>

            <TabPanel idPrefix="connected-spend" k="daily" value={view}>
              <ChartHeading title="Daily spend this month" subtitle="Estimated from effective public list prices" />
              {hasPricedUsage ? <DailySpend data={daily.data} teams={daily.teams} /> : <UnpricedEmpty />}
            </TabPanel>

            <TabPanel idPrefix="connected-spend" k="ownership" value={view}>
              <div className="mb-4">
                <h2 className="font-semibold text-ink">Usage ownership</h2>
                <p className="mt-0.5 text-xs text-ink-3">Credentials and provider key identifiers are never displayed.</p>
              </div>
              <OwnershipTable rows={data.keys} />
            </TabPanel>
          </div>
        </section>
      )}

      <ConnectionHealth connections={data.connections} />
      {hasUsage && <QualityNotice quality={quality} />}
    </div>
  );
}

function ConnectionHealth({ connections }: { connections: any[] }) {
  const failing = connections.filter((connection) => connection.last_error);
  const lastSync = connections.map((connection) => connection.last_sync_at).filter(Boolean).sort().at(-1);
  return (
    <section className="card flex flex-wrap items-center justify-between gap-3 py-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className={`pill ${failing.length ? "bg-red-100 text-red-700" : "bg-green-bg text-green"}`}>
          {failing.length ? `${failing.length} connection${failing.length === 1 ? "" : "s"} need attention` : `${connections.length} connected`}
        </span>
        <span className="text-ink-3">Last successful import: {when(lastSync)}</span>
      </div>
      <Link href="/app/connections" className="font-semibold text-green hover:underline">
        {failing.length > 0 ? "Review errors" : "Manage connections"} →
      </Link>
    </section>
  );
}

function QualityNotice({ quality }: { quality: any }) {
  const incomplete = quality.unpriced_models.length > 0;
  return (
    <section className={`rounded-lg border px-4 py-3 text-sm ${incomplete ? "border-amber-line bg-amber-bg text-amber" : "border-line bg-surface text-ink-2"}`}>
      <div className="flex flex-wrap items-center justify-between gap-2">
        <p>
          <strong>{incomplete ? "Partial estimate" : "List-price estimate"}.</strong>{" "}
          {quality.priced_token_percent == null ? "No token usage has been imported yet." : `${quality.priced_token_percent}% of imported tokens have a known price.`}
          {quality.unmapped_key_count > 0 && ` ${quality.unmapped_key_count} usage source${quality.unmapped_key_count === 1 ? " is" : "s are"} not mapped to an owner.`}
        </p>
        {quality.unmapped_key_count > 0 && <Link href="/app/connections" className="font-semibold underline">Map usage</Link>}
      </div>
      {incomplete && (
        <p className="mt-1 text-xs">
          Unpriced: {quality.unpriced_models.slice(0, 3).map((item: any) => `${item.provider} ${item.model}`).join(", ")}
          {quality.unpriced_models.length > 3 ? ` and ${quality.unpriced_models.length - 3} more` : ""}. These tokens are excluded from totals.
        </p>
      )}
    </section>
  );
}

function AreaSpend({ data, teams }: { data: any[]; teams: string[] }) {
  return <ResponsiveContainer width="100%" height={420}>
    <AreaChart data={data}>
      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
      <XAxis dataKey="t" fontSize={11} minTickGap={36} />
      <YAxis fontSize={11} tickFormatter={(value) => `$${value}`} />
      <Tooltip formatter={(value: number) => dollars(value)} labelFormatter={(_, payload) => payload?.[0]?.payload?.raw ? hourLabel(payload[0].payload.raw) : ""} />
      <Legend />
      {teams.map((team, index) => <Area key={team} type="monotone" dataKey={team} stackId="1" stroke={COLORS[index % COLORS.length]} fill={COLORS[index % COLORS.length]} fillOpacity={0.32} isAnimationActive={false} />)}
    </AreaChart>
  </ResponsiveContainer>;
}

function DailySpend({ data, teams }: { data: any[]; teams: string[] }) {
  return <ResponsiveContainer width="100%" height={420}>
    <BarChart data={data}>
      <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
      <XAxis dataKey="t" fontSize={11} />
      <YAxis fontSize={11} tickFormatter={(value) => `$${value}`} />
      <Tooltip formatter={(value: number) => dollars(value)} />
      <Legend />
      {teams.map((team, index) => <Bar key={team} dataKey={team} stackId="1" fill={COLORS[index % COLORS.length]} isAnimationActive={false} />)}
    </BarChart>
  </ResponsiveContainer>;
}

function OwnershipTable({ rows }: { rows: any[] }) {
  if (!rows.length) return <p className="rounded-lg bg-surface-2 p-6 text-center text-sm text-ink-3">No priced usage is available yet.</p>;
  return <div className="overflow-x-auto">
    <table className="tbl min-w-[760px]">
      <thead><tr><th>Provider</th><th>Team</th><th>Owner</th><th>Status</th><th className="num">MTD</th><th className="num">Avg/h (24h)</th><th className="num">Latest hour</th><th className="num">Projected</th></tr></thead>
      <tbody>{rows.map((row) => <tr key={row.id} className={!row.mapped ? "bg-amber-50" : ""}>
        <td>{row.provider}</td><td>{row.team}</td>
        <td>{row.owner ?? <span className="text-ink-3">—</span>}</td>
        <td>{row.mapped ? <span className="pill bg-green-bg text-green">mapped</span> : <span className="pill bg-amber-bg text-amber">needs mapping</span>}</td>
        <td className="num">{dollars(row.mtd)}</td><td className="num">{dollars(row.avg_hourly_24h)}</td>
        <td className="num">{dollars(row.current_hour)}</td><td className="num">{dollars(row.projected)}</td>
      </tr>)}</tbody>
    </table>
  </div>;
}

function NoConnections() {
  return <section className="card p-8 text-center">
    <p className="tu-eyebrow text-green">Connected workspace</p>
    <h1 className="mt-2 font-serif text-3xl text-ink">Connect a provider to see your analytics</h1>
    <p className="mx-auto mt-2 max-w-xl text-sm leading-relaxed text-ink-2">Add an OpenAI or Anthropic admin credential. Your real usage remains isolated from the public synthetic demo.</p>
    <Link href="/app/connections" className="tu-btn-primary mt-5">Add your first connection</Link>
  </section>;
}

function EmptyUsage({ connections }: { connections: any[] }) {
  const hasError = connections.some((connection) => connection.last_error);
  return <section className="card p-8 text-center">
    <h2 className="font-serif text-2xl text-ink">{hasError ? "Usage import needs attention" : "Waiting for the first usage import"}</h2>
    <p className="mx-auto mt-2 max-w-xl text-sm text-ink-2">{hasError ? "Open Connections to review the provider error and retry the sync." : "The dashboard will populate after a connection completes its first sync. You can start one now from Connections."}</p>
    <Link href="/app/connections" className="tu-btn-primary mt-5">Open connections</Link>
  </section>;
}

function UnpricedEmpty() {
  return <div className="flex h-[420px] items-center justify-center rounded-lg bg-surface-2 text-center text-sm text-ink-3">Usage was imported, but its models do not yet have a matching list price.</div>;
}

function ConnectedSkeleton() {
  return <div className="space-y-4"><div className="tu-skeleton h-24" /><div className="grid grid-cols-3 gap-4"><div className="tu-skeleton h-24" /><div className="tu-skeleton h-24" /><div className="tu-skeleton h-24" /></div><div className="tu-skeleton h-[500px]" /></div>;
}

function ChartHeading({ title, subtitle }: { title: string; subtitle: string }) {
  return <div className="mb-4"><h2 className="font-semibold text-ink">{title}</h2><p className="mt-0.5 text-xs text-ink-3">{subtitle}</p></div>;
}

function Stat({ label, value }: { label: string; value: string }) {
  return <div className="card"><div className="text-xs uppercase tracking-wide text-slate-500">{label}</div><div className="mt-1 text-2xl font-semibold tabular-nums">{value}</div></div>;
}
