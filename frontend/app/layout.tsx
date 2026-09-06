import type { Metadata } from "next";
import { Imbue, Victor_Mono } from "next/font/google";
import { headers } from "next/headers";
import "./globals.css";

const display = Imbue({
  variable: "--font-display",
  subsets: ["latin"],
});

const mono = Victor_Mono({
  variable: "--font-mono",
  subsets: ["latin"],
});

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host =
    requestHeaders.get("x-forwarded-host") ??
    requestHeaders.get("host") ??
    "localhost:3000";
  const protocol =
    requestHeaders.get("x-forwarded-proto") ??
    (host.startsWith("localhost") ? "http" : "https");
  const origin = `${protocol}://${host}`;
  const title = "FaceChain Live — See the search. Prove the match.";
  const description =
    "Watch YuNet, SFace, Google Lens, social-profile resolution, and Ethereum verification unfold live.";

  return {
    metadataBase: new URL(origin),
    title,
    description,
    openGraph: {
      title,
      description,
      type: "website",
      url: origin,
      images: [{
        url: `${origin}/og.png`,
        width: 1200,
        height: 630,
        alt: "FaceChain — Find the face. Prove the find.",
      }],
    },
    twitter: {
      card: "summary_large_image",
      title,
      description,
      images: [`${origin}/og.png`],
    },
  };
}

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className={`${display.variable} ${mono.variable}`}>{children}</body>
    </html>
  );
}
