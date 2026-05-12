import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "BioSlice5X — 5-axis slicer for FRESH bioprinting",
  description:
    "Open-source 5-axis slicer + viewer + recipe builder for syringe bioprinting in the FRESH support-bath workflow (Feinberg Lab, CMU). Cell-viability-aware path validation. RepRapFirmware G-code output.",
  authors: [{ name: "BioSlice5X Contributors" }],
  openGraph: {
    title: "BioSlice5X — open-source 5-axis bioprinting slicer",
    description:
      "Generate 5-axis G-code for FRESH/CHIPS bioprinting in your browser. Cell-viability-aware. Open source.",
    type: "website",
  },
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="en">
      <body className="min-h-full antialiased">{children}</body>
    </html>
  );
}
