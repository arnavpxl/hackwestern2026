import Image from "next/image";

type LoadingStateProps = {
  label?: string;
  detail?: string;
  variant?: "page" | "dashboard" | "card";
};

/** A shared, accessible loading state for route, authentication, and API waits. */
export default function LoadingState({
  label = "Loading your workspace",
  detail = "Fetching the latest data…",
  variant = "card",
}: LoadingStateProps) {
  if (variant === "dashboard") {
    return (
      <div className="space-y-4" role="status" aria-live="polite" aria-busy="true">
        <LoadingCard label={label} detail={detail} announce={false} />
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-3" aria-hidden="true">
          <div className="tu-skeleton h-24" />
          <div className="tu-skeleton h-24 [animation-delay:120ms]" />
          <div className="tu-skeleton h-24 [animation-delay:240ms]" />
        </div>
        <div className="rounded-lg border border-line bg-surface p-5 shadow-sm" aria-hidden="true">
          <div className="tu-skeleton h-5 w-48" />
          <div className="mt-3 tu-skeleton h-3 w-72 max-w-full" />
          <div className="mt-7 tu-skeleton h-[clamp(240px,38vh,390px)]" />
        </div>
      </div>
    );
  }

  if (variant === "page") {
    return (
      <main className="flex min-h-screen w-full items-center justify-center bg-paper p-6" role="status" aria-live="polite" aria-busy="true">
        <div className="flex max-w-sm flex-col items-center text-center">
          <Image src="/tokentrueup-logo.svg" alt="True Token Up" width={420} height={200} priority className="h-auto w-[168px]" />
          <LoaderMark />
          <p className="mt-5 font-medium text-ink">{label}</p>
          <p className="mt-1 text-sm text-ink-3">{detail}</p>
        </div>
      </main>
    );
  }

  return <LoadingCard label={label} detail={detail} />;
}

function LoadingCard({ label, detail, announce = true }: { label: string; detail: string; announce?: boolean }) {
  return (
    <section className="card flex min-h-24 items-center gap-4" role={announce ? "status" : undefined} aria-live={announce ? "polite" : undefined} aria-busy="true">
      <LoaderMark compact />
      <div>
        <p className="font-medium text-ink">{label}</p>
        <p className="mt-0.5 text-sm text-ink-3">{detail}</p>
      </div>
    </section>
  );
}

function LoaderMark({ compact = false }: { compact?: boolean }) {
  return (
    <span className={`${compact ? "size-10" : "mt-8 size-12"} relative inline-flex shrink-0 items-center justify-center`} aria-hidden="true">
      <span className="absolute inset-0 animate-spin rounded-full border-[3px] border-green-bg border-t-green" />
      <span className="size-2 rounded-full bg-green" />
    </span>
  );
}
