import Link from "next/link";
import { useAppRoot } from "@/lib/routes";

/** Figma Callout/Approval needed. Only rendered while a learned rule from this case is proposed. */
export default function ApprovalCallout({ rule, busy, onApprove }: {
  rule: { id: number; kind: string; rationale: string; replay?: { mape_before?: number; mape_after?: number } | null };
  busy: boolean;
  onApprove: () => void;
}) {
  const root = useAppRoot();
  const r = rule.replay;
  return (
    <section aria-labelledby="approval-title" className="flex flex-wrap items-center gap-3 rounded-[10px] border border-amber-line bg-amber-bg px-4 py-3.5">
      <div className="min-w-[240px] flex-1">
        <h2 id="approval-title" className="text-sm font-semibold text-ink">Proposed rule #{rule.id} needs your approval</h2>
        <p className="mt-0.5 text-[13px] text-ink-2">
          <span className="font-medium">{rule.kind.replace(/_/g, " ")}:</span> {rule.rationale}
          {r?.mape_before != null && r?.mape_after != null && <> Replay cuts mean absolute error from {r.mape_before}% to {r.mape_after}%.</>}
        </p>
      </div>
      <div className="flex gap-2">
        {/* The replay table (before/after by month) lives on the reconciliation page. */}
        <Link href={`${root}/recon`} className="tu-btn-secondary">Review diff</Link>
        <button type="button" className="tu-btn-primary" disabled={busy} onClick={onApprove}>
          {busy ? "Approving…" : "Approve rule"}
        </button>
      </div>
    </section>
  );
}
