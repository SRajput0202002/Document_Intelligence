"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { GaugeCircle, GanttChart, GitCompareArrows, Braces } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";

// Animated icons from lucide-animated
import { SunIcon } from "@/components/ui/sun";
import { MoonIcon } from "@/components/ui/moon";
import { SettingsIcon } from "@/components/ui/settings";

interface NavItem {
  href: string;
  label: string;
  icon: React.ComponentType<{ className?: string; size?: string | number }>;
  isAnimated?: boolean;
}

const navItems: NavItem[] = [
  { href: "/", label: "Extract", icon: GanttChart },
  { href: "/jobs", label: "Jobs", icon: GitCompareArrows },
  { href: "/schemas", label: "Schemas", icon: Braces },
  { href: "/providers", label: "Providers", icon: SettingsIcon, isAnimated: true },
];

export function Header() {
  const pathname = usePathname();
  const { setTheme } = useTheme();

  return (
    <header className="sticky top-0 z-50 w-full border-b bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="container flex h-14 items-center">
        <div className="mr-4 flex">
          <Link href="/" className="mr-6 flex items-center space-x-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center relative app-icon-container">
              <GaugeCircle className="w-4 h-4 text-primary-foreground animate-spin-slow" />
            </div>
            <span className="font-bold">IDP Platform</span>
          </Link>
          <nav className="flex items-center space-x-6 text-sm font-medium">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    "flex items-center gap-2 transition-colors hover:text-foreground/80",
                    isActive ? "text-foreground" : "text-foreground/60"
                  )}
                >
                  {item.isAnimated ? (
                    <Icon size={16} />
                  ) : (
                    <Icon className="h-4 w-4" />
                  )}
                  {item.label}
                </Link>
              );
            })}
          </nav>
        </div>
        <div className="flex flex-1 items-center justify-end space-x-2">
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="ghost" size="icon">
                <SunIcon size={19} className="rotate-0 scale-100 transition-all dark:-rotate-90 dark:scale-0" />
                <MoonIcon size={19} className="absolute rotate-90 scale-0 transition-all dark:rotate-0 dark:scale-100" />
                <span className="sr-only">Toggle theme</span>
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onClick={() => setTheme("light")}>
                Light
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme("dark")}>
                Dark
              </DropdownMenuItem>
              <DropdownMenuItem onClick={() => setTheme("system")}>
                System
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </div>
    </header>
  );
}
