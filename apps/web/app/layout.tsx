import type { Metadata } from "next";
import "./globals.css";
import { Shell } from "@/components/Shell";

export const metadata: Metadata = {
  title: "PlacePilot — placement agent that asks before applying",
  description:
    "Upload a resume, name target roles. PlacePilot searches, tailors, tracks and coaches. It sends nothing without your yes.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <Shell>{children}</Shell>
      </body>
    </html>
  );
}
