"use client";
import Link from "next/link";
import { use, useState } from "react";
import { post, usd, useApi, when } from "@/lib/api";
import { allowed, useMe } from "../../auth-gate";
import {
  activity, approverLabel, assertions, calcOf, checkScore, checks, groupActivity, kpis, outreachState, periodRange,
  ruleForCase, shortTime, statusOf, steps, TYPE_LABEL, type CasePayload, type Source,
} from "@/lib/case-view";
import ActivityEvent from "@/components/trueup/ActivityEvent";
import ApprovalCallout from "@/components/trueup/ApprovalCallout";
import AssertionRow from "@/components/trueup/AssertionRow";
import Card, { EmptyRow, SkeletonRows } from "@/components/trueup/Card";
import CheckRow from "@/components/trueup/CheckRow";
import KpiStrip from "@/components/trueup/KpiStrip";
import Pill from "@/components/trueup/Pill";
import StatusIcon from "@/components/trueup/StatusIcon";
import Stepper from "@/components/trueup/Stepper";
import Tabs, { TabPanel } from "@/components/trueup/Tabs";

type TabKey = "verification" | "activity" | "workpaper" | "correspondence";
type Filter = "all" | Source;
const FILTERS: [Filter, string][] = [["all", "All"], ["llm", "Language model"], ["rule", "Rule-based"]];

/* Page frame shared by the loaded page and its skeleton so nothing moves when data arrives. */
const FRAME = "flex flex-col min-[1280px]:min-h-screen min-[1280px]:flex-row";
const MAIN = "@container min-w-0 flex-1 space-y-6 px-8 pt-6 pb-10 max-[760px]:px-4";
const RAIL = "grid w-full shrink-0 content-start gap-x-8 gap-y-5 border-t border-line bg-surface px-[22px] py-6 max-[760px]:px-4 min-[761px]:max-[1279px]:grid-cols-2 min-[761px]:max-[1279px]:px-8 min-[1280px]:flex min-[1280px]:w-[340px] min-[1280px]:flex-col min-[1280px]:gap-3 min-[1280px]:border-t-0 min-[1280px]:border-l";

export default function CaseDetail({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const { data, error, mutate } = useApi<CasePayload>(`/api/cases/${id}`);
  const { data: recon, mutate: mutateRecon } = useApi("/api/recon", 5000);
  const [tab, setTab] = useState<TabKey>("verification");
  const [filter, setFilter] = useState<Filter>("all");
  const [reply, setReply] = useState("");
  const [busy, setBusy] = useState<string | null>(null);
  const [reruns, setReruns] = useState<Record<number, any>>({});
  const me = useMe();

  if (!data) return error ? <LoadError message={(error as Error).message} retry={() => mutate()} /> : <CaseSkeleton />;

  const c = data.case;
  const calc = calcOf(c);
  const queries: any[] = calc?.queries ?? [];
  const exp = c.explanation;
  const rule = ruleForCase(recon?.rules, c.id);
  const checkList = checks(data);
  const score = checkScore(checkList);
  const events = activity(data.audit);
  const shown = filter === "all" ? events : events.filter((e) => e.source === filter);
  const o = outreachState(data.outreach);
  const [titleA, titleB] = String(c.title).includes(" — ") ? String(c.title).split(" — ") : [c.provider_name, c.title];

  const act = async (label: string, fn: () => Promise<unknown>) => {
    setBusy(label);
    try { await fn(); } finally { setBusy(null); mutate(); mutateRecon(); }
  };
  const send = () => act("reply", async () => { await post(`/api/cases/${id}/reply`, { body: reply }); setReply(""); });
  const rerun = async (i: number) => setReruns({ ...reruns, [i]: await post(`/api/cases/${id}/rerun/${i}`) });
  const downloadJson = () => {
    const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: "application/json" }));
    const a = Object.assign(document.createElement("a"), { href: url, download: `case-${id}-workpaper.json` });
    a.click();
    URL.revokeObjectURL(url);
  };

  // pair each outbound question with the first reply that follows it
  const threads = data.outreach.flatMap((m: any, i: number) => m.direction !== "out" ? [] : [{
    out: m, reply: data.outreach.slice(i + 1).find((r: any) => r.direction === "in") ?? null,
  }]);

  return (
    <div className={FRAME}>
      <div className={MAIN}>
        {/* ------------------------------------------------ header */}
        <header className="space-y-2.5">
          <nav aria-label="Breadcrumb">
            <ol className="flex flex-wrap items-center gap-1.5 text-[11px] font-medium tracking-[0.12em] text-ink-3 uppercase">
              <li><Link href="/close" className="tu-focus rounded hover:text-ink">Close</Link></li>
              <li aria-hidden>/</li>
              <li>{TYPE_LABEL[c.type] ?? c.type}</li>
              <li aria-hidden>/</li>
              <li className="font-mono tracking-normal normal-case">Case #{c.id}</li>
              <li aria-hidden>/</li>
              <li aria-current="page">Verification</li>
            </ol>
          </nav>
          <div className="flex flex-wrap items-start justify-between gap-4">
            <div className="min-w-[min(100%,420px)] flex-1 space-y-3">
              <h1 className="font-serif text-[38px] leading-[42px] tracking-[-0.01em] text-ink max-[760px]:text-[30px] max-[760px]:leading-9">
                {titleA}<span className="text-ink-3"> · </span>{titleB}
              </h1>
              <ul className="flex flex-wrap gap-2" aria-label="Case details">
                <li><Pill variant="neutral">{TYPE_LABEL[c.type] ?? c.type}</Pill></li>
                <li><Pill variant="neutral" mono>{String(c.provider_id).toUpperCase()}</Pill></li>
                {c.key_label && <li><Pill variant="neutral" mono>{c.key_label}</Pill></li>}
                <li><Pill variant="neutral">{periodRange(c.period)}</Pill></li>
                <li><Pill variant="neutral">Opened {when(c.opened_at)}</Pill></li>
              </ul>
            </div>
            <div className="flex flex-wrap gap-2">
              <button type="button" className="tu-btn-secondary" onClick={downloadJson}>Workpaper JSON</button>
              {c.status === "pending_approval" && allowed(me, "controller") && (
                <button type="button" className="tu-btn-primary" disabled={!!busy}
                  onClick={() => act("approve", () => post(`/api/cases/${id}/approve`))}>
                  {busy === "approve" ? "Approving…" : "Approve accrual"}
                </button>
              )}
            </div>
          </div>
        </header>

        <KpiStrip items={kpis(data)} />
        <Stepper steps={steps(data, rule, !!recon)} />

        {rule?.status === "proposed" && allowed(me, "controller") && (
          <ApprovalCallout rule={rule} busy={busy === "rule"}
            onApprove={() => act("rule", () => post(`/api/rules/${rule.id}/activate`))} />
        )}

        {/* ------------------------------------------------ tabs */}
        <div className="space-y-[18px]">
          <Tabs idPrefix="case" value={tab} onChange={setTab} tabs={[
            { key: "verification", label: "Verification", count: `${score.passed}/${score.total}` },
            { key: "activity", label: "Activity", count: data.audit.length },
            { key: "workpaper", label: "Workpaper", count: queries.length || undefined },
            { key: "correspondence", label: "Correspondence", count: data.outreach.length || undefined },
          ]} />

          <TabPanel idPrefix="case" k="verification" value={tab}>
            <div className="space-y-[18px]">
              <div className="flex flex-wrap items-center gap-x-3.5 gap-y-2 rounded-[10px] border border-line bg-surface-2 px-4 py-3">
                <StatusIcon tone={calc ? "done" : "pending"} />
                <p className="min-w-[200px] flex-1 text-[13px] text-ink-2">
                  <span className="font-semibold text-ink">{calc ? `Received from the ${String(calc.kind ?? c.type).replace(/_/g, "-")} estimator` : "Waiting for the estimator"}</span>
                  {" · "}<span className="font-mono text-xs">CASE-{c.id}</span>
                  {calc && <> · {queries.length} {queries.length === 1 ? "query" : "queries"} · {(calc.lines ?? []).length} lines · {data.evidence.length} evidence items</>}
                </p>
                <button type="button" className="tu-focus rounded text-[13px] font-semibold text-green hover:underline" onClick={() => setTab("workpaper")}>
                  Open workpaper <span aria-hidden>→</span>
                </button>
              </div>

              <div className="grid items-start gap-5 @min-[760px]:grid-cols-[minmax(0,1fr)_330px]">
                <Card id="checks" title="Control checks" subtitle="Close rules applied to this case" right={
                  <div className="flex items-center gap-2.5">
                    <span className="text-[13px] font-semibold text-ink tabular-nums">{score.passed} / {score.total} passed</span>
                    <span aria-hidden className="h-1.5 w-[110px] overflow-hidden rounded-full bg-line">
                      <span className="block h-full rounded-full bg-green-2" style={{ width: `${score.total ? (score.passed / score.total) * 100 : 0}%` }} />
                    </span>
                  </div>
                }>
                  <ul>{checkList.map((ch) => <CheckRow key={ch.code} check={ch} />)}</ul>
                </Card>

                <div className="flex flex-col gap-5">
                  <Card id="assertions" title="Assertions" subtitle="What this case records"
                    right={<span className="text-xs text-ink-3">{assertions(data).filter((a) => a.value).length} recorded</span>}>
                    <ul>
                      {assertions(data).map((a) => (
                        <AssertionRow key={a.label} label={a.label} value={a.value ?? "Not recorded yet"} tone={a.value ? "done" : "pending"} />
                      ))}
                    </ul>
                  </Card>

                  <Card id="corr" title="Correspondence" subtitle="Questions to key owners" right={<Pill variant="warning">Synthetic data</Pill>}>
                    {threads.length === 0 ? <EmptyRow>No owner outreach on this case.</EmptyRow> : (
                      <ul>
                        {threads.map(({ out, reply: r }: any) => (
                          <AssertionRow key={out.id} tone={r ? "done" : "flag"}
                            label={`Message to ${out.owner_name ?? "key owner"}`}
                            value={`Sent ${shortTime(out.created_at)} · ${r ? `Replied ${shortTime(r.created_at)}` : "Awaiting reply"}`}
                            right={
                              <button type="button" className="tu-focus shrink-0 rounded text-[13px] font-semibold text-green hover:underline"
                                aria-label={`View message to ${out.owner_name ?? "key owner"}`} onClick={() => setTab("correspondence")}>View</button>
                            } />
                        ))}
                      </ul>
                    )}
                  </Card>
                </div>
              </div>
            </div>
          </TabPanel>

          <TabPanel idPrefix="case" k="activity" value={tab}>
            <Card id="audit" title="Audit trail" subtitle="Every action on this case, oldest first">
              {data.audit.length === 0 ? <EmptyRow>No audit events yet.</EmptyRow> : (
                <div className="overflow-x-auto">
                  <table className="w-full text-[13px]">
                    <thead>
                      <tr className="border-b border-line text-left">
                        {["When", "Actor", "Action", "Detail"].map((h) => <th key={h} scope="col" className="tu-eyebrow px-[18px] py-2">{h}</th>)}
                      </tr>
                    </thead>
                    <tbody>{data.audit.map((a: any) => (
                      <tr key={a.id} className="border-b border-line last:border-b-0 align-top">
                        <td className="px-[18px] py-2 whitespace-nowrap text-ink-2 tabular-nums">{when(a.ts)}</td>
                        <td className="px-[18px] py-2 font-mono text-xs text-ink-2">{a.actor}</td>
                        <td className="px-[18px] py-2 text-ink">{a.action.replace(/_/g, " ")}</td>
                        <td className="max-w-md truncate px-[18px] py-2 font-mono text-xs text-ink-3" title={JSON.stringify(a.detail)}>{JSON.stringify(a.detail)}</td>
                      </tr>
                    ))}</tbody>
                  </table>
                </div>
              )}
            </Card>
          </TabPanel>

          <TabPanel idPrefix="case" k="workpaper" value={tab}>
            <div className="space-y-5">
              <Card id="explain" title="Explanation" subtitle={exp
                ? `Agent ${exp.agent?.mode ?? "?"} · ${exp.agent?.verified ? "every number verified against the query results" : "fallback text"}`
                : undefined}>
                {exp ? (
                  <div className="px-[18px] py-3.5 text-[13px] text-ink">
                    <p className="font-semibold">{exp.headline}</p>
                    <ul className="mt-1.5 list-disc space-y-0.5 pl-5 text-ink-2">{exp.bullets?.map((b: string, i: number) => <li key={i}>{b}</li>)}</ul>
                  </div>
                ) : <EmptyRow>The explainer runs after the case is estimated.</EmptyRow>}
              </Card>
              <Card id="calc" title="How the number was computed" subtitle={calc?.summary}>
                {queries.length === 0 ? <EmptyRow>No stored queries yet.</EmptyRow> : (
                  <div className="space-y-4 px-[18px] py-3.5">
                    {queries.map((q, i) => (
                      <div key={i}>
                        <div className="mb-1.5 flex flex-wrap items-center gap-2 text-xs text-ink-3 tabular-nums">
                          <span className="font-mono">Query {i + 1} · {q.ms?.toFixed(1)} ms · {q.rows?.length} rows</span>
                          <button type="button" className="tu-btn-secondary px-2.5 py-1 text-xs" disabled={!allowed(me, "controller")} onClick={() => rerun(i)}>Re-run</button>
                          {reruns[i] && <span role="status" className={reruns[i].matches_stored ? "text-green" : "text-amber"}>
                            {reruns[i].matches_stored ? `✓ same result (${reruns[i].ms} ms)` : `result changed since close (${reruns[i].ms} ms)`}</span>}
                        </div>
                        <pre className="overflow-x-auto rounded-lg bg-ink p-3 font-mono text-xs leading-relaxed text-surface-2">{q.sql.trim()}</pre>
                      </div>
                    ))}
                  </div>
                )}
              </Card>
            </div>
          </TabPanel>

          <TabPanel idPrefix="case" k="correspondence" value={tab}>
            <Card id="outreach" title="Correspondence" subtitle="Owner questions and replies" right={<Pill variant="warning">Synthetic data</Pill>}>
              {data.outreach.length === 0 ? <EmptyRow>No owner outreach on this case.</EmptyRow> : (
                <div className="space-y-2 px-[18px] py-3.5">
                  {data.outreach.map((m: any) => (
                    <div key={m.id} className={`rounded-lg p-3 text-[13px] text-ink ${m.direction === "out" ? "bg-surface-2" : "border border-green-2/20 bg-green-bg"}`}>
                      <div className="mb-1 text-xs text-ink-2">{m.direction === "out" ? `To ${m.owner_name ?? "?"} <${m.email ?? "?"}>` : "Reply"} · {shortTime(m.created_at)}</div>
                      {m.body}
                    </div>
                  ))}
                  <form className="flex flex-wrap gap-2 pt-1" onSubmit={(e) => { e.preventDefault(); if (reply && allowed(me, "controller")) send(); }}>
                    <label htmlFor="reply" className="sr-only">Reply as the key owner</label>
                    <input id="reply" className="tu-focus min-w-[200px] flex-1 rounded-lg border border-line-2 px-3 py-2 text-[13px] text-ink placeholder:text-ink-3"
                      placeholder="Reply as the key owner…" value={reply} onChange={(e) => setReply(e.target.value)} />
                    <button type="submit" className="tu-btn-primary" disabled={!reply || !!busy || !allowed(me, "controller")}>{busy === "reply" ? "Interpreting…" : "Send reply"}</button>
                  </form>
                </div>
              )}
            </Card>
          </TabPanel>
        </div>
      </div>

      {/* ------------------------------------------------ right rail */}
      <aside className={RAIL} aria-label="Outcome and activity">
        <div className="flex flex-col gap-3">
        <h2 className="tu-eyebrow">Outcome</h2>
        <div className="flex flex-col gap-1.5 rounded-[10px] border border-line bg-paper p-4">
          <p className="tu-eyebrow text-ink-2">{c.type === "anomaly" ? "Excess spend" : "Accrual amount"}</p>
          <p className="font-serif text-[34px] leading-[44px] text-ink tabular-nums">{usd(c.estimate_cents)}</p>
          <dl className="space-y-1 text-xs">
            {([
              ["Status", statusOf(c.status).label, ""],
              ["Approved by", approverLabel(c.approved_by), ""],
              ["Checks", `${score.passed}/${score.total} passed`, score.passed === score.total ? "text-green" : "text-amber"],
            ] as const).map(([k, v, cls]) => (
              <div key={k} className="flex justify-between gap-3">
                <dt className="text-ink-2">{k}</dt>
                <dd className={`text-right font-medium ${cls || "text-ink"}`}>{v}</dd>
              </div>
            ))}
          </dl>
        </div>
        </div>

        <div className="flex flex-col gap-3">
        <div className="flex items-baseline justify-between min-[1280px]:pt-3.5">
          <h2 className="tu-eyebrow">Activity</h2>
          <span className="text-[11px] text-ink-3 tabular-nums">{events.length} events</span>
        </div>
        <div className="flex flex-wrap gap-1.5" role="group" aria-label="Filter activity by source">
          {FILTERS.map(([k, label]) => (
            <button key={k} type="button" aria-pressed={filter === k} onClick={() => setFilter(k)}
              className={`tu-focus rounded-full border px-2 py-[3px] text-[11px] ${filter === k ? "border-ink bg-ink text-white" : "border-line text-ink-2 hover:bg-surface-2"}`}>
              {label}
            </button>
          ))}
        </div>
        <div aria-live="polite">
          {shown.length === 0
            ? <p className="py-3 text-[13px] text-ink-3">{events.length === 0 ? "No activity yet." : "No events from this source."}</p>
            : groupActivity(shown).map((g) => (
              <section key={g.group} aria-label={g.group}>
                <h3 className="pt-1 text-[11px] font-semibold tracking-[0.06em] text-ink-3 uppercase">{g.group}</h3>
                <ul>{g.items.map((it) => <ActivityEvent key={it.id} item={it} />)}</ul>
              </section>
            ))}
        </div>
        </div>
        <div className="hidden flex-1 min-[1280px]:block" />
        <Link href="/close" className="tu-btn-secondary w-full min-[761px]:max-[1279px]:col-span-2 min-[761px]:max-[1279px]:w-auto min-[761px]:max-[1279px]:justify-self-start">← Back to close</Link>
      </aside>
    </div>
  );
}

function LoadError({ message, retry }: { message: string; retry: () => void }) {
  return (
    <div className="p-8">
      <div role="alert" className="rounded-[10px] border border-amber-line bg-amber-bg p-4 text-[13px] text-ink">
        <p className="font-semibold">Could not load this case</p>
        <p className="mt-0.5 text-ink-2">{message}</p>
        <button type="button" className="tu-btn-secondary mt-3" onClick={retry}>Try again</button>
      </div>
    </div>
  );
}

/** Same frame and block heights as the loaded page, so the content swaps in without shifting. */
function CaseSkeleton() {
  return (
    <div className={FRAME} aria-busy="true">
      <span role="status" className="sr-only">Loading case…</span>
      <div className={MAIN} aria-hidden>
        <div className="space-y-2.5">
          <div className="tu-skeleton h-3.5 w-72" />
          <div className="tu-skeleton h-[42px] w-2/3" />
          <div className="flex gap-2">{[120, 90, 150].map((w) => <div key={w} className="tu-skeleton h-[22px] rounded-full" style={{ width: w }} />)}</div>
        </div>
        <div className="grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-line bg-line @min-[640px]:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <div key={i} className="space-y-2 bg-surface px-[18px] py-3.5"><div className="tu-skeleton h-3 w-24" /><div className="tu-skeleton h-[33px] w-28" /><div className="tu-skeleton h-3 w-32" /></div>
          ))}
        </div>
        <div className="tu-skeleton h-[84px]" />
        <div className="tu-skeleton h-10" />
        <div className="grid items-start gap-5 @min-[760px]:grid-cols-[minmax(0,1fr)_330px]">
          <div className="overflow-hidden rounded-[10px] border border-line"><div className="h-[67px] border-b border-line" /><SkeletonRows n={6} /></div>
          <div className="overflow-hidden rounded-[10px] border border-line"><div className="h-[67px] border-b border-line" /><SkeletonRows n={4} /></div>
        </div>
      </div>
      <div className={RAIL} aria-hidden>
        <div className="tu-skeleton h-3 w-16" />
        <div className="tu-skeleton h-[150px] rounded-[10px]" />
        <SkeletonRows n={5} />
      </div>
    </div>
  );
}
