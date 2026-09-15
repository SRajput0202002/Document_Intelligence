"use client";

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { api, TextMatch, RegionMatch, TextIndexResponse } from '@/lib/api';

// Re-export types that consumers may need
export type { TextMatch, RegionMatch, TextIndexResponse } from '@/lib/api';

/**
 * Highlight colors palette - transparent (border only)
 */
export const HIGHLIGHT_COLORS = [
  'transparent',   // Blue
  'transparent',   // Green
  'transparent',   // Orange
  'transparent',   // Purple
  'transparent',   // Pink
  'transparent',   // Teal
  'transparent',   // Amber
  'transparent',   // Indigo
];

/**
 * Border colors for highlights - solid colors for visibility
 */
export const HIGHLIGHT_BORDER_COLORS = [
  '#3b82f6',    // Blue
  '#22c55e',    // Green
  '#f97316',    // Orange
  '#a855f7',    // Purple
  '#ec4899',    // Pink
  '#14b8a6',    // Teal
  '#f59e0b',    // Amber
  '#6366f1',    // Indigo
];

export interface HighlightItem {
  text: string;
  color: string;
  borderColor: string;
  isSelected: boolean;
  polygon?: number[][];  // Normalized 0-1 coords — when present, skip text-layer search
  /** 1-based page from region_fields; used by PDFViewer to filter polygon highlights per page */
  page?: number;
}

export interface PDFHighlightingState {
  fieldIndex: Record<string, TextMatch[]>;
  /** Polygon matches from OCR regions (may exist without text-layer `fields` entries). */
  regionIndex: Record<string, RegionMatch[]>;
  /** Sorted union of keys present in `fields` or `region_fields` — for UI key lists. */
  indexedFieldKeys: string[];
  selectedField: string | null;
  hoveredField: string | null;
  activeHighlights: TextMatch[];
  highlightPage: number | null;
  isLoading: boolean;
  error: string | null;
  showAll: boolean;
  selectField: (field: string | null) => void;
  hoverField: (field: string | null) => void;
  toggleShowAll: () => void;
  hasHighlights: (field: string) => boolean;
  getHighlightsForPDF: () => HighlightItem[];
  getFieldColor: (field: string) => string;
  fieldCount: number;
}

/**
 * Hook for managing PDF text highlighting state.
 *
 * Fetches the text position index for a job and provides
 * state management for highlighting extracted fields in the PDF viewer.
 *
 * @param jobId - The job ID to fetch the text index for
 * @param partName - Optional ``job_parts.part_name`` for multi-part / segmented jobs (e.g. ``segment-0``)
 * @returns Highlighting state and control functions
 */
function textIndexErrorMessage(err: unknown): string {
  if (err instanceof Error) return err.message || 'Failed to load text index';
  return String(err) || 'Failed to load text index';
}

export function usePDFHighlighting(
  jobId: string | null,
  partName?: string | null,
): PDFHighlightingState {
  const [selectedField, setSelectedField] = useState<string | null>(null);
  const [hoveredField, setHoveredField] = useState<string | null>(null);
  const [showAll, setShowAll] = useState(false);

  const partKey = partName?.trim() || '';

  const textIndexQuery = useQuery({
    queryKey: ['jobTextIndex', jobId, partKey] as const,
    queryFn: async (): Promise<TextIndexResponse> => {
      return api.getJobTextIndex(jobId!, partKey || undefined);
    },
    enabled: Boolean(jobId),
    staleTime: Infinity,
    gcTime: 1000 * 60 * 60,
  });

  useEffect(() => {
    if (!jobId) {
      setSelectedField(null);
      setHoveredField(null);
    }
  }, [jobId]);

  useEffect(() => {
    if (textIndexQuery.isError) {
      console.error('Failed to fetch text index:', textIndexQuery.error);
    }
  }, [textIndexQuery.isError, textIndexQuery.error]);

  const fieldIndex = useMemo((): Record<string, TextMatch[]> => {
    if (!jobId || !textIndexQuery.data) return {};
    const res = textIndexQuery.data;
    return res.success ? res.fields : {};
  }, [jobId, textIndexQuery.data]);

  const regionIndex = useMemo((): Record<string, RegionMatch[]> => {
    if (!jobId || !textIndexQuery.data) return {};
    const res = textIndexQuery.data;
    return res.success ? (res.region_fields || {}) : {};
  }, [jobId, textIndexQuery.data]);

  const isLoading = Boolean(jobId) && textIndexQuery.isPending;
  const error =
    jobId && textIndexQuery.isError ? textIndexErrorMessage(textIndexQuery.error) : null;

  // Get the currently active field (selected takes priority over hovered)
  const activeField = selectedField || hoveredField;

  /** Keys that have either text positions or region polygons (sorted for stable colors). */
  const indexedFieldKeys = useMemo(() => {
    const keys = new Set([
      ...Object.keys(fieldIndex),
      ...Object.keys(regionIndex),
    ]);
    return Array.from(keys).sort();
  }, [fieldIndex, regionIndex]);

  // Get highlights for the current active field (text-layer matches only)
  const activeHighlights = useMemo(() => {
    if (!activeField || !fieldIndex[activeField]) return [];
    return fieldIndex[activeField];
  }, [activeField, fieldIndex]);

  // First page to show for the active field — text match or region match
  const highlightPage = useMemo(() => {
    if (!activeField) return null;
    const text = fieldIndex[activeField];
    if (text?.length) return text[0].page;
    const regions = regionIndex[activeField];
    if (regions?.length) return regions[0].page;
    return null;
  }, [activeField, fieldIndex, regionIndex]);

  // Select a field (click behavior)
  const selectField = useCallback((field: string | null) => {
    setSelectedField(current => current === field ? null : field);
  }, []);

  // Hover a field
  const hoverField = useCallback((field: string | null) => {
    setHoveredField(field);
  }, []);

  // Toggle show all highlights
  const toggleShowAll = useCallback(() => {
    setShowAll(prev => !prev);
  }, []);

  // Check if a field has highlights available (text index and/or region polygons)
  const hasHighlights = useCallback((field: string) => {
    return (
      (fieldIndex[field]?.length ?? 0) > 0 ||
      (regionIndex[field]?.length ?? 0) > 0
    );
  }, [fieldIndex, regionIndex]);

  // Get a consistent color index for a field
  const getFieldColorIndex = useCallback((field: string): number => {
    const index = indexedFieldKeys.indexOf(field);
    return index === -1 ? 0 : index % HIGHLIGHT_COLORS.length;
  }, [indexedFieldKeys]);

  // Get a consistent color for a field based on its index
  const getFieldColor = useCallback((field: string) => {
    return HIGHLIGHT_COLORS[getFieldColorIndex(field)];
  }, [getFieldColorIndex]);

  // Get a consistent border color for a field based on its index
  const getFieldBorderColor = useCallback((field: string) => {
    return HIGHLIGHT_BORDER_COLORS[getFieldColorIndex(field)];
  }, [getFieldColorIndex]);

  /**
   * Build highlight items for a single field.
   * Prefers polygon-based region matches when available;
   * falls back to text-layer matching otherwise.
   */
  const buildFieldHighlights = useCallback(
    (field: string, isFieldSelected: boolean): HighlightItem[] => {
      const color = getFieldColor(field);
      const borderColor = getFieldBorderColor(field);
      const regions = regionIndex[field];

      // Polygon path: one highlight per region match
      if (regions && regions.length > 0) {
        return regions.map(r => ({
          text: r.value,
          color,
          borderColor,
          isSelected: isFieldSelected,
          polygon: r.polygon,
          page: r.page,
        }));
      }

      // Text-layer fallback: unique values only
      const matches = fieldIndex[field];
      if (!matches || matches.length === 0) return [];
      const uniqueValues = Array.from(new Set(matches.map(m => m.value)));
      return uniqueValues.map(value => ({
        text: value,
        color,
        borderColor,
        isSelected: isFieldSelected,
      }));
    },
    [fieldIndex, regionIndex, getFieldColor, getFieldBorderColor],
  );

  // Build highlights array for the PDFViewer component
  const getHighlightsForPDF = useCallback((): HighlightItem[] => {
    if (showAll) {
      const allHighlights: HighlightItem[] = [];
      indexedFieldKeys.forEach((field) => {
        const isFieldSelected = field === selectedField || field === activeField;
        allHighlights.push(...buildFieldHighlights(field, isFieldSelected));
      });
      return allHighlights;
    }

    if (!activeField) return [];
    const hasText = (fieldIndex[activeField]?.length ?? 0) > 0;
    const hasRegions = (regionIndex[activeField]?.length ?? 0) > 0;
    if (!hasText && !hasRegions) return [];
    return buildFieldHighlights(activeField, activeField === selectedField);
  }, [
    showAll,
    activeField,
    selectedField,
    indexedFieldKeys,
    fieldIndex,
    regionIndex,
    buildFieldHighlights,
  ]);

  return {
    fieldIndex,
    regionIndex,
    indexedFieldKeys,
    selectedField,
    hoveredField,
    activeHighlights,
    highlightPage,
    isLoading,
    error,
    showAll,
    selectField,
    hoverField,
    toggleShowAll,
    hasHighlights,
    getHighlightsForPDF,
    getFieldColor,
    fieldCount: indexedFieldKeys.length,
  };
}
