"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { LoginForm } from "../auth-gate";

export default function LoginPage() {
  const router = useRouter();
  return (
    <main className="flex min-h-screen w-full items-center justify-center bg-paper px-4 py-12">
      <div className="w-full max-w-sm rounded-xl border border-line bg-white p-7 shadow-sm">
        <LoginForm onSignedIn={() => router.replace("/app")} />
        <Link href="/demo" className="mt-4 block text-center text-sm text-ink-3 hover:text-green">Or explore the demo</Link>
      </div>
    </main>
  );
}
