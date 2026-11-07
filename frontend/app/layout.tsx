import type { Metadata, Viewport } from "next";
import AppShell from "@/components/AppShell";
import { brand } from "@/config/brand";
import "./globals.css";

export const metadata: Metadata = {
  title: brand.name,
  description: brand.tagline,
};

// 工作台是深色界面，让手机浏览器地址栏、状态栏也跟着变深，不然顶部会出现一条刺眼的白条。
export const viewport: Viewport = {
  width: "device-width",
  initialScale: 1,
  themeColor: [
    { media: "(prefers-color-scheme: light)", color: "#0F1117" },
    { media: "(prefers-color-scheme: dark)", color: "#0F1117" },
  ],
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body
        className="antialiased"
      >
        <AppShell>{children}</AppShell>
      </body>
    </html>
  );
}
