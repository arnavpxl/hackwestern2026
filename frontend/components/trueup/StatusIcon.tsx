import type { Tone } from "@/lib/case-view";

const LABEL: Record<Tone, string> = { done: "Done", flag: "Needs attention", pending: "Pending", skipped: "Not needed" };

/** Figma Status/Done and Status/Flag (16px), plus a dashed pending state. */
export default function StatusIcon({ tone, label, className = "" }: { tone: Tone; label?: string; className?: string }) {
  const a11y = label === "" ? { "aria-hidden": true } : { role: "img", "aria-label": label ?? LABEL[tone] };
  if (tone === "done") {
    return (
      <span {...a11y} className={`inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-green-2 ${className}`}>
        <img src="/trueup/icon-check.svg" alt="" width={10} height={10} />
      </span>
    );
  }
  if (tone === "flag") {
    return (
      <span {...a11y} className={`inline-flex size-4 shrink-0 items-center justify-center rounded-full bg-amber text-[10px] leading-none font-bold text-white ${className}`}>!</span>
    );
  }
  return (
    <span {...a11y} className={`inline-flex size-4 shrink-0 items-center justify-center rounded-full border-[1.5px] border-dashed border-line-2 bg-surface text-[9px] leading-none font-bold text-ink-3 ${className}`}>–</span>
  );
}
