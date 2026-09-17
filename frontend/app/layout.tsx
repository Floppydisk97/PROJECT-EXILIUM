import type { ReactNode } from "react";
import "./globals.css";

export const metadata = {
  title: "Project Exilium · Hesperia",
  description: "Mondo persistente autoritativo — selezione del sito di atterraggio",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="it"><body>{children}</body></html>;
}
