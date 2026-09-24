"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useQuery } from "@tanstack/react-query";
import {
  GaugeCircle,
  ChevronLeft,
  ChevronRight,
  LogOut,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
  JobsHoverContent,
  SchemasHoverContent,
  ProvidersHoverContent,
  SettingsHoverContent,
  ExtractHoverContent,
  AdminHoverContent,
  WorkflowsHoverContent,
  LabHoverContent,
} from "./sidebar-hover-cards";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/hooks/use-auth";
import { api } from "@/lib/api";

// Animated icons from lucide-animated
import { SunIcon } from "@/components/ui/sun";
import { MoonIcon } from "@/components/ui/moon";
import { MenuIcon } from "@/components/ui/menu";
import { XIcon } from "@/components/ui/x";
import { BlocksIcon } from "@/components/ui/blocks";
import { SettingsIcon } from "@/components/ui/settings";
import { AlignLeftIcon } from "@/components/ui/align-left";
import { GitCompareArrowsIcon } from "@/components/ui/git-compare-arrows";
import { LayersIcon } from "@/components/ui/layers";
import { UserIcon } from "@/components/ui/user";
import { UsersIcon } from "@/components/ui/users";
import { ChartBarIncreasingIcon } from "@/components/ui/chart-bar-increasing";
import { ZapIcon } from "@/components/ui/zap";
import { FlaskIcon } from "@/components/ui/flask";

interface NavItem {
  label: string;
  href: string;
  icon: React.ComponentType<{ className?: string; size?: number }>;
  isAnimated?: boolean;
  badgeKey?: string; // Key to look up badge count from badgeCounts
  hoverContentKey?: string; // Key to look up hover content component
}

const baseNavItems: NavItem[] = [
  { label: "Extract", href: "/extract", icon: AlignLeftIcon, isAnimated: true, hoverContentKey: "extract" },
  { label: "Jobs", href: "/jobs", icon: GitCompareArrowsIcon, isAnimated: true, hoverContentKey: "jobs" },
  { label: "Schemas", href: "/schemas", icon: LayersIcon, isAnimated: true, hoverContentKey: "schemas", badgeKey: "pendingSchemas" },
  { label: "Workflows", href: "/workflows", icon: ZapIcon, isAnimated: true, hoverContentKey: "workflows", badgeKey: "pendingWorkflows" },
  { label: "Lab", href: "/lab/segmentation", icon: FlaskIcon, isAnimated: true, hoverContentKey: "lab" },
  { label: "Providers", href: "/providers", icon: BlocksIcon, isAnimated: true, hoverContentKey: "providers" },
  { label: "Settings", href: "/settings", icon: SettingsIcon, isAnimated: true, hoverContentKey: "settings" },
];

const adminNavItems: NavItem[] = [
  { label: "Admin", href: "/admin", icon: ChartBarIncreasingIcon, isAnimated: true, hoverContentKey: "admin" },
];

// Map of hover content components
const hoverContentMap: Record<string, React.ComponentType> = {
  extract: ExtractHoverContent,
  jobs: JobsHoverContent,
  schemas: SchemasHoverContent,
  workflows: WorkflowsHoverContent,
  lab: LabHoverContent,
  providers: ProvidersHoverContent,
  settings: SettingsHoverContent,
  admin: AdminHoverContent,
};

export function Sidebar() {
  const pathname = usePathname();
  const { theme, setTheme, resolvedTheme } = useTheme();
  const { user, logout, isAdmin } = useAuth();
  const [mounted, setMounted] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [collapsed, setCollapsed] = useState(false);

  // Fetch pending schema count for admin badge
  const { data: pendingSchemaCount } = useQuery({
    queryKey: ["pendingSchemaCount"],
    queryFn: () => api.getPendingSchemaCount(),
    enabled: isAdmin,
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  // Fetch pending workflow count for admin badge
  const { data: pendingWorkflowCount } = useQuery({
    queryKey: ["pendingWorkflowCount"],
    queryFn: () => api.getPendingWorkflowCount(),
    enabled: isAdmin,
    refetchInterval: 30000, // Refresh every 30 seconds
  });

  // Badge counts for nav items
  const pendingSchemasNum = pendingSchemaCount?.pending_schemas || 0;
  const pendingWorkflowsNum = pendingWorkflowCount?.pending_workflows || 0;
  const badgeCounts: Record<string, number> = {
    pendingSchemas: pendingSchemasNum,
    pendingWorkflows: pendingWorkflowsNum,
    totalPendingReviews: pendingSchemasNum + pendingWorkflowsNum,
  };

  // Build nav items based on user role
  const navItems = isAdmin ? [...baseNavItems, ...adminNavItems] : baseNavItems;

  useEffect(() => {
    setMounted(true);
    // Restore collapsed state from localStorage
    const saved = localStorage.getItem("sidebar-collapsed");
    if (saved) setCollapsed(saved === "true");
  }, []);

  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  useEffect(() => {
    // Save collapsed state
    localStorage.setItem("sidebar-collapsed", String(collapsed));
  }, [collapsed]);

  const isActive = (href: string) => {
    if (href === "/") return pathname === "/";
    return pathname.startsWith(href);
  };

  const ThemeIcon = () => {
    if (!mounted) return <div className="w-4 h-4" />;
    if (resolvedTheme === "dark") return <MoonIcon size={16} className="flex-shrink-0" />;
    return <SunIcon size={16} className="flex-shrink-0" />;
  };

  const cycleTheme = () => {
    if (theme === "light") setTheme("dark");
    else if (theme === "dark") setTheme("system");
    else setTheme("light");
  };

  const getThemeLabel = () => {
    if (!mounted) return "Theme";
    if (theme === "system") return "System";
    if (resolvedTheme === "dark") return "Dark";
    return "Light";
  };

  return (
    <TooltipProvider delayDuration={0}>
      {/* Mobile Menu Button */}
      <Button
        variant="ghost"
        size="icon"
        className="fixed top-3 left-3 z-50 md:hidden h-9 w-9 bg-card border shadow-sm"
        onClick={() => setMobileOpen(true)}
      >
        <MenuIcon size={16} />
      </Button>

      {/* Mobile Overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 bg-black/50 z-40 md:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Mobile Sidebar */}
      <aside
        className={cn(
          "fixed inset-y-0 left-0 z-50 flex flex-col w-56 bg-card border-r transition-transform duration-200 md:hidden",
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        )}
      >
        <div className="flex items-center justify-between h-14 px-4">
          <Link href="/" className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center relative app-icon-container">
              <GaugeCircle className="w-4 h-4 text-primary-foreground animate-spin-slow" />
            </div>
            <span className="font-semibold">IDP Platform</span>
          </Link>
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8"
            onClick={() => setMobileOpen(false)}
          >
            <XIcon size={16} />
          </Button>
        </div>
        <nav className="flex-1 py-3 px-2 space-y-1">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            const badgeCount = item.badgeKey ? badgeCounts[item.badgeKey] : 0;
            return (
              <Link
                key={item.href}
                href={item.href}
                className={cn(
                  "flex items-center gap-3 px-3 h-10 rounded-lg text-sm transition-colors",
                  active
                    ? "bg-primary text-primary-foreground font-medium"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {item.isAnimated ? (
                  <Icon size={16} className="flex-shrink-0" />
                ) : (
                  <Icon className="w-4 h-4 flex-shrink-0" />
                )}
                <span className="flex-1">{item.label}</span>
                {badgeCount > 0 && (
                  <Badge
                    variant={active ? "secondary" : "default"}
                    className="h-5 min-w-[20px] px-1.5 text-xs"
                  >
                    {badgeCount}
                  </Badge>
                )}
              </Link>
            );
          })}
        </nav>
        {/* Bottom Section */}
        <div className="p-3 space-y-1">
          <button
            onClick={cycleTheme}
            className="flex items-center gap-3 px-3 h-10 w-full rounded-lg text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
          >
            <ThemeIcon />
            <span>{getThemeLabel()}</span>
          </button>

          {/* User Menu */}
          {user && (
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <button className="flex items-center gap-3 px-3 h-10 w-full rounded-lg text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
                  <UserIcon size={16} className="flex-shrink-0" />
                  <span className="truncate">{user.display_name || user.username}</span>
                </button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="start" className="w-56">
                <DropdownMenuLabel>
                  <div className="flex flex-col">
                    <span>{user.display_name || user.username}</span>
                    <span className="text-xs font-normal text-muted-foreground capitalize">{user.role}</span>
                  </div>
                </DropdownMenuLabel>
                <DropdownMenuSeparator />
                <DropdownMenuItem onClick={logout} className="text-destructive focus:text-destructive">
                  <LogOut className="mr-2 h-4 w-4" />
                  Sign Out
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          )}
        </div>
      </aside>

      {/* Desktop Sidebar - Collapsible */}
      <aside
        className={cn(
          "hidden md:flex flex-col h-screen bg-card border-r transition-all duration-200 ease-in-out relative",
          collapsed ? "w-[68px]" : "w-56"
        )}
      >
        {/* Expand Button - Centered vertically on sidebar edge */}
        <Button
          variant="outline"
          size="icon"
          className="absolute -right-3 top-1/2 -translate-y-1/2 h-6 w-6 rounded-full bg-card border shadow-sm z-20 hover:bg-muted"
          onClick={() => setCollapsed(!collapsed)}
        >
          {collapsed ? (
            <ChevronRight className="w-3.5 h-3.5" />
          ) : (
            <ChevronLeft className="w-3.5 h-3.5" />
          )}
        </Button>

        {/* Header with Logo */}
        <div className="flex items-center h-14 px-3">
          <Link
            href="/"
            className={cn(
              "flex items-center gap-2.5 flex-1 min-w-0",
              collapsed && "justify-center"
            )}
          >
            <div className="w-8 h-8 rounded-lg bg-primary flex items-center justify-center flex-shrink-0 relative app-icon-container">
              <GaugeCircle className="w-4 h-4 text-primary-foreground animate-spin-slow" />
            </div>
            {!collapsed && (
              <span className="font-semibold truncate">IDP Platform</span>
            )}
          </Link>
        </div>

        {/* Navigation */}
        <nav className="flex-1 py-3 px-2 space-y-1 overflow-y-auto">
          {navItems.map((item) => {
            const Icon = item.icon;
            const active = isActive(item.href);
            const badgeCount = item.badgeKey ? badgeCounts[item.badgeKey] : 0;

            if (collapsed) {
              const HoverContent = item.hoverContentKey ? hoverContentMap[item.hoverContentKey] : null;

              return (
                <HoverCard key={item.href} openDelay={200} closeDelay={100}>
                  <HoverCardTrigger asChild>
                    <Link
                      href={item.href}
                      className={cn(
                        "flex items-center justify-center h-10 w-full rounded-lg transition-colors relative",
                        active
                          ? "bg-primary text-primary-foreground"
                          : "text-muted-foreground hover:bg-muted hover:text-foreground"
                      )}
                    >
                      {item.isAnimated ? (
                        <Icon size={20} />
                      ) : (
                        <Icon className="w-5 h-5" />
                      )}
                      {badgeCount > 0 && (
                        <span className="absolute -top-1 -right-1 h-4 min-w-[16px] px-1 text-[10px] font-medium bg-destructive text-destructive-foreground rounded-full flex items-center justify-center">
                          {badgeCount}
                        </span>
                      )}
                    </Link>
                  </HoverCardTrigger>
                  <HoverCardContent side="right" align="start" sideOffset={16} className="w-72 p-3">
                    {HoverContent ? <HoverContent /> : (
                      <div className="text-sm font-medium">{item.label}</div>
                    )}
                  </HoverCardContent>
                </HoverCard>
              );
            }

            const HoverContent = item.hoverContentKey ? hoverContentMap[item.hoverContentKey] : null;

            return (
              <HoverCard key={item.href} openDelay={300} closeDelay={100}>
                <HoverCardTrigger asChild>
                  <Link
                    href={item.href}
                    className={cn(
                      "flex items-center gap-3 px-3 h-10 rounded-lg text-sm transition-colors",
                      active
                        ? "bg-primary text-primary-foreground font-medium"
                        : "text-muted-foreground hover:bg-muted hover:text-foreground"
                    )}
                  >
                    {item.isAnimated ? (
                      <Icon size={16} className="flex-shrink-0" />
                    ) : (
                      <Icon className="w-4 h-4 flex-shrink-0" />
                    )}
                    <span className="truncate flex-1">{item.label}</span>
                    {badgeCount > 0 && (
                      <Badge
                        variant={active ? "secondary" : "default"}
                        className="h-5 min-w-[20px] px-1.5 text-xs"
                      >
                        {badgeCount}
                      </Badge>
                    )}
                  </Link>
                </HoverCardTrigger>
                <HoverCardContent side="right" align="start" sideOffset={16} className="w-72 p-3">
                  {HoverContent ? <HoverContent /> : (
                    <div className="text-sm font-medium">{item.label}</div>
                  )}
                </HoverCardContent>
              </HoverCard>
            );
          })}
        </nav>

        {/* Theme and User at Bottom */}
        <div className="p-2 space-y-1">
          {/* Theme Toggle */}
          {collapsed ? (
            <Tooltip>
              <TooltipTrigger asChild>
                <button
                  onClick={cycleTheme}
                  className="flex items-center justify-center h-10 w-full rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
                >
                  <ThemeIcon />
                </button>
              </TooltipTrigger>
              <TooltipContent side="right" sideOffset={10}>
                {getThemeLabel()}
              </TooltipContent>
            </Tooltip>
          ) : (
            <button
              onClick={cycleTheme}
              className="flex items-center gap-3 px-3 h-10 w-full rounded-lg text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors"
            >
              <ThemeIcon />
              <span>{getThemeLabel()}</span>
            </button>
          )}

          {/* User Menu */}
          {user && (
            <>
              {collapsed ? (
                <DropdownMenu>
                  <Tooltip>
                    <TooltipTrigger asChild>
                      <DropdownMenuTrigger asChild>
                        <button className="flex items-center justify-center h-10 w-full rounded-lg text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
                          <UserIcon size={20} />
                        </button>
                      </DropdownMenuTrigger>
                    </TooltipTrigger>
                    <TooltipContent side="right" sideOffset={10}>
                      {user.display_name || user.username}
                    </TooltipContent>
                  </Tooltip>
                  <DropdownMenuContent side="right" align="end" className="w-56">
                    <DropdownMenuLabel>
                      <div className="flex flex-col">
                        <span>{user.display_name || user.username}</span>
                        <span className="text-xs font-normal text-muted-foreground capitalize">{user.role}</span>
                      </div>
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={logout} className="text-destructive focus:text-destructive">
                      <LogOut className="mr-2 h-4 w-4" />
                      Sign Out
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              ) : (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <button className="flex items-center gap-3 px-3 h-10 w-full rounded-lg text-sm text-muted-foreground hover:bg-muted hover:text-foreground transition-colors">
                      <UserIcon size={16} className="flex-shrink-0" />
                      <span className="truncate">{user.display_name || user.username}</span>
                    </button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="start" className="w-56">
                    <DropdownMenuLabel>
                      <div className="flex flex-col">
                        <span>{user.display_name || user.username}</span>
                        <span className="text-xs font-normal text-muted-foreground capitalize">{user.role}</span>
                      </div>
                    </DropdownMenuLabel>
                    <DropdownMenuSeparator />
                    <DropdownMenuItem onClick={logout} className="text-destructive focus:text-destructive">
                      <LogOut className="mr-2 h-4 w-4" />
                      Sign Out
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
            </>
          )}
        </div>
      </aside>
    </TooltipProvider>
  );
}
