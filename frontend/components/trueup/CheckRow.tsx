import type { Check } from "@/lib/case-view";
import Pill, { RESULT_PILL } from "./Pill";

/** Figma Row/Control check */
export default function CheckRow({ check }: { check: Check }) {
  const p = RESULT_PILL[check.result];
  return (
    <li className="flex flex-wrap items-start gap-x-3.5 gap-y-1 border-b border-line px-[18px] py-[11px] last:border-b-0">
      <span className="w-[92px] shrink-0 pt-px font-mono text-[11px] text-ink-3 max-[480px]:w-full">{check.code}</span>
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-ink">{check.rule}</p>
        <p className="mt-0.5 font-mono text-[11px] text-ink-3 tabular-nums">{check.evidence}</p>
      </div>
      <Pill variant={p.variant} className="shrink-0">{p.label}</Pill>
    </li>
  );
}
