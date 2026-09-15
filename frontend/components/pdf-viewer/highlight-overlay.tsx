"use client";

/**
 * PDF Highlight Overlay Component.
 *
 * Renders highlight rectangles positioned over the PDF canvas
 * based on text search results from react-pdf's text layer.
 */

import { useEffect, useState, useCallback, useRef } from "react";

export interface HighlightConfig {
  text: string;
  color: string;
  borderColor?: string;
  isSelected: boolean;
  polygon?: number[][];  // Normalized 0-1 coords — skip text search when present
  /** 1-based PDF page; when set with polygon, parent should only pass highlights for the visible page */
  page?: number;
}

export interface HighlightBox {
  x: number;
  y: number;
  width: number;
  height: number;
  color: string;
  borderColor: string;
  isSelected: boolean;
}

/**
 * Color palette for field highlights - transparent fill, colored border only.
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

interface HighlightOverlayProps {
  pageElement: HTMLElement | null;
  highlights: HighlightConfig[];
  scale: number;
  /** Callback when highlight boxes are calculated - provides first box position for scrolling */
  onHighlightBoxesReady?: (boxes: HighlightBox[]) => void;
}

/**
 * Check if a string represents a number (integer or decimal).
 */
function isNumericString(str: string): boolean {
  const cleaned = str.replace(/[,\s]/g, '');
  return /^-?\d+\.?\d*$/.test(cleaned);
}

/**
 * Generate variations of a number string for matching.
 * Handles: 35400 <-> 35,400 <-> 35,400.00 <-> 35400.00
 */
function getNumberVariations(value: string): string[] {
  const cleaned = value.replace(/[,\s]/g, '');
  if (!isNumericString(cleaned)) return [value];

  const num = parseFloat(cleaned);
  if (isNaN(num)) return [value];

  const variations: string[] = [];

  // Integer (no decimals): 35400
  const intPart = Math.floor(Math.abs(num));
  const isNegative = num < 0;
  const prefix = isNegative ? '-' : '';

  variations.push(prefix + intPart.toString());

  // With comma separators: 35,400
  variations.push(prefix + intPart.toLocaleString('en-US'));

  // With .00 decimals: 35400.00
  variations.push(prefix + num.toFixed(2));

  // With comma separators and decimals: 35,400.00
  variations.push(prefix + num.toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));

  // If original has decimals, also include single decimal version
  if (cleaned.includes('.')) {
    const decimalPart = cleaned.split('.')[1] || '';
    if (decimalPart.length === 1) {
      variations.push(prefix + num.toFixed(1));
      variations.push(prefix + num.toLocaleString('en-US', { minimumFractionDigits: 1, maximumFractionDigits: 1 }));
    }
  }

  // Remove duplicates
  return Array.from(new Set(variations));
}

/**
 * Generate search patterns for a text, including number variations.
 */
function getSearchPatterns(searchText: string): string[] {
  const trimmed = searchText.trim();
  if (!trimmed) return [];

  // If it looks like a number, generate variations
  if (isNumericString(trimmed)) {
    return getNumberVariations(trimmed);
  }

  // For non-numbers, just return the original
  return [trimmed];
}

/**
 * Finds text spans in the text layer that match the search text
 * and returns their bounding boxes relative to the text layer.
 *
 * Includes intelligent matching for numbers (with/without commas, decimals).
 */
function findTextBounds(
  pageElement: HTMLElement,
  searchText: string,
  scale: number
): Array<{ x: number; y: number; width: number; height: number }> {
  const results: Array<{ x: number; y: number; width: number; height: number }> = [];

  if (!searchText || searchText.length < 2) return results;

  // Find the text layer within the page
  const textLayer = pageElement.querySelector('.react-pdf__Page__textContent') as HTMLElement;
  if (!textLayer) return results;

  // Get all text spans (react-pdf creates spans for each text item)
  const spans = textLayer.querySelectorAll('span');
  if (spans.length === 0) return results;

  // Get the text layer's bounding rect as reference point
  const layerRect = textLayer.getBoundingClientRect();

  // Generate search patterns (includes number variations)
  const searchPatterns = getSearchPatterns(searchText);
  if (searchPatterns.length === 0) return results;

  // Track which spans we've already matched to avoid duplicates
  const matchedSpans = new Set<Element>();

  // First pass: try to find exact text in single spans
  for (const pattern of searchPatterns) {
    const patternLower = pattern.toLowerCase();

    spans.forEach((span) => {
      if (matchedSpans.has(span)) return;

      const spanText = span.textContent?.toLowerCase() || '';
      if (spanText.includes(patternLower)) {
        matchedSpans.add(span);
        const spanRect = span.getBoundingClientRect();
        results.push({
          x: (spanRect.left - layerRect.left) / scale,
          y: (spanRect.top - layerRect.top) / scale,
          width: spanRect.width / scale,
          height: spanRect.height / scale,
        });
      }
    });

    // If we found matches, stop looking
    if (results.length > 0) break;
  }

  // If no matches found, try matching across multiple adjacent spans
  if (results.length === 0) {
    // Build concatenated text with span references
    const spanData: Array<{ span: Element; text: string; startIndex: number }> = [];
    let fullText = '';

    spans.forEach((span) => {
      const text = span.textContent || '';
      spanData.push({
        span,
        text,
        startIndex: fullText.length,
      });
      fullText += text;
    });

    const fullTextLower = fullText.toLowerCase();

    for (const pattern of searchPatterns) {
      if (pattern.length < 3) continue;
      const patternLower = pattern.toLowerCase();
      let searchIndex = fullTextLower.indexOf(patternLower);

      while (searchIndex !== -1) {
        const searchEnd = searchIndex + patternLower.length;

        // Find all spans that overlap with this match
        const matchingSpans = spanData.filter((sd) => {
          const spanEnd = sd.startIndex + sd.text.length;
          return (
            (sd.startIndex >= searchIndex && sd.startIndex < searchEnd) ||
            (spanEnd > searchIndex && spanEnd <= searchEnd) ||
            (sd.startIndex <= searchIndex && spanEnd >= searchEnd)
          );
        });

        if (matchingSpans.length > 0) {
          // Calculate bounding box that covers all matching spans
          let minX = Infinity, minY = Infinity, maxX = -Infinity, maxY = -Infinity;

          matchingSpans.forEach((sd) => {
            const spanRect = sd.span.getBoundingClientRect();
            const x = (spanRect.left - layerRect.left) / scale;
            const y = (spanRect.top - layerRect.top) / scale;
            const right = x + spanRect.width / scale;
            const bottom = y + spanRect.height / scale;

            minX = Math.min(minX, x);
            minY = Math.min(minY, y);
            maxX = Math.max(maxX, right);
            maxY = Math.max(maxY, bottom);
          });

          results.push({
            x: minX,
            y: minY,
            width: maxX - minX,
            height: maxY - minY,
          });
        }

        searchIndex = fullTextLower.indexOf(patternLower, searchIndex + 1);
      }

      // If we found matches with this pattern, stop
      if (results.length > 0) break;
    }
  }

  return results;
}

/**
 * Highlight overlay component that renders highlight rectangles
 * over the PDF canvas based on text search.
 */
export function HighlightOverlay({ pageElement, highlights, scale, onHighlightBoxesReady }: HighlightOverlayProps) {
  const [boxes, setBoxes] = useState<HighlightBox[]>([]);
  const [layerStyle, setLayerStyle] = useState<{ top: number; left: number; width: number; height: number } | null>(null);
  const observerRef = useRef<MutationObserver | null>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  const updateHighlights = useCallback(() => {
    if (!pageElement || highlights.length === 0) {
      setBoxes([]);
      setLayerStyle(null);
      return;
    }

    // Find the text layer
    const textLayer = pageElement.querySelector('.react-pdf__Page__textContent') as HTMLElement;
    if (!textLayer) {
      setBoxes([]);
      setLayerStyle(null);
      return;
    }

    // Get the page element's bounding rect (the react-pdf__Page element)
    const pageRect = pageElement.getBoundingClientRect();
    const textLayerRect = textLayer.getBoundingClientRect();

    // Calculate text layer position relative to the page element
    // Divide by scale to get coordinates in untransformed space
    const newLayerStyle = {
      top: (textLayerRect.top - pageRect.top) / scale,
      left: (textLayerRect.left - pageRect.left) / scale,
      width: textLayerRect.width / scale,
      height: textLayerRect.height / scale,
    };
    setLayerStyle(newLayerStyle);

    // Rendered page dimensions (in unscaled CSS pixels)
    const pageW = newLayerStyle.width;
    const pageH = newLayerStyle.height;

    const newBoxes: HighlightBox[] = [];

    highlights.forEach((highlight) => {
      const borderColor = highlight.borderColor || highlight.color.replace(/[\d.]+\)$/, '0.9)');

      // Polygon path: coordinates are normalized 0-1, scale to rendered size
      if (highlight.polygon && highlight.polygon.length >= 3) {
        const xs = highlight.polygon.map(p => p[0] * pageW);
        const ys = highlight.polygon.map(p => p[1] * pageH);
        const minX = Math.min(...xs);
        const minY = Math.min(...ys);
        newBoxes.push({
          x: minX,
          y: minY,
          width: Math.max(...xs) - minX,
          height: Math.max(...ys) - minY,
          color: highlight.color,
          borderColor,
          isSelected: highlight.isSelected,
        });
        return;
      }

      // Text-layer fallback
      if (!highlight.text || highlight.text.length < 2) return;
      const bounds = findTextBounds(pageElement, highlight.text, scale);
      bounds.forEach((bound) => {
        newBoxes.push({
          ...bound,
          color: highlight.color,
          borderColor,
          isSelected: highlight.isSelected,
        });
      });
    });

    setBoxes(newBoxes);

    // Notify parent about highlight boxes for scrolling
    if (onHighlightBoxesReady && newBoxes.length > 0) {
      // Add layer offset to box positions for absolute positioning
      const absoluteBoxes = newBoxes.map(box => ({
        ...box,
        x: box.x + newLayerStyle.left,
        y: box.y + newLayerStyle.top,
      }));
      onHighlightBoxesReady(absoluteBoxes);
    }
  }, [pageElement, highlights, scale, onHighlightBoxesReady]);

  // Update highlights when dependencies change
  useEffect(() => {
    // Small delay to ensure text layer is rendered
    if (timeoutRef.current) {
      clearTimeout(timeoutRef.current);
    }

    timeoutRef.current = setTimeout(() => {
      updateHighlights();
    }, 200);

    return () => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
    };
  }, [updateHighlights]);

  // Observe text layer changes
  useEffect(() => {
    if (!pageElement) return;

    const textLayer = pageElement.querySelector('.react-pdf__Page__textContent');
    if (!textLayer) return;

    // Re-calculate when text layer content changes
    observerRef.current = new MutationObserver(() => {
      if (timeoutRef.current) {
        clearTimeout(timeoutRef.current);
      }
      timeoutRef.current = setTimeout(() => {
        updateHighlights();
      }, 200);
    });

    observerRef.current.observe(textLayer, {
      childList: true,
      subtree: true,
    });

    return () => {
      if (observerRef.current) {
        observerRef.current.disconnect();
      }
    };
  }, [pageElement, updateHighlights]);

  if (boxes.length === 0 || !layerStyle) return null;

  return (
    <div
      className="highlight-overlay-container"
      style={{
        position: 'absolute',
        top: `${layerStyle.top}px`,
        left: `${layerStyle.left}px`,
        width: `${layerStyle.width}px`,
        height: `${layerStyle.height}px`,
        pointerEvents: 'none',
        zIndex: 2,
      }}
    >
      {boxes.map((box, index) => {
        // Convert hex to rgba for background
        const hexToRgba = (hex: string, alpha: number) => {
          const r = parseInt(hex.slice(1, 3), 16);
          const g = parseInt(hex.slice(3, 5), 16);
          const b = parseInt(hex.slice(5, 7), 16);
          return `rgba(${r}, ${g}, ${b}, ${alpha})`;
        };

        return (
          <div
            key={index}
            className={box.isSelected ? 'pdf-highlight-box-active' : 'pdf-highlight-box'}
            style={{
              position: 'absolute',
              left: `${box.x - 2}px`,
              top: `${box.y - 2}px`,
              width: `${box.width + 4}px`,
              height: `${box.height + 4}px`,
              border: `2px solid ${box.borderColor}`,
              borderRadius: '3px',
              backgroundColor: box.isSelected ? hexToRgba(box.borderColor, 0.15) : 'transparent',
            }}
          />
        );
      })}
    </div>
  );
}

/**
 * @deprecated Use HighlightOverlay component instead for proper positioning.
 * This function is kept for backwards compatibility but doesn't work reliably.
 */
export function createHighlightRenderer(
  highlights: HighlightConfig[]
): (textItem: { str: string; itemIndex: number }) => string {
  // Filter out empty or too-short highlights
  const validHighlights = highlights.filter(h => h.text && h.text.length >= 2);

  if (validHighlights.length === 0) {
    return ({ str }) => str;
  }

  return function customTextRenderer({ str }: { str: string; itemIndex: number }): string {
    let result = str;

    for (const highlight of validHighlights) {
      try {
        // Escape special regex characters in the search text
        const escapedText = highlight.text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

        // Create case-insensitive regex to find all matches
        const regex = new RegExp(`(${escapedText})`, 'gi');

        // Replace matches with highlighted span
        const highlightClass = highlight.isSelected ? 'pdf-highlight-active' : 'pdf-highlight';
        result = result.replace(regex, (match) => {
          return `<span class="${highlightClass}" style="background-color: ${highlight.color};">${match}</span>`;
        });
      } catch {
        continue;
      }
    }

    return result;
  };
}
