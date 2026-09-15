"use client";

import { SettingsProvider as BaseSettingsProvider } from "@/hooks/use-settings";

export function SettingsProvider({ children }: { children: React.ReactNode }) {
  return <BaseSettingsProvider>{children}</BaseSettingsProvider>;
}
