"use client";
import { createContext, useContext, useEffect, useState, type FormEvent, type ReactNode } from "react";
import { get, post } from "@/lib/api";

export type Role = "viewer" | "controller" | "admin";
export type Me = { id: number; email: string; name: string; role: Role };

const RANK: Record<Role, number> = { viewer: 0, controller: 1, admin: 2 };
const MeContext = createContext<Me | null>(null);

/** The signed-in user (only inside AuthGate). */
export const useMe = () => useContext(MeContext);

/** True when the user's role is at least `role`. */
export const allowed = (me: Me | null, role: Role) => !!me && RANK[me.role] >= RANK[role];

/** Shows a sign-in form until the server confirms a session, then renders the app. */
export default function AuthGate({ children }: { children: ReactNode }) {
  const [me, setMe] = useState<Me | null | undefined>(undefined);
  useEffect(() => {
    get("/api/auth/me").then(setMe).catch(() => setMe(null));
  }, []);
  if (me === undefined) return <div className="p-8 text-sm text-slate-500">Loading…</div>;
  if (me === null) return <LoginForm onSignedIn={setMe} />;
  return <MeContext.Provider value={me}>{children}</MeContext.Provider>;
}

function LoginForm({ onSignedIn }: { onSignedIn: (me: Me) => void }) {
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
    <div className="flex min-h-screen items-center justify-center bg-slate-50 px-4">
      <form onSubmit={submit} className="w-full max-w-sm space-y-4 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
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
      </form>
    </div>
  );
}
