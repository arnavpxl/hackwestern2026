import type { Metadata } from "next";
import Header from "./header";
import "./globals.css";

export const metadata: Metadata = {
  title: "TokenTrueUp",
  description: "Month-end accruals and reconciliation for AI usage spend, on Tiger Data (synthetic demo)",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Header />
        <main className="mx-auto max-w-7xl space-y-4 px-4 py-6">{children}</main>
      </body>
    </html>
  );
}
