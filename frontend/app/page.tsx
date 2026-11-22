import Link from "next/link";
import Image from "next/image";
import LandingActions from "@/components/LandingActions";

export default function Landing() {
  return (
    <main className="min-h-screen w-full bg-paper text-ink">
      <nav className="mx-auto flex max-w-7xl items-center justify-between px-6 py-6">
        <Link href="/" aria-label="True Token Up home" className="tu-focus rounded">
          <Image src="/tokentrueup-logo.svg" alt="True Token Up" width={420} height={200} priority className="h-auto w-[150px] sm:w-[168px]" />
        </Link>
        <LandingActions />
      </nav>
      <section className="mx-auto grid max-w-7xl items-center gap-12 px-6 py-20 lg:grid-cols-[0.85fr_1.15fr] lg:py-28">
        <div>
          <p className="tu-eyebrow text-green">AI spend operations</p>
          <h1 className="mt-4 max-w-2xl font-serif text-5xl leading-[0.98] sm:text-6xl">Know where every AI dollar went.</h1>
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">Detect runaway agents, close usage spend, and reconcile provider invoices with evidence your finance team can trust.</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/demo" className="tu-btn-primary px-5 py-3">Explore the synthetic demo</Link>
            <Link href="/signup" className="tu-btn-secondary px-5 py-3">Connect your own data</Link>
          </div>
          <p className="mt-4 text-xs text-ink-3">The demo uses synthetic providers, credentials, usage, invoices, and spend.</p>
        </div>
        <div className="overflow-hidden rounded-2xl border border-line bg-surface p-3 shadow-[0_24px_80px_rgba(22,33,27,0.12)]">
          <div className="rounded-xl border border-line bg-slate-50 p-5">
            <div className="flex items-center justify-between"><span className="font-semibold">Spend per minute</span><span className="pill bg-green-bg text-green">Live</span></div>
            <div className="mt-8 flex h-64 items-end gap-2 border-b border-l border-slate-300 px-3">
              {[31,34,32,36,35,38,37,39,42,40,43,44,46,45,49,47,51,55,52,58,56,62,60,66].map((height, i) => (
                <div key={i} className="min-w-0 flex-1 rounded-t bg-green/80" style={{ height: `${height}%` }} />
              ))}
            </div>
            <div className="mt-5 grid grid-cols-3 gap-3">
              {[["Month to date", "$184,290"], ["Current burn", "$391/h"], ["Open cases", "3"]].map(([label, value]) => (
                <div key={label} className="rounded-lg border border-line bg-white p-3"><div className="text-[10px] uppercase tracking-wide text-ink-3">{label}</div><div className="mt-1 font-semibold">{value}</div></div>
              ))}
            </div>
          </div>
        </div>
      </section>
    </main>
  );
}
