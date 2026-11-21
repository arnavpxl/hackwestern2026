import StatusIcon from "./StatusIcon";

/** Figma Row/Assertion — also used for correspondence rows (custom `right`). */
export default function AssertionRow({ label, value, right, tone = "done" }: {
  label: string; value: React.ReactNode; right?: React.ReactNode; tone?: "done" | "flag" | "pending";
}) {
  return (
    <li className="flex items-start gap-2.5 border-b border-line px-[18px] py-[11px] last:border-b-0">
      <StatusIcon tone={tone} className="mt-px" />
      <div className="min-w-0 flex-1">
        <p className="text-[13px] text-ink">{label}</p>
        <p className="mt-px text-xs break-words text-ink-3 tabular-nums">{value}</p>
      </div>
      {right ?? <span className="shrink-0 text-[11px] text-ink-3">{tone === "done" ? "Recorded" : "Missing"}</span>}
    </li>
  );
}
