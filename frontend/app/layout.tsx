import type { Metadata } from "next";
import { Inter, JetBrains_Mono, Newsreader } from "next/font/google";
import AuthGate from "./auth-gate";
import AppFrame from "./app-frame";
import "./globals.css";

const inter = Inter({ subsets: ["latin"], variable: "--font-inter", display: "swap" });
const newsreader = Newsreader({ subsets: ["latin"], variable: "--font-newsreader", display: "swap" });
const jetbrains = JetBrains_Mono({ subsets: ["latin"], variable: "--font-jetbrains", display: "swap" });

export const metadata: Metadata = {
  title: "TokenTrueUp",
  description: "Month-end accruals and reconciliation for AI usage spend, on Tiger Data (synthetic demo)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${newsreader.variable} ${jetbrains.variable}`}>
      <body className="min-[761px]:flex min-[761px]:min-h-screen">
        <AuthGate>
          <AppFrame>{children}</AppFrame>
        </AuthGate>
      </body>
    </html>
  );
}
