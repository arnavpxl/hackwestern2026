"use client";
import { useRef } from "react";

export type TabDef<K extends string> = { key: K; label: string; count?: string | number };

/** WAI-ARIA tabs with roving tabindex: ←/→ move, Home/End jump, selection follows focus. */
export default function Tabs<K extends string>({ tabs, value, onChange, idPrefix }: {
  tabs: TabDef<K>[]; value: K; onChange: (k: K) => void; idPrefix: string;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const onKey = (e: React.KeyboardEvent, i: number) => {
    const last = tabs.length - 1;
    const next = e.key === "ArrowRight" ? (i === last ? 0 : i + 1)
      : e.key === "ArrowLeft" ? (i === 0 ? last : i - 1)
      : e.key === "Home" ? 0 : e.key === "End" ? last : null;
    if (next == null) return;
    e.preventDefault();
    onChange(tabs[next].key);
    refs.current[next]?.focus();
  };
  return (
    <div role="tablist" aria-label="Case sections" className="flex gap-[22px] overflow-x-auto border-b border-line [scrollbar-width:none]">
      {tabs.map((t, i) => {
        const on = t.key === value;
        return (
          <button key={t.key} ref={(el) => { refs.current[i] = el; }} type="button" role="tab"
            id={`${idPrefix}-tab-${t.key}`} aria-selected={on} aria-controls={`${idPrefix}-panel-${t.key}`}
            tabIndex={on ? 0 : -1} onClick={() => onChange(t.key)} onKeyDown={(e) => onKey(e, i)}
            className={`tu-focus relative flex shrink-0 focus-visible:outline-offset-[-2px] items-baseline gap-[5px] rounded-t py-2.5 text-sm whitespace-nowrap ${on
              ? "font-semibold text-ink after:absolute after:inset-x-0 after:bottom-0 after:h-0.5 after:bg-ink"
              : "text-ink-3 hover:text-ink-2"}`}>
            {t.label}
            {t.count != null && <span className="font-mono text-[11px] font-normal text-ink-3">{t.count}</span>}
          </button>
        );
      })}
    </div>
  );
}

export function TabPanel({ idPrefix, k, value, children }: { idPrefix: string; k: string; value: string; children: React.ReactNode }) {
  return (
    <div role="tabpanel" id={`${idPrefix}-panel-${k}`} aria-labelledby={`${idPrefix}-tab-${k}`} hidden={k !== value} tabIndex={0}
      className="tu-focus rounded">
      {k === value && children}
    </div>
  );
}
