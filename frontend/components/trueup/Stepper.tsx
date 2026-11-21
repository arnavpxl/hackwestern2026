import type { Step } from "@/lib/case-view";
import StatusIcon from "./StatusIcon";

const VALUE: Record<Step["tone"], string> = {
  done: "font-semibold text-ink",
  flag: "font-semibold text-amber",
  pending: "font-medium text-ink-3",
  skipped: "font-medium text-ink-3",
};

/** Case lifecycle. Six columns on wide screens, wraps to 3 and then 2 per row. */
export default function Stepper({ steps }: { steps: Step[] }) {
  return (
    <ol aria-label="Case progress" className="grid grid-cols-2 gap-y-5 @min-[520px]:grid-cols-3 @min-[760px]:grid-cols-6">
      {steps.map((s, i) => (
        <li key={s.key} className="min-w-0 pr-3" aria-current={s.tone === "flag" ? "step" : undefined}>
          <div className="flex items-center">
            <StatusIcon tone={s.tone} />
            {i < steps.length - 1 && (
              <span aria-hidden className={`h-0.5 flex-1 ${s.tone === "pending" ? "bg-line" : "bg-green-2"}`} />
            )}
          </div>
          <p className="mt-1.5 text-[11px] font-semibold tracking-[0.08em] text-ink-3 uppercase">{s.label}</p>
          <p className={`mt-1.5 text-[13px] tabular-nums ${VALUE[s.tone]}`}>{s.value}</p>
          <p className="mt-1.5 truncate text-xs text-ink-3">{s.sub}</p>
        </li>
      ))}
    </ol>
  );
}
