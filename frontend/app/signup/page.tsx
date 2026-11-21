"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { post } from "@/lib/api";

export default function SignupPage() {
  const router = useRouter();
  const [form, setForm] = useState({ name: "", email: "", password: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await post("/api/auth/signup", form);
      router.replace("/app");
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };
  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-paper px-4 py-12">
      <div className="w-full max-w-sm rounded-xl border border-line bg-white p-7 shadow-sm">
        <h1 className="text-xl font-bold text-ink">Create your TokenTrueUp account</h1>
        <p className="mt-1 text-sm text-ink-3">Connect real provider data after signing up.</p>
        <form onSubmit={submit} className="mt-6 space-y-4">
          <label className="block text-sm">Name<input className="mt-1 w-full rounded border border-line-2 px-3 py-2" required autoComplete="name" value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label>
          <label className="block text-sm">Email<input className="mt-1 w-full rounded border border-line-2 px-3 py-2" required type="email" autoComplete="email" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} /></label>
          <label className="block text-sm">Password<input className="mt-1 w-full rounded border border-line-2 px-3 py-2" required minLength={12} type="password" autoComplete="new-password" value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} /><span className="mt-1 block text-xs text-ink-3">At least 12 characters</span></label>
          {error && <p className="text-sm text-rose-700">{error}</p>}
          <button className="tu-btn-primary w-full" disabled={busy}>{busy ? "Creating account…" : "Create account"}</button>
        </form>
        <p className="mt-4 text-center text-sm text-ink-3">Already have an account? <Link href="/login" className="font-semibold text-green hover:underline">Sign in</Link></p>
      </div>
    </main>
  );
}
