"use client";

import { useQuery } from "@tanstack/react-query";
import { api, type Provider, type ProvidersResponse } from "@/lib/api";

export function useProviders() {
  return useQuery<ProvidersResponse>({
    queryKey: ["providers"],
    queryFn: () => api.getProviders(),
    staleTime: 5 * 60 * 1000, // 5 minutes
  });
}

export function useOcrProviders() {
  const { data, ...rest } = useProviders();
  return {
    ...rest,
    data: data?.ocr_providers ?? [],
  };
}

export function useLlmProviders() {
  const { data, ...rest } = useProviders();
  return {
    ...rest,
    data: data?.llm_providers ?? [],
  };
}

export function getCostTierLabel(tier: string): string {
  switch (tier) {
    case "free":
      return "FREE";
    case "low":
      return "$";
    case "medium":
      return "$$";
    case "high":
      return "$$$";
    default:
      return tier;
  }
}

export function getCostTierColor(tier: string): string {
  switch (tier) {
    case "free":
      return "text-green-600 dark:text-green-400";
    case "low":
      return "text-blue-600 dark:text-blue-400";
    case "medium":
      return "text-yellow-600 dark:text-yellow-400";
    case "high":
      return "text-red-600 dark:text-red-400";
    default:
      return "";
  }
}

export function getProviderTypeLabel(type: string): string {
  return type === "local" ? "Local" : "Cloud";
}

export function getProviderTypeColor(type: string): string {
  return type === "local"
    ? "text-purple-600 dark:text-purple-400"
    : "text-cyan-600 dark:text-cyan-400";
}
