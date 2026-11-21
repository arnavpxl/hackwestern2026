/**
 * Pure, client-side view model for the Case → Verification screen.
 *
 * Everything here is derived from fields the API already returns
 * (GET /api/cases/:id and the rules list from GET /api/recon). Nothing here changes what a
 * case's status means: the server's state machine (backend orchestrator/close.py) decides
 * that; this file only describes it.
 */
import { usd } from "./api";

export type Tone = "done" | "flag" | "pending" | "skipped";
export type CheckResult = "passed" | "flagged" | "pending" | "na";
export type Source = "llm" | "rule";

export type CasePayload = {
  case: any;
  evidence: any[];
  outreach: any[];
  audit: any[];
  snapshots: { ts: string; estimate_cents: number | null; confidence: number | null; reason: string }[];
};

// ------------------------------------------------------------------ formatting

const UTC = { timeZone: "UTC" } as const;

export const shortDate = (ts: string | null | undefined) =>
  ts ? new Date(ts).toLocaleDateString("en-US", { month: "short", day: "numeric", ...UTC }) : "—";

export const shortTime = (ts: string | null | undefined) =>
  ts ? new Date(ts).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit", ...UTC }) : "—";

/** "2026-12-01" → "Dec 1 – Dec 31, 2026" */
export function periodRange(period: string | null | undefined) {
  if (!period) return "—";
  const start = new Date(`${String(period).slice(0, 10)}T00:00:00Z`);
  const end = new Date(Date.UTC(start.getUTCFullYear(), start.getUTCMonth() + 1, 0));
  const md = (d: Date) => d.toLocaleDateString("en-US", { month: "short", day: "numeric", ...UTC });
  return `${md(start)} – ${md(end)}, ${end.getUTCFullYear()}`;
}

export const humanize = (s: string | null | undefined) => (s ? s.replace(/_/g, " ") : "—");

const signedUsd = (cents: number) => `${cents > 0 ? "+" : cents < 0 ? "−" : ""}${usd(Math.abs(cents))}`;

export const TYPE_LABEL: Record<string, string> = {
  usage: "Usage-based",
  fixed: "Fixed contract",
  one_time: "One-time purchase",
  anomaly: "Spend anomaly",
};

export const STATUS: Record<string, { label: string; tone: Tone }> = {
  open: { label: "Open", tone: "pending" },
  needs_info: { label: "Needs info", tone: "flag" },
  estimated: { label: "Estimated", tone: "pending" },
  pending_approval: { label: "Awaiting approval", tone: "flag" },
  approved: { label: "Approved", tone: "done" },
  reconciled: { label: "Reconciled", tone: "done" },
  skipped_invoiced: { label: "Already invoiced", tone: "skipped" },
};
export const statusOf = (s: string) => STATUS[s] ?? { label: humanize(s), tone: "pending" as Tone };

export function approverLabel(by: string | null | undefined) {
  if (!by) return "—";
  if (by === "policy:below_materiality") return "Policy (below materiality)";
  if (by.startsWith("owner:")) return `Owner (${humanize(by.slice(6))})`;
  return humanize(by);
}

// ------------------------------------------------------------------ shared derivations

/** Mirrors the "answered" test in close.outreach_if_needed. */
export function outreachState(outreach: any[]) {
  const outs = outreach.filter((m) => m.direction === "out");
  const ins = outreach.filter((m) => m.direction === "in");
  const answered = ins.some((m) => m.parsed && m.parsed.intent !== "unclear");
  const lastIn = ins.at(-1);
  return { outs, ins, answered, waiting: outs.length > 0 && !answered, lastIn, owner: outs[0]?.owner_name as string | undefined };
}

export const calcOf = (c: any) => c?.calc?.estimate ?? c?.calc ?? null;

// ------------------------------------------------------------------ KPIs

export type Kpi = { label: string; value: string; sub: string; tone?: "ink" | "green" | "amber"; pill?: { label: string; tone: Tone } };

export function kpis(d: CasePayload): Kpi[] {
  const c = d.case;
  const calc = calcOf(c);
  const snaps = [...d.snapshots].sort((a, b) => a.ts.localeCompare(b.ts));
  const prev = snaps.length >= 2 ? snaps[snaps.length - 2] : null;
  const cur = c.estimate_cents as number | null;
  const diff = prev?.estimate_cents != null && cur != null ? cur - prev.estimate_cents : null;
  const pct = diff != null && prev?.estimate_cents ? (diff / prev.estimate_cents) * 100 : null;
  const st = statusOf(c.status);
  const o = outreachState(d.outreach);
  const conf = c.confidence != null ? `${Math.round(Number(c.confidence) * 100)}% confidence` : "No confidence yet";
  return [
    {
      label: "Previous estimate",
      value: prev ? usd(prev.estimate_cents) : "—",
      sub: prev ? `${shortDate(prev.ts)} · ${prev.reason}` : "No earlier estimate",
    },
    { label: c.type === "anomaly" ? "Excess spend" : "Current estimate", value: usd(cur), sub: calc?.summary ?? "Not estimated yet" },
    {
      label: "Difference",
      value: diff == null ? "—" : signedUsd(diff),
      sub: pct == null ? "Needs two estimates" : `${pct >= 0 ? "+" : "−"}${Math.abs(pct).toFixed(1)}% vs prior`,
      tone: diff ? "green" : "ink",
    },
    { label: "Status", value: st.label, pill: st, sub: o.waiting ? `${conf} · 1 question open` : conf },
  ];
}

// ------------------------------------------------------------------ lifecycle stepper

export type Step = { key: string; label: string; value: string; sub: string; tone: Tone };

export function steps(d: CasePayload, rule: any | null, rulesLoaded: boolean): Step[] {
  const c = d.case;
  const snaps = [...d.snapshots].sort((a, b) => a.ts.localeCompare(b.ts));
  const o = outreachState(d.outreach);
  const out: Step[] = [];

  out.push({ key: "opened", label: c.type === "anomaly" ? "Detected" : "Opened", value: c.type === "anomaly" ? "Spike detected" : "Case opened", sub: shortDate(c.opened_at), tone: "done" });

  out.push(c.status === "skipped_invoiced"
    ? { key: "estimate", label: "Estimate", value: "Not accrued", sub: "Already invoiced", tone: "skipped" }
    : c.estimate_cents != null
      ? { key: "estimate", label: "Estimate", value: `Estimated ${usd(c.estimate_cents)}`, sub: shortDate(snaps[0]?.ts ?? c.opened_at), tone: "done" }
      : { key: "estimate", label: "Estimate", value: "Not estimated", sub: "Runs at close", tone: "pending" });

  out.push(o.outs.length === 0
    ? { key: "owner", label: "Owner", value: "Not needed", sub: "No questions", tone: "skipped" }
    : o.waiting
      ? { key: "owner", label: "Owner", value: "Waiting on reply", sub: `Asked ${shortDate(o.outs.at(-1)?.created_at)}`, tone: "flag" }
      : { key: "owner", label: "Owner", value: "Answered", sub: humanize(o.lastIn?.parsed?.intent), tone: "done" });

  const by: string | null = c.approved_by;
  out.push(c.status === "pending_approval"
    ? { key: "controller", label: "Controller", value: "Awaiting approval", sub: "At or above materiality", tone: "flag" }
    : by === "policy:below_materiality"
      ? { key: "controller", label: "Controller", value: "Not needed", sub: "Below materiality", tone: "skipped" }
      : by
        ? { key: "controller", label: "Controller", value: by.startsWith("owner:") ? "Resolved by owner" : "Approved", sub: shortDate(c.approved_at), tone: "done" }
        : { key: "controller", label: "Controller", value: c.status === "skipped_invoiced" ? "Not needed" : "Not yet", sub: "—", tone: c.status === "skipped_invoiced" ? "skipped" : "pending" });

  out.push(c.status === "reconciled"
    ? { key: "invoice", label: "Invoice", value: "Reconciled", sub: c.invoice_id ? `Invoice #${c.invoice_id}` : "—", tone: "done" }
    : c.status === "skipped_invoiced"
      ? { key: "invoice", label: "Invoice", value: "Already invoiced", sub: c.invoice_id ? `Invoice #${c.invoice_id}` : "—", tone: "done" }
      : { key: "invoice", label: "Invoice", value: "Awaiting invoice", sub: "After close", tone: "pending" });

  out.push(!rulesLoaded
    ? { key: "learning", label: "Learning", value: "Loading…", sub: " ", tone: "pending" }
    : !rule
      ? { key: "learning", label: "Learning", value: "No rule proposed", sub: "—", tone: "skipped" }
      : rule.status === "proposed"
        ? { key: "learning", label: "Learning", value: "Awaiting approval", sub: `Rule #${rule.id}`, tone: "flag" }
        : rule.status === "active"
          ? { key: "learning", label: "Learning", value: "Rule active", sub: `Rule #${rule.id}`, tone: "done" }
          : { key: "learning", label: "Learning", value: "Rule rejected", sub: `Rule #${rule.id}`, tone: "skipped" });
  return out;
}

/** The learning rule this case produced, preferring one still awaiting approval. */
export function ruleForCase(rules: any[] | undefined, caseId: number) {
  const mine = (rules ?? []).filter((r) => r.source_case_id === caseId);
  return mine.find((r) => r.status === "proposed") ?? mine.at(-1) ?? null;
}

// ------------------------------------------------------------------ control checks

export type Check = { code: string; rule: string; evidence: string; result: CheckResult };

/**
 * One row per gate in the close state machine (backend orchestrator/close.py `evaluate`,
 * `invoiced`, `outreach_if_needed`) plus the explainer's number verifier.
 * TODO(backend): these rule descriptions mirror close.py by hand. If the API ever exposes the
 * rule list per case, render that instead so the copy cannot drift from the code.
 */
export function checks(d: CasePayload): Check[] {
  const c = d.case;
  const calc = calcOf(c);
  const flags: string[] = calc?.flags ?? [];
  const queries: any[] = calc?.queries ?? [];
  const exp = c.explanation;
  const o = outreachState(d.outreach);
  const estimated = c.estimate_cents != null;
  const anomaly = c.type === "anomaly";
  const usage = c.type === "usage";
  const skipped = c.status === "skipped_invoiced";

  const list: Check[] = [
    {
      code: "AP-DEDUPE",
      rule: "Never accrue when a matching AP invoice already covers the obligation",
      evidence: anomaly ? "Not applied to anomaly cases" : skipped ? `Invoice #${c.invoice_id} covers it · nothing accrued` : "No matching AP invoice at close",
      result: anomaly ? "na" : "passed",
    },
    {
      code: "MATERIALITY",
      rule: "Accruals at or above materiality need Controller approval",
      evidence: anomaly || skipped ? "Not applied"
        : c.status === "pending_approval" ? `${usd(c.estimate_cents)} is at or above materiality · awaiting Controller`
        : c.approved_by === "policy:below_materiality" ? `${usd(c.estimate_cents)} is below materiality · auto-approved`
        : c.approved_by ? `Approved by ${approverLabel(c.approved_by)}` : "Decided once the case is estimated",
      result: anomaly || skipped ? "na" : c.status === "pending_approval" ? "flagged" : c.approved_by ? "passed" : "pending",
    },
    {
      code: "OWNER-HOLD",
      rule: "Hold the case while a question to the key owner is unanswered",
      evidence: o.outs.length === 0 ? "No owner questions asked" : o.waiting ? `Waiting on ${o.owner ?? "the key owner"}` : `Reply read as “${humanize(o.lastIn?.parsed?.intent)}”`,
      result: o.outs.length === 0 ? "na" : o.waiting ? "flagged" : "passed",
    },
  ];
  if (usage) {
    list.push(
      {
        code: "ANOMALY-HOLD",
        rule: "Hold a usage accrual while an anomaly on the same provider is unresolved",
        evidence: flags.includes("open_anomaly") ? `Open anomaly on ${c.provider_name ?? c.provider_id}` : "No open anomalies on this provider",
        result: !estimated ? "pending" : flags.includes("open_anomaly") ? "flagged" : "passed",
      },
      {
        code: "ORPHAN-KEYS",
        rule: "Exclude spend on keys with no owner until someone claims them",
        evidence: flags.includes("orphan_key_excluded") ? "Unowned key excluded · owner asked" : "Every key with spend has an owner",
        result: !estimated ? "pending" : flags.includes("orphan_key_excluded") ? "flagged" : "passed",
      },
    );
  }
  list.push(
    {
      code: "REPRODUCIBLE",
      rule: "Every number comes from stored SQL that can be re-run",
      evidence: skipped ? "Not applied" : queries.length
        ? `${queries.length} ${queries.length === 1 ? "query" : "queries"} stored · ${queries.reduce((n, q) => n + (q.rows?.length ?? 0), 0)} result rows`
        : estimated ? "No stored queries" : "Stored when the case is estimated",
      result: skipped ? "na" : queries.length ? "passed" : estimated ? "flagged" : "pending",
    },
    {
      code: "VERIFIED-TEXT",
      rule: "Explanations may only cite numbers found in the query results",
      evidence: skipped ? "Not applied" : !exp ? "Explanation not generated yet"
        : exp.agent?.verified ? `Verified · ${exp.agent?.mode ?? "agent"} explainer` : `Verifier rejected the draft · ${exp.agent?.mode ?? "fallback"} text shown`,
      result: skipped ? "na" : !exp ? "pending" : exp.agent?.verified ? "passed" : "flagged",
    },
  );
  return list;
}

export function checkScore(list: Check[]) {
  const applicable = list.filter((x) => x.result !== "na");
  return { passed: applicable.filter((x) => x.result === "passed").length, total: applicable.length };
}

// ------------------------------------------------------------------ assertions

export type Assertion = { label: string; value: string | null };

export function assertions(d: CasePayload): Assertion[] {
  const c = d.case;
  const calc = calcOf(c);
  const list: Assertion[] = [
    { label: c.type === "anomaly" ? "Excess spend" : "Recommended accrual", value: c.estimate_cents != null ? usd(c.estimate_cents) : null },
    { label: "Basis", value: calc?.summary ?? null },
    { label: "Service period", value: periodRange(c.period) },
    { label: "Confidence", value: c.confidence != null ? `${Math.round(Number(c.confidence) * 100)}%` : null },
  ];
  if (c.key_label) list.push({ label: "API key", value: c.key_label });
  if (c.approved_by) list.push({ label: "Approved by", value: `${approverLabel(c.approved_by)} · ${shortTime(c.approved_at)}` });
  return list;
}

// ------------------------------------------------------------------ activity timeline

export type ActivityItem = { id: number; title: string; ts: string; source: Source; tone: Tone; group: string; actor: string };

const GROUPS: [string, string[]][] = [
  ["Detection", ["case_opened"]],
  ["Estimation", ["estimated", "explained", "skipped_already_invoiced"]],
  ["Outreach", ["outreach_sent", "reply_interpreted", "owner_assigned"]],
  ["Approval", ["escalated_to_controller", "anomaly_resolved", "approved"]],
  ["Learning", ["rule_proposed", "rule_replayed", "rule_activated", "rule_rejected"]],
];
export const GROUP_ORDER = [...GROUPS.map(([g]) => g), "Other"];

function eventTitle(a: any): string {
  const d = a.detail ?? {};
  switch (a.action) {
    case "case_opened": return a.actor === "db:anomaly_job" ? "Database opened the case" : "Opened the case";
    case "estimated": return d.status ? `Estimated · ${humanize(d.status)}` : "Estimated the accrual";
    case "explained": return d.verified === false ? "Explanation failed verification" : "Explained the numbers";
    case "skipped_already_invoiced": return "Skipped: already invoiced";
    case "outreach_sent": return "Asked the key owner";
    case "reply_interpreted": return "Read the owner's reply";
    case "owner_assigned": return "Assigned a key owner";
    case "escalated_to_controller": return "Escalated to Controller";
    case "anomaly_resolved": return d.decision ? `Resolved: ${humanize(d.decision)}` : "Resolved the anomaly";
    case "approved": return `Approved by ${humanize(a.actor)}`;
    case "rule_proposed": return d.rule_id ? `Proposed rule #${d.rule_id}` : "Proposed a rule";
    case "rule_replayed": return "Replayed the rule";
    case "rule_activated": return "Activated the rule";
    case "rule_rejected": return "Rejected the rule";
    default: return humanize(a.action);
  }
}

function eventTone(a: any): Tone {
  const d = a.detail ?? {};
  if (a.action === "escalated_to_controller" || a.action === "rule_proposed") return "flag";
  if (a.action === "estimated" && (d.status === "needs_info" || d.status === "pending_approval")) return "flag";
  if (a.action === "explained" && d.verified === false) return "flag";
  return "done";
}

/** Language-model events are agent calls that ran live; fallback agents are deterministic. */
export const sourceOf = (actor: string): Source => (actor.startsWith("agent:") && actor.includes("(live)") ? "llm" : "rule");

export function activity(audit: any[]): ActivityItem[] {
  return audit.map((a) => ({
    id: a.id,
    title: eventTitle(a),
    ts: a.ts,
    source: sourceOf(String(a.actor ?? "")),
    tone: eventTone(a),
    group: GROUPS.find(([, actions]) => actions.includes(a.action))?.[0] ?? "Other",
    actor: a.actor,
  }));
}

export function groupActivity(items: ActivityItem[]) {
  return GROUP_ORDER.map((g) => ({ group: g, items: items.filter((i) => i.group === g) })).filter((g) => g.items.length);
}
