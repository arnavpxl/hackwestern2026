"use client";
import { usePathname } from "next/navigation";

/** Case pages are full-bleed (they own their right rail); every other page keeps the old container. */
export default function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  if (path.includes("/cases/")) {
    return <main className="min-w-0 flex-1 bg-surface">{children}</main>;
  }
  return (
    <main className="min-w-0 flex-1">
      <div className="mx-auto max-w-7xl space-y-4 px-4 py-6">{children}</div>
    </main>
  );
}
