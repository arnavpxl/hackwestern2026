"use client";
import Link from "next/link";
import { useRef, useState, type FormEvent } from "react";
import { post, useApi, when } from "@/lib/api";
import { allowed, useMe } from "../auth-gate";
import Status from "../status";
import { useAppRoot } from "@/lib/routes";
import LoadingState from "@/components/LoadingState";

function syncSummary(r: any) {
  const prefix = "Sync";
  return r.errors
    ? `${prefix} finished with ${r.errors} error${r.errors === 1 ? "" : "s"}. ${r.rows} hourly rows imported.`
    : r.rows > 0
      ? `${prefix} imported ${r.rows} hourly rows across ${r.connections} connection${r.connections === 1 ? "" : "s"}.`
      : `${prefix} complete. All ${r.connections} connection${r.connections === 1 ? " is" : "s are"} up to date.`;
}

export default function Connections() {
  const root = useAppRoot();
  const { data, mutate } = useApi("/api/connections", 5000);
  const me = useMe();
  const canEdit = allowed(me, "admin");
  const [form, setForm] = useState({ provider_id: "anthropic", label: "", team_id: "", key: "" });
  const [rotating, setRotating] = useState<{ id: number; key: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const syncInFlight = useRef(false);

  if (!data) return <LoadingState label="Loading connections" detail="Checking your provider connections and sync status…" />;

  // The key is sent once, then the field is cleared so it does not stay on screen.
  const add = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/api/connections", { ...form, team_id: Number(form.team_id) });
      setForm({ ...form, label: "", key: "" });
      mutate();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const rotate = async () => {
    if (!rotating) return;
    setBusy(true);
    setError(null);
    try {
      await post(`/api/connections/${rotating.id}/rotate`, { key: rotating.key });
      setRotating(null);
      mutate();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  const syncAll = async () => {
    if (syncInFlight.current) return;
    syncInFlight.current = true;
    setError(null);
    setNotice(null);
    setBusy(true);
    try {
      const r = await post("/api/connections/sync");
      setNotice(syncSummary(r));
      await mutate();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      syncInFlight.current = false;
      setBusy(false);
    }
  };

  const revoke = async (id: number, label: string) => {
    if (!confirm(`Revoke "${label}"? Its stored key is deleted and syncing stops.`)) return;
    setError(null);
    try {
      await post(`/api/connections/${id}/revoke`);
      mutate();
    } catch (err) {
      setError((err as Error).message);
    }
  };

  return (
    <>
      <div className="card">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div><h1 className="font-serif text-xl">Connections</h1>
            <p className="mt-1 text-sm text-ink-3">Keys are encrypted and never shown again. Usage syncs every hour.</p>
          </div>
          {canEdit && <button type="button" className="btn" disabled={busy || !data.connections.some((c: any) => c.status === "connected")} onClick={syncAll}>
            {busy ? "Syncing…" : "Sync now"}
          </button>}
        </div>
      </div>

      {canEdit && (
        <form className="card grid gap-3 sm:grid-cols-2 lg:grid-cols-5" autoComplete="off" onSubmit={add}>
          <label className="text-sm">Provider
            <select className="mt-1 w-full rounded-lg border border-line-2 px-2 py-2" value={form.provider_id}
              onChange={(e) => setForm({ ...form, provider_id: e.target.value })}>
              {data.providers.map((p: any) => <option key={p.id} value={p.id}>{p.name}</option>)}
            </select>
          </label>
          <label className="text-sm">Name
            <input className="mt-1 w-full rounded-lg border border-line-2 px-2 py-2" required maxLength={60}
              placeholder="e.g. Platform prod" autoComplete="off" value={form.label} onChange={(e) => setForm({ ...form, label: e.target.value })} />
          </label>
          <label className="text-sm">Default team
            <select className="mt-1 w-full rounded-lg border border-line-2 px-2 py-2" required value={form.team_id}
              onChange={(e) => setForm({ ...form, team_id: e.target.value })}>
              <option value="">Choose…</option>
              {data.teams.map((t: any) => <option key={t.id} value={t.id}>{t.name}</option>)}
            </select>
          </label>
          <label className="text-sm">Admin API key
            <input className="mt-1 w-full rounded-lg border border-line-2 px-2 py-2 font-mono" type="password" required
              autoComplete="new-password" data-1p-ignore data-lpignore="true" data-form-type="other"
              autoCapitalize="none" spellCheck={false}
              value={form.key} onChange={(e) => setForm({ ...form, key: e.target.value })} />
          </label>
          <div className="flex items-end">
            <button className="btn-primary w-full py-2" disabled={busy || !form.team_id}>{busy ? "Connecting…" : "Connect"}</button>
          </div>
        </form>
      )}

      {error && <div className="card border-rose-200 bg-rose-50 text-sm text-rose-800">{error}</div>}
      {notice && <div className="card border-line bg-surface-2 text-sm text-ink-2">{notice}</div>}

      <div className="card overflow-x-auto">
        <table className="tbl">
          <thead><tr><th>Name</th><th>Provider</th><th>Team</th><th>Key</th><th>Status</th><th>Added</th><th>Last sync</th>{canEdit && <th></th>}</tr></thead>
          <tbody>
            {data.connections.length === 0 && (
              <tr><td colSpan={canEdit ? 8 : 7} className="py-6 text-center text-ink-3">
                No connections yet.
              </td></tr>
            )}
            {data.connections.map((c: any) => (
              <tr key={c.id}>
                <td><Link className="text-green hover:underline" href={`${root}/connections/${c.id}`}>{c.label}</Link></td>
                <td>{c.provider_name}</td>
                <td>{c.team}</td>
                <td className="font-mono text-xs">{c.status === "connected" ? `••••${c.key_last4}` : "—"}</td>
                <td><Status s={c.status} /></td>
                <td className="whitespace-nowrap">{when(c.created_at)}{c.created_by && <div className="text-xs text-ink-3">{c.created_by}</div>}</td>
                <td>{when(c.last_sync_at)}{c.last_error && <div className="text-xs text-rose-700">{c.last_error}</div>}</td>
                {canEdit && (
                  <td className="whitespace-nowrap text-right">
                    {c.status === "connected" && (
                      rotating && rotating.id === c.id ? (
                        <span className="flex items-center gap-2">
                          <input className="w-44 rounded-lg border border-line-2 px-2 py-1 font-mono text-xs" type="password"
                            autoComplete="new-password" data-1p-ignore data-lpignore="true" data-form-type="other"
                            autoCapitalize="none" spellCheck={false} placeholder="new key" value={rotating.key}
                            onChange={(e) => setRotating({ id: c.id, key: e.target.value })} />
                          <button className="btn-primary" disabled={busy || !rotating.key} onClick={rotate}>Save</button>
                          <button className="tu-btn-ghost" onClick={() => setRotating(null)}>Cancel</button>
                        </span>
                      ) : (
                        <span className="flex justify-end gap-1">
                          <button className="tu-btn-ghost px-2" onClick={() => setRotating({ id: c.id, key: "" })}>Rotate</button>
                          <button className="tu-btn-ghost px-2 text-red-700 hover:text-red-800" onClick={() => revoke(c.id, c.label)}>Revoke</button>
                        </span>
                      )
                    )}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
