import Link from "next/link";
import Image from "next/image";
import LandingActions from "@/components/LandingActions";
import LandingSpendPreview from "@/components/LandingSpendPreview";

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
          <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-2">Catch runaway agents, close the month, and match provider invoices.</p>
          <div className="mt-8 flex flex-wrap gap-3">
            <Link href="/demo" className="tu-btn-primary px-5 py-2.5">Try the demo</Link>
            <Link href="/signup" className="tu-btn-secondary px-5 py-2.5">Connect your data</Link>
          </div>
          <p className="mt-4 text-xs text-ink-3">The demo uses simulated data.</p>
        </div>
        <div className="overflow-hidden rounded-2xl border border-line bg-surface-2 p-3 shadow-[0_24px_80px_rgba(22,33,27,0.12)]">
          <LandingSpendPreview />
        </div>
      </section>
    </main>
  );
}
