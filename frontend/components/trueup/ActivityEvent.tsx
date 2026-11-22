import { shortTime, type ActivityItem } from "@/lib/case-view";
import StatusIcon from "./StatusIcon";

export function SourceBadge({ source }: { source: ActivityItem["source"] }) {
  return source === "llm"
    ? <span className="rounded bg-violet-bg px-1.5 py-px text-[10px] font-medium text-violet">LLM</span>
    : <span className="rounded border border-line bg-surface-2 px-1.5 py-px text-[10px] font-medium text-ink-2">Rule</span>;
}

/** Figma Row/Activity event */
export default function ActivityEvent({ item }: { item: ActivityItem }) {
  return (
    <li className="flex items-start gap-3 py-2">
      <StatusIcon tone={item.tone} className="mt-px" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-ink">{item.title}</p>
        <p className="mt-[3px] flex flex-wrap items-center gap-1.5 font-mono text-[11px] text-ink-3 tabular-nums">
          <time dateTime={item.ts}>{shortTime(item.ts)}</time>
          <SourceBadge source={item.source} />
          <span>#{item.id}</span>
        </p>
      </div>
    </li>
  );
}
