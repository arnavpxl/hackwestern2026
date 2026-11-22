"use client";
import Link from "next/link";
import { use, useState } from "react";
import { post, useApi, usd, when } from "@/lib/api";
import { allowed, useMe } from "../../auth-gate";
import Status from "../../status";
import { useAppRoot } from "@/lib/routes";
import LoadingState from "@/components/LoadingState";

const num = (n: number | null | undefined) => (n == null ? "—" : Number(n).toLocaleString("en-US"));

export default function ConnectionDetail({ params }: { params: Promise<{ id: string }> }) {
  const root = useAppRoot();
  const { id } = use(params);
  const { data, mutate } = useApi(`/api/connections/${id}`, 5000);
  const { data: lists } = useApi("/api/connections", 60000);
  const me = useMe();
  const canEdit = allowed(me, "admin");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [target, setTarget] = useState<Record<string, { mode: "existing" | "new"; api_key_id: string; name: string; team_id: string; owner_id: string }>>({});
  if (!data) return <LoadingState label="Loading connection details" detail="Fetching imported sources, mappings, and sync history…" />;
  const c = data.connection;

  const run = async (fn: () => Promise<any>, done?: (r: any) => string) => {
    setBusy(true);
    setError(null);
    setNotice(null);
    try {
      const r = await fn();
      if (done) setNotice(done(r));
      mutate();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const syncNow = () => run(() => post(`/api/connections/${id}/sync`), (r) =>
    r.status === "ok" ? `Synced ${r.rows} hourly rows.` : r.status === "up_to_date" ? "Already up to date."
      : r.status === "error" ? `Sync failed: ${r.error}` : `Sync: ${r.status}`);

  const key = (u: any) => `${u.provider_key_id}|${u.workspace_id}`;
  const current = (k: string) => target[k] ?? { mode: "existing" as const, api_key_id: "", name: "", team_id: String(c.team_id), owner_id: "" };
  const setCurrent = (k: string, patch: object) => setTarget({ ...target, [k]: { ...current(k), ...patch } });

  const map = (u: any) => {
    const t = current(key(u));
    const body: any = { provider_key_id: u.provider_key_id, workspace_id: u.workspace_id };
    if (t.mode === "existing") body.api_key_id = Number(t.api_key_id);
    else body.new_key = { label: t.name, team_id: Number(t.team_id), owner_id: t.owner_id ? Number(t.owner_id) : null };
    return run(() => post(`/api/connections/${id}/mappings`, body), () => "Mapped.");
  };

  const unmap = (m: any) => run(() => post(`/api/connections/${id}/mappings/remove`,
    { provider_key_id: m.provider_key_id, workspace_id: m.workspace_id }), () => "Unmapped.");

  return (
    <>
      <div className="card">
        <div className="flex flex-wrap items-center gap-3">
          <Link href={`${root}/connections`} className="text-sm text-green hover:underline">← Connections</Link>
          <h1 className="font-serif text-2xl">{c.label}</h1><Status s={c.status} />
          {canEdit && c.status === "connected" && <button className="btn ml-auto" disabled={busy} onClick={syncNow}>Sync now</button>}
        </div>
        <div className="mt-1 text-sm text-ink-3">
          {c.provider_name} · {c.team} · ••••{c.key_last4} · synced {when(c.last_sync_at)}
        </div>
        {c.last_error && <div className="mt-2 rounded-lg bg-rose-50 p-2 text-sm text-rose-800">{c.last_error}</div>}
        <div className="mt-4 grid gap-4 text-sm sm:grid-cols-3">
          <div><div className="text-xs text-ink-3">Hours stored</div><div className="font-serif text-xl tabular-nums">{num(data.coverage.rows)}</div></div>
          <div><div className="text-xs text-ink-3">From</div><div>{when(data.coverage.first_bucket)}</div></div>
          <div><div className="text-xs text-ink-3">To</div><div>{when(data.coverage.last_bucket)}</div></div>
        </div>
      </div>

      {error && <div className="card border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</div>}
      {notice && <div className="card border-line bg-surface-2 text-sm text-ink-2">{notice}</div>}

      <div className="card overflow-x-auto">
        <h2 className="font-serif text-xl">Keys on the default team</h2>
        <p className="mb-2 text-sm text-ink-3">Counted toward {c.team}. Map a key to set an owner or another team.</p>
        <table className="tbl">
          <thead><tr><th>Provider key</th><th>Workspace</th><th className="num">Tokens</th><th>Seen</th>{canEdit && <th>Map to</th>}</tr></thead>
          <tbody>
            {data.unmapped.length === 0 && <tr><td colSpan={canEdit ? 5 : 4} className="py-4 text-center text-ink-3">All provider keys have detailed mappings.</td></tr>}
            {data.unmapped.map((u: any) => {
              const t = current(key(u));
              return (
                <tr key={key(u)}>
                  <td className="font-mono text-xs">{u.provider_key_id || "(none)"}</td>
                  <td className="font-mono text-xs">{u.workspace_id || "(default)"}</td>
                  <td className="num">{num(u.tokens)}</td>
                  <td className="whitespace-nowrap text-xs">{when(u.first_seen)} → {when(u.last_seen)}</td>
                  {canEdit && (
                    <td>
                      <div className="flex flex-wrap items-center gap-2">
                        <select className="rounded-lg border border-line-2 px-2 py-1 text-xs" value={t.mode}
                          onChange={(e) => setCurrent(key(u), { mode: e.target.value })}>
                          <option value="existing">An existing mapping</option>
                          <option value="new">A new mapping</option>
                        </select>
                        {t.mode === "existing" ? (
                          <select className="rounded-lg border border-line-2 px-2 py-1 text-xs" value={t.api_key_id}
                            onChange={(e) => setCurrent(key(u), { api_key_id: e.target.value })}>
                            <option value="">Choose…</option>
                            {data.our_keys.map((k: any) => <option key={k.id} value={k.id}>{k.label}</option>)}
                          </select>
                        ) : (
                          <>
                            <input className="w-36 rounded-lg border border-line-2 px-2 py-1 text-xs" placeholder="Key name"
                              value={t.name} onChange={(e) => setCurrent(key(u), { name: e.target.value })} />
                            <select className="rounded-lg border border-line-2 px-2 py-1 text-xs" value={t.team_id}
                              onChange={(e) => setCurrent(key(u), { team_id: e.target.value })}>
                              <option value="">Team…</option>
                              {(lists?.teams ?? []).map((tm: any) => <option key={tm.id} value={tm.id}>{tm.name}</option>)}
                            </select>
                            <select className="rounded-lg border border-line-2 px-2 py-1 text-xs" value={t.owner_id}
                              onChange={(e) => setCurrent(key(u), { owner_id: e.target.value })}>
                              <option value="">No owner (orphan)</option>
                              {data.owners.map((o: any) => <option key={o.id} value={o.id}>{o.name}</option>)}
                            </select>
                          </>
                        )}
                        <button className="btn-primary" disabled={busy || (t.mode === "existing" ? !t.api_key_id : !t.name || !t.team_id)}
                          onClick={() => map(u)}>Map</button>
                      </div>
                    </td>
                  )}
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-serif text-xl">Mapped keys</h2>
        <table className="tbl">
          <thead><tr><th>Provider key</th><th>Workspace</th><th>Our key</th><th>Team</th><th>Owner</th>{canEdit && <th></th>}</tr></thead>
          <tbody>
            {data.mappings.length === 0 && <tr><td colSpan={canEdit ? 6 : 5} className="py-4 text-center text-ink-3">None yet.</td></tr>}
            {data.mappings.map((m: any) => (
              <tr key={`${m.provider_key_id}|${m.workspace_id}`}>
                <td className="font-mono text-xs">{m.provider_key_id || "(none)"}</td>
                <td className="font-mono text-xs">{m.workspace_id || "(default)"}</td>
                <td>{m.label}</td><td>{m.team}</td><td>{m.owner ?? <span className="text-amber-700">orphan</span>}</td>
                {canEdit && <td className="text-right"><button className="tu-btn-ghost px-2" disabled={busy} onClick={() => unmap(m)}>Unmap</button></td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card overflow-x-auto">
        <h2 className="mb-2 font-serif text-xl">Recent syncs</h2>
        <table className="tbl">
          <thead><tr><th>Started</th><th>Status</th><th>Covered</th><th className="num">Rows</th><th>Error</th></tr></thead>
          <tbody>
            {data.runs.length === 0 && <tr><td colSpan={5} className="py-4 text-center text-ink-3">No syncs yet.</td></tr>}
            {data.runs.map((r: any, i: number) => (
              <tr key={i}>
                <td className="whitespace-nowrap">{when(r.started_at)}</td><td><Status s={r.status} /></td>
                <td className="whitespace-nowrap text-xs">{r.synced_from ? `${when(r.synced_from)} → ${when(r.synced_through)}` : "—"}</td>
                <td className="num">{num(r.rows_loaded)}</td>
                <td className="text-xs text-rose-700">{r.error ?? ""}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
