"use client";

import React, { createContext, useContext, useState, useEffect, useCallback, ReactNode } from "react";
import type { UserSettings, SettingsResponse, SettingsOptions } from "@/lib/api";

interface SettingsContextType {
  settings: UserSettings | null;
  defaults: UserSettings | null;
  options: SettingsOptions | null;
  loading: boolean;
  error: string | null;
  updateSettings: (updates: Partial<UserSettings>) => Promise<UserSettings>;
  resetSettings: () => Promise<void>;
  refreshSettings: () => Promise<void>;
}

// NO HARDCODED DEFAULTS - All defaults come from the backend database
// The backend's DEFAULT_USER_SETTINGS in api/database/models.py is the single source of truth

const SettingsContext = createContext<SettingsContextType | undefined>(undefined);

export function SettingsProvider({ children }: { children: ReactNode }) {
  const [settings, setSettings] = useState<UserSettings | null>(null);
  const [defaults, setDefaults] = useState<UserSettings | null>(null);
  const [options, setOptions] = useState<SettingsOptions | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchSettings = useCallback(async () => {
    try {
      setLoading(true);
      setError(null);

      // Dynamic import to avoid SSR issues
      const { api } = await import("@/lib/api");

      console.log("[useSettings] Fetching settings...");

      const [settingsRes, optionsRes] = await Promise.all([
        api.getSettings(),
        api.getSettingsOptions(),
      ]);

      console.log("[useSettings] Settings response:", settingsRes);
      console.log("[useSettings] Options response:", optionsRes);

      if (!settingsRes?.settings || !settingsRes?.defaults) {
        throw new Error("Invalid settings response from server");
      }

      setSettings(settingsRes.settings);
      setDefaults(settingsRes.defaults);
      setOptions(optionsRes);
      console.log("[useSettings] Settings loaded successfully");
    } catch (err) {
      console.error("[useSettings] Failed to fetch settings:", err);
      setError(err instanceof Error ? err.message : "Failed to load settings from server");
      // NO FALLBACK TO HARDCODED VALUES - settings/defaults remain null
      // The UI should show an error state and retry option
    } finally {
      setLoading(false);
      console.log("[useSettings] Loading complete, loading=false");
    }
  }, []);

  const updateSettings = useCallback(async (updates: Partial<UserSettings>): Promise<UserSettings> => {
    try {
      setError(null);
      const { api } = await import("@/lib/api");
      const response = await api.updateSettings(updates, true);
      setSettings(response.settings);
      return response.settings;
    } catch (err) {
      console.error("Failed to update settings:", err);
      setError(err instanceof Error ? err.message : "Failed to update settings");
      throw err;
    }
  }, []);

  const resetSettings = useCallback(async () => {
    try {
      setError(null);
      const { api } = await import("@/lib/api");
      const response = await api.resetSettings();
      setSettings(response.settings);
    } catch (err) {
      console.error("Failed to reset settings:", err);
      setError(err instanceof Error ? err.message : "Failed to reset settings");
      throw err;
    }
  }, []);

  const refreshSettings = useCallback(async () => {
    await fetchSettings();
  }, [fetchSettings]);

  // Fetch settings on mount
  useEffect(() => {
    fetchSettings();
  }, [fetchSettings]);

  return (
    <SettingsContext.Provider
      value={{
        settings,
        defaults,
        options,
        loading,
        error,
        updateSettings,
        resetSettings,
        refreshSettings,
      }}
    >
      {children}
    </SettingsContext.Provider>
  );
}

export function useSettings() {
  const context = useContext(SettingsContext);
  if (context === undefined) {
    throw new Error("useSettings must be used within a SettingsProvider");
  }
  return context;
}

// Hook to get a specific setting - only uses values from the database (via API)
export function useSetting<K extends keyof UserSettings>(key: K): UserSettings[K] | undefined {
  const { settings, defaults } = useSettings();
  // First check user's settings, then fall back to server defaults
  // NO hardcoded fallbacks - if both are null/undefined, return undefined
  return settings?.[key] ?? defaults?.[key];
}
