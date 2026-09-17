import type { Metadata } from "next";
import "./globals.css";
import { LocaleProvider } from "@/lib/locale";
import { NavGate } from "@/components/NavGate";

export const metadata: Metadata = {
  title: "PMS — Agile Project OS",
  description: "Scrumban project operating system",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="ru">
      <body>
        <LocaleProvider>
          <NavGate />
          {children}
        </LocaleProvider>
      </body>
    </html>
  );
}
