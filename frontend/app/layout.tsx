import type { ReactNode } from "react";

export const metadata = {
  title: "Project Exilium",
  description: "Stato del mondo persistente",
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="it"><body>{children}</body></html>;
}
