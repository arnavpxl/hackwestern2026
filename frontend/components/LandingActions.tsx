"use client";

import Link from "next/link";
import { useApi } from "@/lib/api";
import type { Me } from "@/app/auth-gate";

export default function LandingActions() {
  const { data: me, error } = useApi<Me>("/api/auth/me", 0);

  if (!me && !error) {
    return (
      <div className="flex h-[42px] w-[238px] items-center justify-end" role="status" aria-label="Checking your session">
        <span className="tu-skeleton block h-10 w-44 rounded-lg" aria-hidden="true" />
      </div>
    );
  }

  // The public demo has a short-lived session, but it is not a connected workspace account.
  if (me && me.email !== "demo@tokentrueup.local") {
    return <Link href="/app" className="tu-btn-primary px-5 py-3">Go to your workspace</Link>;
  }

  return (
    <div className="flex items-center gap-2">
      <Link href="/login" className="tu-btn-ghost">Sign in</Link>
      <Link href="/signup" className="tu-btn-primary">Create account</Link>
    </div>
  );
}
