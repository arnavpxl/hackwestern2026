"use client";
import { usePathname } from "next/navigation";
import Header from "./header";
import Shell from "./shell";

const PUBLIC_PAGES = new Set(["/", "/login", "/signup"]);

export default function AppFrame({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  if (PUBLIC_PAGES.has(path)) return <>{children}</>;
  const demoMode = path === "/demo" || path.startsWith("/demo/");
  return <><Header demoMode={demoMode} /><Shell>{children}</Shell></>;
}
