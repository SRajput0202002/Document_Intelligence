import type { Metadata } from "next";
import { Inter } from "next/font/google";
import "./globals.css";
import { Toaster } from "@/components/ui/toast";
import { QueryProvider } from "@/components/providers/query-provider";
import { ThemeProvider } from "@/components/providers/theme-provider";
import { SettingsProvider } from "@/components/providers/settings-provider";
import { AuthProvider } from "@/components/providers/auth-provider";
import { AuthLayout } from "@/components/layout/auth-layout";

const inter = Inter({ subsets: ["latin"] });

export const metadata: Metadata = {
  title: "IDP Platform",
  description: "Intelligent Document Processing with mix-and-match OCR and LLM providers",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en" suppressHydrationWarning>
      <body className={inter.className}>
        <ThemeProvider
          attribute="class"
          defaultTheme="system"
          enableSystem
          disableTransitionOnChange
        >
          <QueryProvider>
            <AuthProvider>
              <SettingsProvider>
                <AuthLayout>{children}</AuthLayout>
                <Toaster />
              </SettingsProvider>
            </AuthProvider>
          </QueryProvider>
        </ThemeProvider>
      </body>
    </html>
  );
}
