"use client";
import Link from "next/link";
import { useApi } from "@/lib/api";

export default function ConnectedOverview() {
  const { data, error } = useApi("/api/connections", 5000);
  const connections = data?.connections ?? [];
  return (
    <div className="space-y-4">
      <section className="card p-6">
        <p className="tu-eyebrow text-green">Connected workspace</p>
        <h1 className="mt-2 font-serif text-3xl text-ink">Bring in your provider data</h1>
        <p className="mt-2 max-w-2xl text-sm leading-relaxed text-ink-2">
          This workspace is isolated from the synthetic demo. Add an OpenAI or Anthropic credential to begin importing your own usage records.
        </p>
        <Link href="/app/connections" className="tu-btn-primary mt-5">{connections.length ? "Manage connections" : "Add your first connection"}</Link>
      </section>
      {error && <div className="card border-red-200 bg-red-50 text-sm text-red-700">Could not load connections: {error.message}</div>}
      {!data && !error && <div className="card text-sm text-ink-3">Loading workspace…</div>}
      {data && connections.length > 0 && (
        <section className="card">
          <div className="flex items-center justify-between"><h2 className="font-semibold text-ink">Your connections</h2><span className="text-xs text-ink-3">{connections.length} configured</span></div>
          <div className="mt-3 divide-y divide-line">
            {connections.map((connection: any) => (
              <Link key={connection.id} href={`/app/connections/${connection.id}`} className="flex items-center justify-between gap-4 py-3 text-sm hover:text-green">
                <span><strong>{connection.label}</strong><span className="ml-2 text-ink-3">{connection.provider_name}</span></span>
                <span className="pill bg-green-bg text-green">{connection.status}</span>
              </Link>
            ))}
          </div>
        </section>
      )}
    </div>
  );
}
