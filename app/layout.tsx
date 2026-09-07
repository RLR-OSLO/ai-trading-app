import "./globals.css";

export const metadata = {
  title: "AI Trading App",
  description: "Secure trading monitor",
  robots: { index: false, follow: false, nocache: true },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="no"><body>{children}</body></html>;
}
