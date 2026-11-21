export type PillVariant = "passed" | "flagged" | "pending" | "na" | "warning" | "neutral";

const STYLE: Record<PillVariant, string> = {
  passed: "bg-green-bg text-green font-semibold",
  flagged: "bg-amber-bg text-amber font-semibold",
  warning: "bg-amber-bg text-amber font-semibold",
  pending: "bg-surface-2 text-ink-2 font-semibold",
  na: "border border-line bg-surface text-ink-3 font-semibold",
  neutral: "border border-line bg-surface-2 px-[9px] text-ink-2 font-normal",
};

/** Figma Pill/* — status pills and meta chips. */
export default function Pill({ variant, children, dot, mono, className = "" }: {
  variant: PillVariant; children: React.ReactNode; dot?: boolean; mono?: boolean; className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-1.5 rounded-full py-[3px] whitespace-nowrap ${variant === "neutral" ? "" : "px-2.5"} ${STYLE[variant]} ${mono ? "font-mono text-[11px]" : "text-xs"} ${className}`}>
      {dot && <span aria-hidden className="size-1.5 rounded-full bg-current" />}
      {children}
    </span>
  );
}

export const RESULT_PILL = {
  passed: { variant: "passed", label: "Passed" },
  flagged: { variant: "flagged", label: "Flagged" },
  pending: { variant: "pending", label: "Pending" },
  na: { variant: "na", label: "N/A" },
} as const;
