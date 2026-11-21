/** Bordered card with the Figma "Card header" (serif title, subtitle, right slot). */
export default function Card({ title, subtitle, right, children, className = "", id }: {
  title: string; subtitle?: string; right?: React.ReactNode; children: React.ReactNode; className?: string; id?: string;
}) {
  const headingId = id ? `${id}-title` : undefined;
  return (
    <section aria-labelledby={headingId} className={`overflow-hidden rounded-[10px] border border-line bg-surface ${className}`}>
      <header className="flex flex-wrap items-center justify-between gap-x-4 gap-y-2 border-b border-line px-[18px] py-3.5">
        <div className="min-w-0">
          <h2 id={headingId} className="font-serif text-xl leading-tight text-ink">{title}</h2>
          {subtitle && <p className="mt-0.5 text-xs text-ink-3">{subtitle}</p>}
        </div>
        {right}
      </header>
      {children}
    </section>
  );
}

export function EmptyRow({ children }: { children: React.ReactNode }) {
  return <p className="px-[18px] py-4 text-[13px] text-ink-3">{children}</p>;
}

export function SkeletonRows({ n = 3 }: { n?: number }) {
  return (
    <div aria-hidden className="divide-y divide-line">
      {Array.from({ length: n }, (_, i) => (
        <div key={i} className="flex gap-3 px-[18px] py-[11px]">
          <span className="tu-skeleton h-4 w-14" />
          <span className="flex-1 space-y-1.5"><span className="tu-skeleton block h-3.5 w-3/4" /><span className="tu-skeleton block h-3 w-1/3" /></span>
        </div>
      ))}
    </div>
  );
}
