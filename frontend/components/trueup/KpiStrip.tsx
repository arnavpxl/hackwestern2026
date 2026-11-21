import type { Kpi } from "@/lib/case-view";
import Pill from "./Pill";

const VALUE_TONE = { ink: "text-ink", green: "text-green-2", amber: "text-amber" } as const;
const PILL_VARIANT = { done: "passed", flag: "flagged", pending: "pending", skipped: "na" } as const;

/** Four KPIs; 4-up on wide containers, 2×2 below. Cell borders come from a 1px gap on a line-coloured grid. */
export default function KpiStrip({ items }: { items: Kpi[] }) {
  return (
    <dl className="grid grid-cols-2 gap-px overflow-hidden rounded-[10px] border border-line bg-line @min-[640px]:grid-cols-4">
      {items.map((k) => (
        <div key={k.label} className="flex min-w-0 flex-col gap-1 bg-surface px-[18px] py-3.5">
          <dt className="tu-eyebrow">{k.label}</dt>
          <dd className="min-h-[37px]">
            {k.pill
              ? <span className="flex h-[37px] items-center"><Pill variant={PILL_VARIANT[k.pill.tone]} dot>{k.pill.label}</Pill></span>
              : <span className={`font-serif text-[28px] leading-[37px] tabular-nums ${VALUE_TONE[k.tone ?? "ink"]}`}>{k.value}</span>}
          </dd>
          <dd className="truncate text-xs text-ink-3 tabular-nums" title={k.sub}>{k.sub}</dd>
        </div>
      ))}
    </dl>
  );
}
