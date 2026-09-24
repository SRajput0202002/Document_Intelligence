"use client";

import { useAuth } from "@/hooks/use-auth";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { Sidebar } from "./sidebar";
import { Loader2 } from "lucide-react";

interface AuthLayoutProps {
  children: React.ReactNode;
}

// Pages that don't require authentication
const PUBLIC_PATHS = ["/login", "/setup"];

export function AuthLayout({ children }: AuthLayoutProps) {
  const { isLoading, isAuthenticated, setupRequired } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  const isPublicPath = PUBLIC_PATHS.includes(pathname);

  useEffect(() => {
    if (isLoading) return;

    // If setup is required, redirect to setup page
    if (setupRequired && pathname !== "/setup") {
      router.push("/setup");
      return;
    }

    // If not authenticated and trying to access protected route, redirect to login
    if (!isAuthenticated && !isPublicPath && !setupRequired) {
      router.push("/login");
      return;
    }

    // If authenticated and trying to access login/setup, redirect to extract
    if (isAuthenticated && isPublicPath) {
      router.push("/extract");
      return;
    }
  }, [isLoading, isAuthenticated, setupRequired, pathname, router, isPublicPath]);

  // Show loading state
  if (isLoading) {
    return (
      <div className="flex h-screen items-center justify-center bg-background">
        <div className="flex flex-col items-center gap-4">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Loading...</p>
        </div>
      </div>
    );
  }

  // Show public pages without sidebar
  if (isPublicPath || setupRequired) {
    return <>{children}</>;
  }

  // Show authenticated layout with sidebar
  return (
    <div className="flex h-screen overflow-hidden">
      <Sidebar />
      <main className="min-w-0 flex-1 overflow-auto bg-background relative">
        {children}
      </main>
    </div>
  );
}
