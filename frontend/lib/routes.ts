"use client";
import { usePathname } from "next/navigation";

/** Route namespace for screens shared by the synthetic demo and connected app. */
export function useAppRoot() {
  const path = usePathname();
  return path === "/demo" || path.startsWith("/demo/") ? "/demo" : "/app";
}
