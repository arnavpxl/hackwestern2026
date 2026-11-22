const STYLE: Record<string, string> = {
  approved: "bg-emerald-100 text-emerald-800",
  reconciled: "bg-sky-100 text-sky-800",
  pending_approval: "bg-amber-100 text-amber-800",
  needs_info: "bg-rose-100 text-rose-800",
  estimated: "bg-slate-100 text-ink-2",
  open: "bg-slate-100 text-ink-2",
  skipped_invoiced: "bg-slate-100 text-ink-3",
  matched: "bg-emerald-100 text-emerald-800",
  duplicate: "bg-rose-100 text-rose-800",
  received: "bg-slate-100 text-ink-2",
  proposed: "bg-amber-100 text-amber-800",
  active: "bg-emerald-100 text-emerald-800",
  rejected: "bg-slate-100 text-ink-3",
};

export default function Status({ s }: { s: string }) {
  return <span className={`pill ${STYLE[s] ?? "bg-slate-100 text-ink-2"}`}>{s.replace(/_/g, " ")}</span>;
}
