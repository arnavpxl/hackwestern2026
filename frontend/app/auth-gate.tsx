"use client";
import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { get, post } from "@/lib/api";

export type Role = "viewer" | "controller" | "admin";
export type Me = { id: number; email: string; name: string; role: Role };

const RANK: Record<Role, number> = { viewer: 0, controller: 1, admin: 2 };
const MeContext = createContext<Me | null>(null);

/** The signed-in user (only inside AuthGate). */
export const useMe = () => useContext(MeContext);

/** True when the user's role is at least `role`. */
export const allowed = (me: Me | null, role: Role) => !!me && RANK[me.role] >= RANK[role];

const PUBLIC_PAGES = new Set(["/", "/login", "/signup"]);

/** Keeps marketing/auth pages public, provisions the demo silently, and protects the connected app. */
export default function AuthGate({ children }: { children: ReactNode }) {
  const path = usePathname();
  const router = useRouter();
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    let active = true;
    if (PUBLIC_PAGES.has(path)) {
      setMe(null);
      return () => { active = false; };
    }
    setMe(undefined);
    get("/api/auth/me")
      .catch(() => path === "/demo" || path.startsWith("/demo/") ? post("/api/auth/demo") : Promise.reject())
      .then(async (user: Me) => {
        const isDemo = path === "/demo" || path.startsWith("/demo/");
        if (!isDemo && user.email === "demo@tokentrueup.local") {
          await post("/api/auth/logout").catch(() => {});
          throw new Error("demo sessions cannot open the connected app");
        }
        if (active) setMe(user);
      })
      .catch(() => {
        if (!active) return;
        setMe(null);
        router.replace(`/login?next=${encodeURIComponent(path)}`);
      });
    return () => { active = false; };
  }, [path, router]);
  if (PUBLIC_PAGES.has(path)) return <>{children}</>;
  if (me === undefined) return <div className="p-8 text-sm text-slate-500">Loading…</div>;
  if (me === null) return <div className="p-8 text-sm text-slate-500">Taking you to sign in…</div>;
  return <MeContext.Provider value={me}>{children}</MeContext.Provider>;
}

export function LoginForm({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      onSignedIn(await post("/api/auth/login", { email, password }));
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="w-full space-y-4">
        <div>
          <h1 className="text-lg font-bold text-ink">TokenTrueUp</h1>
          <p className="text-sm text-slate-500">Sign in to continue</p>
        </div>
        <label className="block text-sm">
          Email
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" type="email" autoComplete="username"
            required value={email} onChange={(e) => setEmail(e.target.value)} />
        </label>
        <label className="block text-sm">
          Password
          <input className="mt-1 w-full rounded border border-slate-300 px-3 py-2" type="password"
            autoComplete="current-password" required value={password} onChange={(e) => setPassword(e.target.value)} />
        </label>
        {error && <p className="text-sm text-rose-700">{error}</p>}
        <button className="btn-primary w-full" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        <p className="text-center text-sm text-ink-3">No account? <Link href="/signup" className="font-semibold text-green hover:underline">Create one</Link></p>
    </form>
  );
}
