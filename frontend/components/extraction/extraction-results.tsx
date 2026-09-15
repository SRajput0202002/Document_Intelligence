"use client";

import { useState, useEffect, useMemo, useCallback } from "react";
import {
  FileText,
  XCircle,
  AlertCircle,
  ChevronLeft,
  ChevronUp,
  ChevronRight,
  ChevronDown,
  ChevronsUpDown,
  Focus,
  Info,
  Table2,
  FileCode,
  Check,
  Clock,
  Zap,
  FileType,
  Brain,
  CalendarDays,
  Gauge,
  ScanText,
  Cpu,
  BarChart2,
  FileJson,
  File,
  Code,
  Loader2,
  Workflow,
  Pencil,
  SquareDashed,
  Save,
  X,
} from "lucide-react";
import { CopyIcon } from "@/components/ui/copy";
import { DownloadIcon } from "@/components/ui/download";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { FileTextIcon } from "@/components/ui/file-text";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { toast } from "@/components/ui/toast";
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui/popover";
import {
  HoverCard,
  HoverCardContent,
  HoverCardTrigger,
} from "@/components/ui/hover-card";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { cn, formatDuration } from "@/lib/utils";
import { PDFViewer } from "@/components/pdf-viewer";
import { ExcelViewer } from "@/components/extraction/excel-viewer";
import {
  api,
  type Job,
  type JobPart,
  type OCRTextResult,
  type DocumentSegmentResponse,
  type FieldCorrectionUpdate,
} from "@/lib/api";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { usePDFHighlighting, HIGHLIGHT_COLORS, HIGHLIGHT_BORDER_COLORS } from "@/hooks/use-pdf-highlighting";
import { SaveAsWorkflowModal } from "@/components/workflows/save-as-workflow-modal";
import { useSetting } from "@/hooks/use-settings";
import type { DrawBoxResult } from "@/components/pdf-viewer/draw-overlay";

/** Readable label for a doc_type / segmentation slug (e.g. payment_certificate → Payment Certificate) */
function formatDocTypeLabel(docType: string): string {
  return docType
    .split(/[-_\s]+/)
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ");
}

/** Ensure segment list titles are unique without mutating `used`. */
function makeUniqueSegmentTitle(baseName: string, used: Set<string>): string {
  if (!used.has(baseName)) return baseName;
  let counter = 2;
  while (used.has(`${baseName} (${counter})`)) {
    counter++;
  }
  return `${baseName} (${counter})`;
}

/** Parse ``segment-N`` job part names to segmentation index. */
function parseSegmentIndex(partName: string): number | null {
  const match = /^segment-(\d+)$/.exec(partName);
  return match ? parseInt(match[1], 10) : null;
}

/** Stable page order for multi-segment jobs (matches backend ``get_job_parts``). */
function sortJobPartsByPage<T extends { part_name: string; page_range?: number[] }>(
  parts: T[]
): T[] {
  return [...parts].sort((a, b) => {
    const pageA = a.page_range?.[0] ?? 0;
    const pageB = b.page_range?.[0] ?? 0;
    if (pageA !== pageB) return pageA - pageB;
    return a.part_name.localeCompare(b.part_name);
  });
}

// =============================================================================
// Shared Results View Component (used by both main page and jobs/[id] page)
// =============================================================================

/** True for LLM ``{ value, ref_id? }`` field objects (not arbitrary nested structs). */
function isValueRefWrapper(obj: unknown): obj is { value?: unknown; ref_id?: unknown } {
  if (obj === null || typeof obj !== "object" || Array.isArray(obj)) return false;
  const o = obj as Record<string, unknown>;
  const keys = Object.keys(o);
  if (!keys.every((k) => k === "value" || k === "ref_id")) return false;
  if (!("value" in o)) return false;
  const v = o.value;
  if (v !== null && v !== undefined && typeof v === "object") return false;
  return true;
}

/**
 * Text index keys are logical paths (e.g. ``invoice_number``), not ``invoice_number.value``.
 */
function highlightKeyForPath(fieldPath: string): string {
  if (fieldPath.endsWith(".value") || fieldPath.endsWith(".ref_id")) {
    return fieldPath.replace(/\.(value|ref_id)$/, "");
  }
  return fieldPath;
}

type PathToken = string | number;

function parseFieldPathTokens(path: string): PathToken[] {
  const raw = highlightKeyForPath(path.trim());
  const tokens: PathToken[] = [];
  const re = /[^.\[\]]+|\[\d+\]/g;
  let m: RegExpExecArray | null;
  while ((m = re.exec(raw)) !== null) {
    const chunk = m[0];
    if (chunk.startsWith("[")) tokens.push(parseInt(chunk.slice(1, -1), 10));
    else tokens.push(chunk);
  }
  return tokens;
}

function getAtFieldPath(data: unknown, path: string): unknown {
  let cur: unknown = data;
  for (const tok of parseFieldPathTokens(path)) {
    if (typeof tok === "number") {
      if (!Array.isArray(cur) || tok < 0 || tok >= cur.length) return undefined;
      cur = cur[tok];
    } else {
      if (!cur || typeof cur !== "object" || Array.isArray(cur)) return undefined;
      cur = (cur as Record<string, unknown>)[tok];
    }
  }
  return cur;
}

function pathExistsInData(data: unknown, path: string): boolean {
  return getAtFieldPath(data, path) !== undefined;
}

function setAtFieldPath(data: Record<string, unknown>, path: string, value: unknown): void {
  const tokens = parseFieldPathTokens(path);
  let cur: unknown = data;
  for (let i = 0; i < tokens.length - 1; i++) {
    const tok = tokens[i];
    if (typeof tok === "number") {
      if (!Array.isArray(cur)) return;
      cur = cur[tok];
    } else {
      if (!cur || typeof cur !== "object" || Array.isArray(cur)) return;
      cur = (cur as Record<string, unknown>)[tok];
    }
  }
  const last = tokens[tokens.length - 1];
  if (typeof last === "number") {
    if (!Array.isArray(cur) || last < 0 || last >= cur.length) return;
    const existing = cur[last];
    if (isValueRefWrapper(existing)) {
      (existing as { value: unknown }).value = value;
    } else {
      cur[last] = value;
    }
    return;
  }
  if (!cur || typeof cur !== "object" || Array.isArray(cur)) return;
  const obj = cur as Record<string, unknown>;
  const existing = obj[last];
  if (isValueRefWrapper(existing)) {
    (existing as { value: unknown }).value = value;
  } else {
    obj[last] = value;
  }
}

/** Coerce edited string back toward the original leaf type. */
function coerceEditedValue(raw: string, original: unknown): unknown {
  const leaf = isValueRefWrapper(original)
    ? (original as { value: unknown }).value
    : original;
  if (typeof leaf === "number") {
    const n = Number(raw.replace(/,/g, ""));
    return Number.isFinite(n) ? n : raw;
  }
  if (typeof leaf === "boolean") {
    const lower = raw.trim().toLowerCase();
    if (lower === "true") return true;
    if (lower === "false") return false;
    return raw;
  }
  if (leaf === null) {
    if (raw.trim() === "" || raw.trim().toLowerCase() === "null") return null;
    return raw;
  }
  return raw;
}

function findPartNameForFieldPath(parts: JobPart[], path: string): string | null {
  const key = highlightKeyForPath(path);
  for (const part of parts) {
    if (part.extracted_data && pathExistsInData(part.extracted_data, key)) {
      return part.part_name;
    }
  }
  return parts.find((p) => p.status === "completed")?.part_name ?? parts[0]?.part_name ?? null;
}

function deepCloneParts(parts: JobPart[]): JobPart[] {
  return parts.map((p) => ({
    ...p,
    extracted_data: p.extracted_data
      ? (JSON.parse(JSON.stringify(p.extracted_data)) as Record<string, unknown>)
      : undefined,
  }));
}

function valuesEqualForEdit(a: unknown, b: unknown): boolean {
  const va = isValueRefWrapper(a) ? (a as { value: unknown }).value : a;
  const vb = isValueRefWrapper(b) ? (b as { value: unknown }).value : b;
  return JSON.stringify(va) === JSON.stringify(vb);
}

/** Collect dotted paths whose leaf values differ between original and draft part data. */
function collectValueDiffs(
  original: Record<string, unknown> | undefined,
  draft: Record<string, unknown> | undefined,
  prefix = "",
): Array<{ path: string; value: unknown }> {
  if (!draft) return [];
  if (!original) {
    // Entire tree is new — flatten leaves
    const out: Array<{ path: string; value: unknown }> = [];
    const walk = (node: unknown, p: string) => {
      if (isValueRefWrapper(node)) {
        out.push({ path: p, value: (node as { value: unknown }).value });
        return;
      }
      if (Array.isArray(node)) {
        node.forEach((item, i) => walk(item, `${p}[${i}]`));
        return;
      }
      if (node && typeof node === "object") {
        for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
          if (k === "ref_id") continue;
          walk(v, p ? `${p}.${k}` : k);
        }
        return;
      }
      out.push({ path: p, value: node });
    };
    walk(draft, prefix);
    return out.filter((x) => x.path);
  }

  const out: Array<{ path: string; value: unknown }> = [];
  const walk = (origNode: unknown, draftNode: unknown, p: string) => {
    if (isValueRefWrapper(draftNode) || isValueRefWrapper(origNode) ||
      (draftNode !== null && typeof draftNode !== "object") ||
      (origNode !== null && typeof origNode !== "object" && origNode !== undefined)) {
      if (!valuesEqualForEdit(origNode, draftNode)) {
        const value = isValueRefWrapper(draftNode)
          ? (draftNode as { value: unknown }).value
          : draftNode;
        out.push({ path: p, value });
      }
      return;
    }
    if (Array.isArray(draftNode)) {
      const origArr = Array.isArray(origNode) ? origNode : [];
      draftNode.forEach((item, i) => walk(origArr[i], item, `${p}[${i}]`));
      return;
    }
    if (draftNode && typeof draftNode === "object") {
      const origObj =
        origNode && typeof origNode === "object" && !Array.isArray(origNode)
          ? (origNode as Record<string, unknown>)
          : {};
      for (const [k, v] of Object.entries(draftNode as Record<string, unknown>)) {
        if (k === "ref_id") continue;
        walk(origObj[k], v, p ? `${p}.${k}` : k);
      }
    }
  };
  walk(original, draft, prefix);
  return out.filter((x) => x.path);
}

/** Omit internal provenance keys from extracted-data UI (rows / table columns). */
function objectEntriesForDisplay(o: Record<string, unknown>): [string, unknown][] {
  return Object.entries(o).filter(([k]) => k !== "ref_id" && k !== "polygon" && k !== "image_base64");
}

function objectKeysForDisplayRow(row: Record<string, unknown>): string[] {
  return Object.keys(row).filter((k) => k !== "ref_id" && k !== "polygon" && k !== "image_base64");
}

function isBarcodeHitList(value: unknown): value is Array<Record<string, unknown>> {
  if (!Array.isArray(value) || value.length === 0) return false;
  return value.every(
    (item) =>
      item &&
      typeof item === "object" &&
      !Array.isArray(item) &&
      "kind" in item &&
      "value" in item,
  );
}

function isSignatureHit(value: unknown): value is Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const o = value as Record<string, unknown>;
  return "present" in o && ("signature_type" in o || "image_base64" in o);
}

function isDataImageString(value: unknown): boolean {
  return typeof value === "string" && value.startsWith("data:image/");
}

// --- Export (PDF / CSV / Markdown): avoid JSON blobs and [object Object] for line items ---

function formatFieldNameForExport(key: string): string {
  return key
    .replace(/_/g, " ")
    .replace(/([A-Z])/g, " $1")
    .split(" ")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
    .join(" ")
    .trim();
}

function unwrapArrayItemsForExport(items: unknown[]): { unwrapped: unknown[]; wrapperKey: string | null } {
  if (items.length === 0 || typeof items[0] !== "object" || items[0] === null) {
    return { unwrapped: items, wrapperKey: null };
  }
  const firstItem = items[0] as Record<string, unknown>;
  const keys = Object.keys(firstItem);
  if (
    keys.length === 1 &&
    typeof firstItem[keys[0]] === "object" &&
    firstItem[keys[0]] !== null &&
    !Array.isArray(firstItem[keys[0]])
  ) {
    const wrapperKey = keys[0];
    const unwrapped = items.map((item) => (item as Record<string, unknown>)[wrapperKey]);
    return { unwrapped, wrapperKey: wrapperKey };
  }
  return { unwrapped: items, wrapperKey: null };
}

function isArrayOfRecordLike(arr: unknown[]): boolean {
  return arr.every((x) => x !== null && typeof x === "object" && !Array.isArray(x));
}

/** Readable text for exports: unwraps ``{ value, ref_id }``, nested objects, and table-style arrays. */
function formatExtractedValueForExportPlain(value: unknown): string {
  if (value === null || value === undefined) return "";
  if (isValueRefWrapper(value)) {
    return formatExtractedValueForExportPlain((value as { value: unknown }).value);
  }
  if (typeof value === "string" || typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    if (value.length === 0) return "";
    if (isArrayOfRecordLike(value)) {
      const { unwrapped } = unwrapArrayItemsForExport(value);
      const rows = unwrapped as Record<string, unknown>[];
      const colKeys =
        rows.length > 0 && rows[0] && typeof rows[0] === "object"
          ? objectKeysForDisplayRow(rows[0] as Record<string, unknown>)
          : [];
      return rows
        .map((row, idx) => {
          const cells = colKeys.map((k) => {
            const cell = (row as Record<string, unknown>)[k];
            return `${formatFieldNameForExport(k)}: ${formatExtractedValueForExportPlain(cell)}`;
          });
          return `${idx + 1}. ${cells.join("; ")}`;
        })
        .join("\n");
    }
    return value.map((v) => formatExtractedValueForExportPlain(v)).join(", ");
  }
  if (typeof value === "object") {
    return objectEntriesForDisplay(value as Record<string, unknown>)
      .map(([k, v]) => `${formatFieldNameForExport(k)}: ${formatExtractedValueForExportPlain(v)}`)
      .join("; ");
  }
  return String(value);
}

function isLineItemsArrayForExport(value: unknown): value is unknown[] {
  return Array.isArray(value) && value.length > 0 && isArrayOfRecordLike(value);
}

function formatLineItemsAsMarkdownTable(rows: Record<string, unknown>[], columnKeys: string[]): string {
  const escCell = (s: string) => s.replace(/\|/g, "\\|").replace(/\r?\n/g, " ");
  const header = `| ${columnKeys.map((c) => formatFieldNameForExport(c)).join(" | ")} |`;
  const sep = `| ${columnKeys.map(() => "---").join(" | ")} |`;
  const body = rows.map((row) => {
    const cells = columnKeys.map((k) =>
      escCell(formatExtractedValueForExportPlain((row as Record<string, unknown>)[k]))
    );
    return `| ${cells.join(" | ")} |`;
  });
  return [header, sep, ...body].join("\n");
}

function escapeCsvField(text: string): string {
  return `"${text.replace(/"/g, '""')}"`;
}

/** Flat list of label + raw value for PDF/CSV/Markdown (expands multi-segment buckets). */
function getExportLabelValuePairs(
  data: Record<string, unknown>,
  isMultiSegmentJob: boolean,
  segmentTitles: Map<string, string>
): { label: string; value: unknown }[] {
  const pairs: { label: string; value: unknown }[] = [];
  for (const [key, value] of Object.entries(data)) {
    if (
      isMultiSegmentJob &&
      key.startsWith("__segment_") &&
      value &&
      typeof value === "object" &&
      !Array.isArray(value)
    ) {
      const prefix = segmentTitles.get(key) ?? formatFieldNameForExport(key);
      for (const [innerKey, innerVal] of Object.entries(value as Record<string, unknown>)) {
        pairs.push({
          label: `${prefix} — ${formatFieldNameForExport(innerKey)}`,
          value: innerVal,
        });
      }
    } else {
      pairs.push({ label: formatFieldNameForExport(key), value });
    }
  }
  return pairs;
}

interface ExtractionResultsViewProps {
  job: Job;
  providers?: {
    ocr: Array<{ name: string; display_name: string }>;
    llm: Array<{ name: string; display_name: string }>;
  } | null;
  documentFile?: File | string | null;
  onBack?: () => void;
  backButtonText?: string;
  // For main extraction page - hide outer header since page has its own
  hideHeader?: boolean;
  // Hide save as workflow button (when coming from workflow test)
  hideSaveAsWorkflow?: boolean;
}

export function ExtractionResultsView({
  job,
  providers,
  documentFile,
  onBack,
  backButtonText = "Back",
  hideHeader = false,
  hideSaveAsWorkflow = false,
}: ExtractionResultsViewProps) {
  const queryClient = useQueryClient();
  const compactView = useSetting("compact_view") ?? false;
  const showConfidenceScores = useSetting("show_confidence_scores") ?? true;
  const autoExpandResults = useSetting("auto_expand_results") ?? true;
  const [infoOpen, setInfoOpen] = useState(false);
  const [copied, setCopied] = useState(false);
  const [activeTab, setActiveTab] = useState<"extracted" | "ocr">("extracted");
  const [ocrText, setOcrText] = useState<string | null>(null);
  const [ocrLoading, setOcrLoading] = useState(false);
  const [ocrError, setOcrError] = useState<string | null>(null);
  const [collapsedSections, setCollapsedSections] = useState<Set<string>>(new Set());
  const [workflowModalOpen, setWorkflowModalOpen] = useState(false);
  const [currentPage, setCurrentPage] = useState(1);
  /** Multi-part: pin /text-index to the segment whose field is hovered (cleared on mouse leave). */
  const [hoverHighlightPartName, setHoverHighlightPartName] = useState<string | null>(null);
  /** Multi-part: pin /text-index to the segment whose field is selected (cleared when selection clears). */
  const [selectedHighlightPartName, setSelectedHighlightPartName] = useState<string | null>(null);

  // Human correction: edit mode + pending geometry drafts
  const [editMode, setEditMode] = useState(false);
  const [drawMode, setDrawMode] = useState(false);
  const [savingEdits, setSavingEdits] = useState(false);
  const [draftParts, setDraftParts] = useState<JobPart[] | null>(null);
  const [pendingGeometry, setPendingGeometry] = useState<
    Record<string, { page: number; polygon: number[][]; partName: string }>
  >({});

  // Check if this is a multi-segment job
  const isMultiSegmentJob = (job.parts || []).some(p => p.part_name.startsWith("segment-"));

  const sortedJobParts = useMemo(
    () => sortJobPartsByPage((draftParts ?? job.parts) || []),
    [draftParts, job.parts]
  );

  // Fetch segments data for multi-segment jobs (to get page ranges)
  const { data: segmentsData } = useQuery({
    queryKey: ["jobSegments", job.id],
    queryFn: () => api.getJobSegments(job.id),
    enabled: isMultiSegmentJob && !!job.id,
    staleTime: Infinity,
  });

  // Create a map of segment index to page range for quick lookup
  const segmentPageRanges = useMemo(() => {
    const map = new Map<number, { pageStart: number; pageEnd: number }>();
    if (segmentsData) {
      segmentsData.forEach((seg) => {
        map.set(seg.index, { pageStart: seg.page_start, pageEnd: seg.page_end });
      });
    }
    return map;
  }, [segmentsData]);

  /** Multi-part jobs: which ``job_parts.part_name`` to request for /text-index (matches PDF page). */
  const hasMultipleDataParts = useMemo(
    () => (job.parts || []).filter((p) => p.extracted_data).length > 1,
    [job.parts],
  );

  /** Multi-part fallback: part for the PDF page currently in view (segment page ranges). */
  const pageDerivedPartName = useMemo(() => {
    if (!hasMultipleDataParts || !sortedJobParts.length) return null;
    for (const part of sortedJobParts) {
      const segIdx = parseSegmentIndex(part.part_name);
      const pr = segIdx !== null ? segmentPageRanges.get(segIdx) : undefined;
      if (!pr) continue;
      if (currentPage >= pr.pageStart && currentPage <= pr.pageEnd) {
        return part.part_name ?? null;
      }
    }
    const firstWithData = sortedJobParts.find((p) => p.extracted_data);
    return firstWithData?.part_name ?? null;
  }, [hasMultipleDataParts, sortedJobParts, segmentPageRanges, currentPage]);

  const effectiveTextIndexPartName = useMemo(() => {
    if (!hasMultipleDataParts) return null;
    return hoverHighlightPartName ?? selectedHighlightPartName ?? pageDerivedPartName;
  }, [
    hasMultipleDataParts,
    hoverHighlightPartName,
    selectedHighlightPartName,
    pageDerivedPartName,
  ]);

  useEffect(() => {
    setHoverHighlightPartName(null);
    setSelectedHighlightPartName(null);
    setEditMode(false);
    setDrawMode(false);
    setDraftParts(null);
    setPendingGeometry({});
  }, [job.id]);

  // Navigate to a specific page
  const handlePageClick = useCallback((page: number) => {
    setCurrentPage(page);
  }, []);

  // Toggle section collapse state
  const toggleSection = useCallback((key: string) => {
    setCollapsedSections(prev => {
      const next = new Set(prev);
      if (next.has(key)) {
        next.delete(key);
      } else {
        next.add(key);
      }
      return next;
    });
  }, []);


  // PDF highlighting state
  const {
    indexedFieldKeys,
    selectedField,
    hoveredField,
    highlightPage,
    selectField,
    hoverField,
    showAll: showAllHighlights,
    toggleShowAll,
    hasHighlights: hasDirectHighlights,
    getHighlightsForPDF,
    getFieldColor: getDirectFieldColor,
  } = usePDFHighlighting(
    job.status?.toLowerCase() === "completed" ? job.id : null,
    effectiveTextIndexPartName,
  );

  useEffect(() => {
    if (!selectedField) {
      setSelectedHighlightPartName(null);
    }
  }, [selectedField]);

  // Sync currentPage when highlightPage changes (from field clicks)
  useEffect(() => {
    if (highlightPage && highlightPage !== currentPage) {
      setCurrentPage(highlightPage);
    }
  }, [highlightPage, currentPage]);

  // Check if a field OR any of its nested children have highlights
  const hasHighlights = useCallback((key: string): boolean => {
    // Direct match
    if (hasDirectHighlights(key)) return true;
    // Check for nested matches (e.g., key="buyer" matches "buyer.name", "buyer.address")
    const nestedPrefix = key + ".";
    const arrayPrefix = key + "[";
    return indexedFieldKeys.some(
      k => k.startsWith(nestedPrefix) || k.startsWith(arrayPrefix)
    );
  }, [hasDirectHighlights, indexedFieldKeys]);

  // Get color for a field (checks nested fields too)
  const getFieldColor = useCallback((key: string): string => {
    if (hasDirectHighlights(key)) return getDirectFieldColor(key);
    // Find first nested field with highlights
    const nestedPrefix = key + ".";
    const arrayPrefix = key + "[";
    const nestedKey = indexedFieldKeys.find(
      k => k.startsWith(nestedPrefix) || k.startsWith(arrayPrefix)
    );
    return nestedKey ? getDirectFieldColor(nestedKey) : HIGHLIGHT_COLORS[0];
  }, [hasDirectHighlights, getDirectFieldColor, indexedFieldKeys]);

  // Get border/indicator color for a field based on field index
  const getFieldBorderColor = useCallback((key: string): string => {
    const fields = indexedFieldKeys;
    // Check for exact match first
    let index = fields.indexOf(key);
    // If not found, check for parent field (for nested fields like "buyer.name" -> "buyer")
    if (index === -1) {
      const parentKey = key.split('.')[0].split('[')[0];
      index = fields.findIndex(f => f === parentKey || f.startsWith(parentKey + '.') || f.startsWith(parentKey + '['));
    }
    return HIGHLIGHT_BORDER_COLORS[index >= 0 ? index % HIGHLIGHT_BORDER_COLORS.length : 0];
  }, [indexedFieldKeys]);

  // Select a field - also select all nested fields for highlighting
  const handleSelectField = useCallback(
    (key: string, opts?: { segmentPartName?: string | null }) => {
      if (hasMultipleDataParts) {
        if (opts?.segmentPartName) {
          setSelectedHighlightPartName(opts.segmentPartName);
        } else {
          setSelectedHighlightPartName(null);
        }
      }
      if (hasDirectHighlights(key)) {
        selectField(key);
        return;
      }
      const nestedPrefix = key + ".";
      const arrayPrefix = key + "[";
      const nestedKey = indexedFieldKeys.find(
        (k) => k.startsWith(nestedPrefix) || k.startsWith(arrayPrefix),
      );
      if (nestedKey) {
        selectField(nestedKey);
      }
    },
    [hasMultipleDataParts, hasDirectHighlights, selectField, indexedFieldKeys],
  );

  // Hover a field - same logic as select
  const handleHoverField = useCallback(
    (key: string | null, opts?: { segmentPartName?: string | null }) => {
      if (!key) {
        setHoverHighlightPartName(null);
        hoverField(null);
        return;
      }
      if (hasMultipleDataParts) {
        if (opts?.segmentPartName) {
          setHoverHighlightPartName(opts.segmentPartName);
        } else {
          setHoverHighlightPartName(null);
        }
      }
      if (hasDirectHighlights(key)) {
        hoverField(key);
        return;
      }
      const nestedPrefix = key + ".";
      const arrayPrefix = key + "[";
      const nestedKey = indexedFieldKeys.find(
        (k) => k.startsWith(nestedPrefix) || k.startsWith(arrayPrefix),
      );
      if (nestedKey) {
        hoverField(nestedKey);
      }
    },
    [hasMultipleDataParts, hasDirectHighlights, hoverField, indexedFieldKeys],
  );

  // Build highlights for PDFViewer
  const pdfHighlights = useMemo(() => {
    const base = getHighlightsForPDF();
    // Overlay pending geometry drafts (preview before save)
    const pending = Object.entries(pendingGeometry);
    if (!pending.length) return base;
    return [
      ...base.filter((h) => {
        // Drop base polygon for fields with pending geometry so preview wins
        // (HighlightItem doesn't carry field id; keep all and append draft on top)
        return true;
      }),
      ...pending.map(([, geo]) => ({
        text: "",
        color: "transparent",
        borderColor: "#2563eb",
        isSelected: true,
        polygon: geo.polygon,
        page: geo.page,
      })),
    ];
  }, [getHighlightsForPDF, pendingGeometry]);

  const enterEditMode = useCallback(() => {
    setDraftParts(deepCloneParts(job.parts || []));
    setPendingGeometry({});
    setDrawMode(false);
    setEditMode(true);
  }, [job.parts]);

  const cancelEditMode = useCallback(() => {
    setEditMode(false);
    setDrawMode(false);
    setDraftParts(null);
    setPendingGeometry({});
  }, []);

  const updateDraftFieldValue = useCallback(
    (partName: string, fieldPath: string, rawText: string) => {
      setDraftParts((prev) => {
        if (!prev) return prev;
        const next = deepCloneParts(prev);
        const part = next.find((p) => p.part_name === partName);
        if (!part?.extracted_data) return prev;
        const path = highlightKeyForPath(fieldPath);
        const original = getAtFieldPath(part.extracted_data, path);
        const coerced = coerceEditedValue(rawText, original);
        setAtFieldPath(part.extracted_data, path, coerced);
        return next;
      });
    },
    [],
  );

  const resolvePartNameForField = useCallback(
    (fieldPath: string, preferredPart?: string | null) => {
      if (preferredPart) return preferredPart;
      if (selectedHighlightPartName) return selectedHighlightPartName;
      return findPartNameForFieldPath(draftParts ?? job.parts ?? [], fieldPath);
    },
    [selectedHighlightPartName, draftParts, job.parts],
  );

  const handleBoxDrawn = useCallback(
    (result: DrawBoxResult) => {
      if (!selectedField) {
        toast({
          title: "Select a field first",
          description: "Click a field on the left, then draw its box on the PDF.",
          variant: "destructive",
        });
        return;
      }
      const partName = resolvePartNameForField(selectedField);
      if (!partName) {
        toast({
          title: "Could not resolve part",
          description: "Unable to determine which job part owns this field.",
          variant: "destructive",
        });
        return;
      }
      setPendingGeometry((prev) => ({
        ...prev,
        [selectedField]: {
          page: result.page,
          polygon: result.polygon,
          partName,
        },
      }));
      toast({
        title: "Box updated",
        description: "Save to persist the new bounding box.",
      });
    },
    [selectedField, resolvePartNameForField],
  );

  const saveEdits = useCallback(async () => {
    if (!draftParts) return;
    setSavingEdits(true);
    try {
      const originalParts = job.parts || [];
      const updatesByPart = new Map<string, FieldCorrectionUpdate[]>();

      for (const draft of draftParts) {
        const orig = originalParts.find((p) => p.part_name === draft.part_name);
        const diffs = collectValueDiffs(
          orig?.extracted_data as Record<string, unknown> | undefined,
          draft.extracted_data as Record<string, unknown> | undefined,
        );
        if (!diffs.length) continue;
        const list = updatesByPart.get(draft.part_name) || [];
        for (const d of diffs) {
          list.push({ path: d.path, value: d.value });
        }
        updatesByPart.set(draft.part_name, list);
      }

      for (const [fieldPath, geo] of Object.entries(pendingGeometry)) {
        const list = updatesByPart.get(geo.partName) || [];
        const existing = list.find((u) => u.path === fieldPath);
        if (existing) {
          existing.page = geo.page;
          existing.polygon = geo.polygon;
        } else {
          list.push({ path: fieldPath, page: geo.page, polygon: geo.polygon });
        }
        updatesByPart.set(geo.partName, list);
      }

      if (updatesByPart.size === 0) {
        toast({ title: "No changes", description: "Nothing to save." });
        cancelEditMode();
        return;
      }

      let anyCache = false;
      for (const [partName, updates] of Array.from(updatesByPart.entries())) {
        const res = await api.patchJobPartFields(job.id, partName, updates);
        if (res.cache_synced) anyCache = true;
      }

      await queryClient.invalidateQueries({ queryKey: ["job", job.id] });
      await queryClient.invalidateQueries({ queryKey: ["jobTextIndex", job.id] });

      toast({
        title: "Corrections saved",
        description: anyCache
          ? "Values updated and extraction cache synced."
          : "Values updated (cache sync skipped).",
      });
      cancelEditMode();
    } catch (err) {
      toast({
        title: "Save failed",
        description: err instanceof Error ? err.message : "Could not save corrections",
        variant: "destructive",
      });
    } finally {
      setSavingEdits(false);
    }
  }, [draftParts, job.parts, job.id, pendingGeometry, cancelEditMode, queryClient]);

  // Reset copied state after 2 seconds
  useEffect(() => {
    if (copied) {
      const timer = setTimeout(() => setCopied(false), 2000);
      return () => clearTimeout(timer);
    }
  }, [copied]);

  // Fetch OCR text when OCR tab is selected
  useEffect(() => {
    if (activeTab === "ocr" && !ocrText && !ocrLoading && job.status === "completed") {
      setOcrLoading(true);
      setOcrError(null);
      api.getJobOcrText(job.id)
        .then((result) => {
          if (result.success && result.text) {
            setOcrText(result.text);
          } else {
            setOcrError(result.error || "Failed to load OCR text");
          }
        })
        .catch((err) => {
          setOcrError(err.message || "Failed to load OCR text");
        })
        .finally(() => {
          setOcrLoading(false);
        });
    }
  }, [activeTab, job.id, job.status, ocrText, ocrLoading]);

  const getProviderDisplayName = (type: "ocr" | "llm", name: string) => {
    if (!providers) return name;
    const list = type === "ocr" ? providers.ocr : providers.llm;
    const provider = list?.find((p) => p.name === name);
    return provider?.display_name || name;
  };

  // Helper to flatten nested objects (handles LLM responses that wrap data)
  // Preserves arrays and meaningful nested objects
  const flattenExtractedData = (data: Record<string, unknown>): Record<string, unknown> => {
    const result: Record<string, unknown> = {};

    const flatten = (obj: Record<string, unknown>, prefix = "") => {
      for (const [key, value] of Object.entries(obj)) {
        // Skip wrapper keys - go deeper into their contents
        if (key === "extraction" || key.endsWith("_invoice") || key.endsWith("_data")) {
          if (value && typeof value === "object" && !Array.isArray(value)) {
            flatten(value as Record<string, unknown>, prefix);
          }
        } else if (Array.isArray(value)) {
          // Preserve arrays as-is
          result[key] = value;
        } else if (value && typeof value === "object") {
          // For nested objects, keep them as objects (don't flatten)
          result[key] = value;
        } else {
          // Primitive value
          result[key] = value;
        }
      }
    };

    flatten(data);
    return result;
  };

  /**
   * Generate a meaningful display name for a segment based on extracted data.
   * Priority:
   * 1. Name fields (vendor_name, company_name, merchant_name, etc.)
   * 2. Document identifier fields (invoice_number, receipt_number, etc.)
   * 3. Fallback to doc_type + index or "Document N"
   */
  const getSegmentDisplayName = (
    extractedData: Record<string, unknown>,
    index: number,
    docType?: string,
    usedNames?: Set<string>
  ): string => {
    const MAX_NAME_LENGTH = 40;

    // Helper to get a value from extracted data (handles nested objects)
    const getValue = (data: Record<string, unknown>, keys: string[]): string | null => {
      for (const key of keys) {
        // Check direct key
        const value = data[key];
        if (value && typeof value === "string" && value.trim()) {
          return value.trim();
        }
        // Check nested objects (one level deep)
        for (const [objKey, objValue] of Object.entries(data)) {
          if (objValue && typeof objValue === "object" && !Array.isArray(objValue)) {
            const nested = objValue as Record<string, unknown>;
            if (nested[key] && typeof nested[key] === "string" && (nested[key] as string).trim()) {
              return (nested[key] as string).trim();
            }
          }
        }
      }
      return null;
    };

    // Helper to truncate long names with ellipsis
    const truncate = (str: string, maxLen: number): string => {
      if (str.length <= maxLen) return str;
      return str.substring(0, maxLen - 3).trim() + "...";
    };

    // Name fields to look for (in order of priority)
    const nameFields = [
      // Invoice/vendor
      "vendor_name", "vendor", "company_name", "supplier_name", "seller_name",
      "bill_from", "from", "shipper_name", "shipper",
      // Receipt/merchant
      "merchant_name", "restaurant_name", "store_name", "business_name",
      "establishment", "location_name",
      // General
      "name", "title", "sender", "issuer"
    ];

    // Document identifier fields
    const idFields = [
      "invoice_number", "invoice_no", "inv_number", "inv_no",
      "receipt_number", "receipt_no",
      "document_number", "doc_number", "doc_no",
      "reference_number", "ref_number", "ref_no", "reference",
      "order_number", "order_no", "po_number", "po_no",
      "bill_number", "bill_no", "tracking_number",
      "id", "number", "no"
    ];

    const used = usedNames || new Set<string>();

    // Try to find a name field
    const nameValue = getValue(extractedData, nameFields);
    if (nameValue) {
      const displayName = truncate(nameValue, MAX_NAME_LENGTH);
      return makeUniqueSegmentTitle(displayName, used);
    }

    // Try to find an identifier field
    const idValue = getValue(extractedData, idFields);
    if (idValue) {
      // Format as "DocType #ID" or just "#ID"
      const docTypeLabel = docType ? formatDocTypeLabel(docType) : "Document";
      const displayName = `${docTypeLabel} #${truncate(idValue, MAX_NAME_LENGTH - docTypeLabel.length - 2)}`;
      return makeUniqueSegmentTitle(displayName, used);
    }

    // Fallback: use doc_type + index or "Document N"
    const fallbackLabel = docType ? formatDocTypeLabel(docType) : "Document";
    const displayName = `${fallbackLabel} ${index + 1}`;
    return makeUniqueSegmentTitle(displayName, used);
  };

  // Get flattened data from all parts and segment index mapping
  const getAllFlattenedDataWithMapping = (
    segRows: DocumentSegmentResponse[] | undefined
  ): {
    data: Record<string, unknown>;
    segmentIndexMap: Map<string, number>;
    segmentTitles: Map<string, string>;
  } => {
    const parts = sortJobPartsByPage(sortedJobParts);
    const segmentIndexMap = new Map<string, number>();
    const segmentTitles = new Map<string, string>();

    // For multi-segment jobs, group data by segment to avoid field name collisions
    if (isMultiSegmentJob && parts.length > 1) {
      const usedNames = new Set<string>();
      const data = parts.reduce((acc, part, listIndex) => {
        if (part.extracted_data) {
          const flattened = flattenExtractedData(part.extracted_data as Record<string, unknown>);
          const segIdx = parseSegmentIndex(part.part_name) ?? listIndex;
          const stableKey = `__segment_${listIndex}`;
          const segRow = segRows?.find((s) => s.index === segIdx);
          const classified = segRow?.detected_type?.trim();
          let displayName: string;
          if (classified) {
            displayName = makeUniqueSegmentTitle(formatDocTypeLabel(classified), usedNames);
          } else {
            displayName = getSegmentDisplayName(
              part.extracted_data as Record<string, unknown>,
              segIdx,
              job.doc_type,
              usedNames
            );
          }
          usedNames.add(displayName);
          segmentIndexMap.set(stableKey, segIdx);
          segmentTitles.set(stableKey, displayName);
          acc[stableKey] = flattened;
        }
        return acc;
      }, {} as Record<string, unknown>);
      return { data, segmentIndexMap, segmentTitles };
    }

    // For single-part or standard multi-part jobs, merge as before
    const data = parts.reduce((acc, part) => {
      if (part.extracted_data) {
        const flattened = flattenExtractedData(part.extracted_data as Record<string, unknown>);
        Object.assign(acc, flattened);
      }
      return acc;
    }, {} as Record<string, unknown>);
    return { data, segmentIndexMap, segmentTitles };
  };

  // Get flattened data from all parts (for backwards compatibility)
  const getAllFlattenedData = () => getAllFlattenedDataWithMapping(segmentsData).data;

  const handleCopy = async () => {
    const allData = getAllFlattenedData();

    try {
      await navigator.clipboard.writeText(JSON.stringify(allData, null, 2));
      setCopied(true);
      toast({
        title: "Copied",
        description: "Data copied to clipboard",
      });
    } catch {
      toast({
        title: "Failed to copy",
        description: "Could not copy to clipboard",
        variant: "destructive",
      });
    }
  };

  const downloadFile = (content: string, mimeType: string, extension: string) => {
    const blob = new Blob([content], { type: mimeType });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${job.document_name.replace(".pdf", "")}.${extension}`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const handleExport = async (format: "pdf" | "csv" | "markdown") => {
    const { data: allData, segmentTitles } = getAllFlattenedDataWithMapping(segmentsData);
    const rows = getExportLabelValuePairs(allData, isMultiSegmentJob, segmentTitles);

    switch (format) {
      case "pdf": {
        const { jsPDF } = await import("jspdf");
        const doc = new jsPDF();
        const pageWidth = doc.internal.pageSize.getWidth();

        // Title
        doc.setFontSize(16);
        doc.setFont("helvetica", "bold");
        doc.text("Extracted Data", 14, 20);

        // Document name subtitle
        doc.setFontSize(10);
        doc.setFont("helvetica", "normal");
        doc.setTextColor(128);
        doc.text(job.document_name, 14, 28);

        // Data rows
        doc.setTextColor(0);
        let yPos = 40;
        const lineHeight = 8;

        rows.forEach(({ label, value }) => {
          if (yPos > 270) {
            doc.addPage();
            yPos = 20;
          }

          const formattedValue = formatExtractedValueForExportPlain(value);

          // Key (gray)
          doc.setFontSize(9);
          doc.setTextColor(100);
          doc.text(label, 14, yPos);

          // Value (black)
          doc.setTextColor(0);
          doc.setFontSize(10);
          const splitValue = doc.splitTextToSize(formattedValue, pageWidth - 90);
          doc.text(splitValue, 80, yPos);

          yPos += lineHeight * Math.max(1, splitValue.length);
        });

        doc.save(`${job.document_name.replace(".pdf", "")}-extracted.pdf`);
        break;
      }

      case "csv": {
        const lines = [
          `${escapeCsvField("Field")},${escapeCsvField("Value")}`,
          ...rows.map(({ label, value }) => {
            const cell = formatExtractedValueForExportPlain(value);
            return `${escapeCsvField(label)},${escapeCsvField(cell)}`;
          }),
        ];
        downloadFile(lines.join("\n"), "text/csv", "csv");
        break;
      }

      case "markdown": {
        let content = `# Extracted Data\n\n`;
        content += `**Document:** ${job.document_name}\n\n`;
        rows.forEach(({ label, value }) => {
          content += `**${label}**\n\n`;
          if (isLineItemsArrayForExport(value)) {
            const { unwrapped } = unwrapArrayItemsForExport(value);
            const displayRows = unwrapped as Record<string, unknown>[];
            const cols = objectKeysForDisplayRow(displayRows[0] as Record<string, unknown>);
            content += `${formatLineItemsAsMarkdownTable(displayRows, cols)}\n\n`;
          } else {
            content += `${formatExtractedValueForExportPlain(value)}\n\n`;
          }
        });
        downloadFile(content, "text/markdown", "md");
        break;
      }
    }
  };

  // Get all extracted data flattened with segment index mapping.
  // Depend on sortedJobParts (includes draftParts while editing) so controlled
  // inputs re-render on each keystroke instead of staying stuck on originals.
  const { data: extractedData, segmentIndexMap, segmentTitles } = useMemo(
    () => getAllFlattenedDataWithMapping(segmentsData),
    [sortedJobParts, isMultiSegmentJob, job.doc_type, segmentsData]
  );

  // Get segment keys from extractedData for collapse all functionality
  const segmentKeys = useMemo(() => {
    if (!isMultiSegmentJob) return [];
    // Keys in extractedData are stable segment keys (for example __segment_0)
    return Object.keys(extractedData).filter(key => {
      const value = extractedData[key];
      // Only include segment headers (objects, not arrays or primitives)
      return typeof value === "object" && value !== null && !Array.isArray(value);
    });
  }, [isMultiSegmentJob, extractedData]);

  // Check if all segments are collapsed
  const allSegmentsCollapsed = useMemo(() => {
    if (segmentKeys.length === 0) return false;
    return segmentKeys.every(key => collapsedSections.has(key));
  }, [segmentKeys, collapsedSections]);

  // Toggle collapse all segments
  const toggleCollapseAll = useCallback(() => {
    setCollapsedSections(prev => {
      if (allSegmentsCollapsed) {
        // Expand all - remove segment keys from collapsed set
        const next = new Set(prev);
        segmentKeys.forEach(key => next.delete(key));
        return next;
      } else {
        // Collapse all - add all segment keys to collapsed set
        const next = new Set(prev);
        segmentKeys.forEach(key => next.add(key));
        return next;
      }
    });
  }, [allSegmentsCollapsed, segmentKeys]);

  // Apply default expansion/collapse based on user preference when results are available.
  useEffect(() => {
    if (job.status !== "completed") return;

    if (autoExpandResults) {
      setCollapsedSections((prev) => (prev.size === 0 ? prev : new Set()));
      return;
    }

    const defaultCollapsed = new Set<string>();
    Object.entries(extractedData).forEach(([key, value]) => {
      const isSegmentHeader = isMultiSegmentJob &&
        typeof value === "object" &&
        value !== null &&
        !Array.isArray(value) &&
        Object.keys(value as Record<string, unknown>).length > 0;

      const isComplex = (Array.isArray(value) && value.length > 0 && typeof value[0] === "object") ||
        (typeof value === "object" && value !== null && !Array.isArray(value));

      // Keep barcode / signature fields expanded so results are visible
      if (isBarcodeHitList(value) || isSignatureHit(value)) {
        return;
      }

      if (isSegmentHeader || isComplex) {
        defaultCollapsed.add(key);
      }
    });

    setCollapsedSections((prev) => {
      if (prev.size !== defaultCollapsed.size) return defaultCollapsed;
      let hasMismatch = false;
      prev.forEach((key) => {
        if (!defaultCollapsed.has(key)) {
          hasMismatch = true;
        }
      });
      if (hasMismatch) return defaultCollapsed;
      return prev;
    });
  }, [autoExpandResults, extractedData, isMultiSegmentJob, job.status]);

  // Calculate confidence (average of all parts)
  const confidence =
    job.parts && job.parts.length > 0
      ? Math.round(
          (job.parts.reduce((sum, p) => sum + (p.confidence || 0), 0) /
            job.parts.length) *
            100
        )
      : 0;

  // Format field name for display
  const formatFieldName = (key: string) => {
    return key
      .replace(/_/g, " ")
      .replace(/([A-Z])/g, " $1")
      .split(" ")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1).toLowerCase())
      .join(" ")
      .trim();
  };

  // Format a value for display - unwraps ``{ value, ref_id? }`` so UI matches plain schemas
  const formatValue = (val: unknown): string => {
    if (val === null || val === undefined) return "";
    if (isValueRefWrapper(val)) {
      return formatValue((val as { value: unknown }).value);
    }
    if (typeof val === "string") {
      if (val.startsWith("data:image/")) return "[image]";
      return val;
    }
    if (typeof val === "number" || typeof val === "boolean") return String(val);
    if (Array.isArray(val)) {
      return val.map((v) => formatValue(v)).join(", ");
    }
    if (typeof val === "object") {
      const entries = objectEntriesForDisplay(val as Record<string, unknown>);
      return entries.map(([k, v]) => `${formatFieldName(k)}: ${formatValue(v)}`).join(", ");
    }
    return String(val);
  };

  const renderBarcodeHits = (
    fieldKey: string,
    items: Array<Record<string, unknown>>,
    partName?: string | null,
  ) => {
    if (!items.length) {
      return <span className="text-muted-foreground">No barcodes found</span>;
    }
    return (
      <div className="flex flex-wrap gap-1.5 py-1">
        {items.map((item, i) => {
          const hk = `${fieldKey}[${i}].value`;
          const canHl = hasDirectHighlights(hk) || hasDirectHighlights(`${fieldKey}[${i}]`);
          const highlightKey = hasDirectHighlights(hk) ? hk : `${fieldKey}[${i}]`;
          const border = canHl ? getFieldBorderColor(highlightKey) : undefined;
          const active = selectedField === highlightKey || hoveredField === highlightKey;
          return (
            <button
              type="button"
              key={i}
              className="inline-flex items-center gap-1 rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs text-indigo-800"
              style={
                canHl && active && border
                  ? { backgroundColor: hexToRgba(border, 0.18), borderColor: border }
                  : undefined
              }
              title={item.page != null ? `Page ${item.page}` : undefined}
              onClick={(e) => {
                e.stopPropagation();
                if (canHl) {
                  if (partName) setSelectedHighlightPartName(partName);
                  selectField(highlightKey);
                }
              }}
              onMouseEnter={() => canHl && hoverField(highlightKey)}
              onMouseLeave={() => hoverField(null)}
            >
              <span className="font-medium">{String(item.kind || "Code")}</span>
              <span className="max-w-[200px] truncate">{String(item.value || "")}</span>
              {item.page != null ? <span className="text-indigo-500">p{String(item.page)}</span> : null}
            </button>
          );
        })}
      </div>
    );
  };

  const renderSignatureHit = (fieldKey: string, sig: Record<string, unknown>) => {
    const present = Boolean(sig.present);
    const image = typeof sig.image_base64 === "string" ? sig.image_base64 : null;
    const hk = fieldKey;
    const canHl = hasDirectHighlights(hk);
    const border = canHl ? getFieldBorderColor(hk) : undefined;
    return (
      <div
        className="inline-flex flex-col gap-1 rounded border border-fuchsia-200 bg-fuchsia-50/60 p-2 text-xs"
        style={canHl && border && (selectedField === hk || hoveredField === hk)
          ? { borderColor: border }
          : undefined}
        onClick={(e) => {
          if (!canHl) return;
          e.stopPropagation();
          selectField(hk);
        }}
        onMouseEnter={() => canHl && hoverField(hk)}
        onMouseLeave={() => hoverField(null)}
      >
        <div className="flex items-center gap-2 text-fuchsia-900">
          <span className="font-medium">{present ? "Signed" : "Not signed"}</span>
          {sig.signature_type ? <span>({String(sig.signature_type)})</span> : null}
          {sig.page != null ? <span>· page {String(sig.page)}</span> : null}
        </div>
        {image && isDataImageString(image) ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={image}
            alt="Signature"
            className="max-h-28 max-w-[240px] rounded border bg-white object-contain"
          />
        ) : null}
      </div>
    );
  };

  /** Editable leaf for correction mode (primitives / value-ref wrappers). */
  const renderEditableLeaf = (
    fieldPath: string,
    value: unknown,
    partName: string | null | undefined,
  ) => {
    const isLeaf =
      value === null ||
      value === undefined ||
      typeof value === "string" ||
      typeof value === "number" ||
      typeof value === "boolean" ||
      isValueRefWrapper(value);
    if (!editMode || !isLeaf || !partName) {
      return formatValue(value);
    }
    return (
      <Input
        className="h-8 text-sm font-medium"
        value={formatValue(value)}
        onClick={(e) => e.stopPropagation()}
        onChange={(e) => updateDraftFieldValue(partName, fieldPath, e.target.value)}
      />
    );
  };

  // Detect if array items use wrapper pattern: [{wrapper: {actual_data}}]
  // Returns unwrapped items and the wrapper key if detected
  const unwrapArrayItems = (items: unknown[]): { unwrapped: unknown[], wrapperKey: string | null } => {
    if (items.length === 0 || typeof items[0] !== 'object' || items[0] === null) {
      return { unwrapped: items, wrapperKey: null };
    }

    const firstItem = items[0] as Record<string, unknown>;
    const keys = Object.keys(firstItem);

    // Check if single key wrapping another object
    if (keys.length === 1 && typeof firstItem[keys[0]] === 'object' && firstItem[keys[0]] !== null && !Array.isArray(firstItem[keys[0]])) {
      const wrapperKey = keys[0];
      const unwrapped = items.map(item => (item as Record<string, unknown>)[wrapperKey]);
      return { unwrapped, wrapperKey };
    }

    return { unwrapped: items, wrapperKey: null };
  };

  // Convert hex color to rgba for background
  const hexToRgba = (hex: string, alpha: number) => {
    const r = parseInt(hex.slice(1, 3), 16);
    const g = parseInt(hex.slice(3, 5), 16);
    const b = parseInt(hex.slice(5, 7), 16);
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  };

  // Calculate processing time
  const processingTime =
    job.completed_at && job.started_at
      ? (new Date(job.completed_at).getTime() -
          new Date(job.started_at).getTime()) /
        1000
      : 0;

  const filename = job.document_name.replace(".pdf", "");

  return (
    <div className={cn("h-full flex flex-col", compactView ? "p-2" : "p-6")}>
      {/* Header - Only show if not hidden */}
      {!hideHeader && (
        <div className={cn("flex-none flex items-center justify-between", compactView ? "mb-2" : "mb-6")}>
          <div className="flex items-center gap-4">
            {onBack && (
              <Button
                variant="ghost"
                size="icon"
                onClick={onBack}
                className="h-9 w-9"
              >
                <ChevronLeft className="h-5 w-5" />
              </Button>
            )}
            <div>
              <h1 className="text-xl font-semibold">Extraction Results</h1>
              <p className="text-sm text-muted-foreground">{job.document_name}</p>
            </div>
          </div>
          <div className="flex items-center gap-3">
            {!job.workflow_id && !hideSaveAsWorkflow && job.status === "completed" && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => setWorkflowModalOpen(true)}
                className="h-8"
              >
                <Workflow className="w-4 h-4 mr-2" />
                Save as Workflow
              </Button>
            )}
            <Badge
              variant="outline"
              className={cn(
                "capitalize",
                job.status === "completed" && "border-emerald-500 text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30",
                job.status === "failed" && "border-red-500 text-red-600 bg-red-50 dark:bg-red-950/30",
                job.status === "processing" && "border-blue-500 text-blue-600 bg-blue-50 dark:bg-blue-950/30"
              )}
            >
              {job.status}
            </Badge>
          </div>
        </div>
      )}

      {/* Error State */}
      {job.error ? (
        <Card className="border-destructive">
          <CardContent className="py-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center">
                <AlertCircle className="w-6 h-6 text-destructive" />
              </div>
              <div className="flex-1">
                <h3 className="font-semibold">Extraction Failed</h3>
                <p className="text-sm text-muted-foreground">{job.error}</p>
              </div>
              {onBack && <Button onClick={onBack}>Try Again</Button>}
            </div>
          </CardContent>
        </Card>
      ) : (
        /* Split View - Two Cards */
        <div className={cn("flex-1 grid grid-cols-1 lg:grid-cols-2 min-h-0", compactView ? "gap-2" : "gap-6")}>
          {/* Left Card - Extracted Data / OCR Text */}
          <Card className="flex flex-col min-h-0 overflow-hidden">
            {/* Card Header with Tabs */}
            <div className={cn("flex-none flex items-center justify-between border-b", compactView ? "px-2 py-1 h-10" : "px-4 py-2 h-14")}>
              <Tabs value={activeTab} onValueChange={(v) => setActiveTab(v as "extracted" | "ocr")} className="w-auto">
                <TabsList className="h-8">
                  <TabsTrigger value="extracted" className="text-xs px-3 h-7 gap-1.5">
                    <FileJson className="h-3.5 w-3.5" />
                    Extracted
                    {showConfidenceScores && confidence > 0 && (
                      <Badge
                        variant="outline"
                        className="border-emerald-500 text-emerald-600 bg-emerald-50 dark:bg-emerald-950/30 text-[10px] px-1 py-0 h-4 ml-1"
                      >
                        {confidence}%
                      </Badge>
                    )}
                  </TabsTrigger>
                  <TabsTrigger value="ocr" className="text-xs px-3 h-7 gap-1.5">
                    <ScanText className="h-3.5 w-3.5" />
                    OCR Text
                  </TabsTrigger>
                </TabsList>
              </Tabs>
              <div className="flex items-center gap-1 flex-shrink-0">
                {/* Human correction controls */}
                {job.status === "completed" && activeTab === "extracted" && (
                  editMode ? (
                    <>
                      <Button
                        variant="ghost"
                        size="icon"
                        className={cn("h-8 w-8", drawMode && "bg-blue-50 text-blue-600")}
                        onClick={() => setDrawMode((d) => !d)}
                        title={
                          drawMode
                            ? "Draw mode on — drag a box on the PDF"
                            : "Draw bounding box for selected field"
                        }
                        disabled={!selectedField}
                      >
                        <SquareDashed className="h-4 w-4" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-2"
                        onClick={() => void saveEdits()}
                        disabled={savingEdits}
                        title="Save corrections"
                      >
                        {savingEdits ? (
                          <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                          <Save className="h-4 w-4 mr-1" />
                        )}
                        Save
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-2"
                        onClick={cancelEditMode}
                        disabled={savingEdits}
                        title="Cancel edits"
                      >
                        <X className="h-4 w-4 mr-1" />
                        Cancel
                      </Button>
                    </>
                  ) : (
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8"
                      onClick={enterEditMode}
                      title="Edit field values / bounding boxes"
                    >
                      <Pencil className="h-4 w-4" />
                    </Button>
                  )
                )}

                {/* Collapse/Expand All Documents - only for multi-segment jobs */}
                {segmentKeys.length > 1 && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={toggleCollapseAll}
                    title={allSegmentsCollapsed ? "Expand all documents" : "Collapse all documents"}
                  >
                    <ChevronsUpDown className={cn(
                      "h-4 w-4 transition-colors",
                      allSegmentsCollapsed ? "text-muted-foreground" : "text-blue-500"
                    )} />
                  </Button>
                )}

                {/* Show All Highlights Toggle */}
                {indexedFieldKeys.length > 0 && (
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    onClick={toggleShowAll}
                    title={showAllHighlights ? "Hide all highlights" : "Show all highlights"}
                  >
                    <Focus className={cn(
                      "h-4 w-4 transition-colors",
                      showAllHighlights ? "text-blue-500" : "text-muted-foreground"
                    )} />
                  </Button>
                )}

                {/* Info HoverCard with futuristic design */}
                <HoverCard openDelay={100} closeDelay={200}>
                  <HoverCardTrigger asChild>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-8 w-8 group"
                    >
                      <Info className="h-4 w-4 transition-all duration-300 group-hover:text-emerald-500 group-hover:scale-110" />
                    </Button>
                  </HoverCardTrigger>
                  <HoverCardContent
                    align="end"
                    className="w-80 p-0 overflow-hidden"
                  >
                    {/* Header */}
                    <div className="px-4 py-3 border-b">
                      <div className="flex items-center gap-2">
                        <BarChart2 className="h-4 w-4 text-muted-foreground" />
                        <h4 className="font-semibold text-sm">
                          Processing Stats
                        </h4>
                      </div>
                    </div>

                    {/* Stats Grid */}
                    <div className="p-3 space-y-2">
                      {/* Providers Row */}
                      <div className="grid grid-cols-2 gap-2">
                        <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
                          <ScanText className="h-3.5 w-3.5 text-blue-500" />
                          <div className="min-w-0">
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">OCR</p>
                            <p className="text-xs font-medium truncate">
                              {getProviderDisplayName("ocr", job.ocr_provider)}
                            </p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
                          <Brain className="h-3.5 w-3.5 text-purple-500" />
                          <div className="min-w-0">
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">LLM</p>
                            <p className="text-xs font-medium truncate">
                              {getProviderDisplayName("llm", job.llm_provider)}
                            </p>
                          </div>
                        </div>
                      </div>

                      {/* Doc Type & Time Row */}
                      <div className="grid grid-cols-2 gap-2">
                        <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
                          <FileType className="h-3.5 w-3.5 text-orange-500" />
                          <div className="min-w-0">
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Type</p>
                            <p className="text-xs font-medium truncate">{job.doc_type}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
                          <Zap className="h-3.5 w-3.5 text-yellow-500" />
                          <div className="min-w-0">
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Time</p>
                            <p className="text-xs font-medium">
                              {processingTime > 0 ? `${processingTime.toFixed(2)}s` : "-"}
                            </p>
                          </div>
                        </div>
                      </div>

                      {/* Tokens Row */}
                      <div className="grid grid-cols-2 gap-2">
                        <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
                          <Cpu className="h-3.5 w-3.5 text-cyan-500" />
                          <div className="min-w-0">
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Input</p>
                            <p className="text-xs font-medium">{job.input_tokens?.toLocaleString() || 0}</p>
                          </div>
                        </div>
                        <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
                          <Cpu className="h-3.5 w-3.5 text-pink-500" />
                          <div className="min-w-0">
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Output</p>
                            <p className="text-xs font-medium">{job.output_tokens?.toLocaleString() || 0}</p>
                          </div>
                        </div>
                      </div>

                      {/* Bottom Row */}
                      <div className={cn("grid gap-2", showConfidenceScores ? "grid-cols-2" : "grid-cols-1")}>
                        <div className="flex items-center gap-2 p-2 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
                          <CalendarDays className="h-3.5 w-3.5 text-indigo-500" />
                          <div className="min-w-0">
                            <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Created</p>
                            <p className="text-xs font-medium">
                              {job.created_at
                                ? new Date(job.created_at).toLocaleDateString()
                                : "-"}
                            </p>
                          </div>
                        </div>
                        {showConfidenceScores && (
                          <div className="flex items-center gap-2 p-2 rounded-lg bg-gradient-to-r from-emerald-500/10 to-teal-500/10 border border-emerald-500/20">
                            <Gauge className="h-3.5 w-3.5 text-emerald-500" />
                            <div className="min-w-0">
                              <p className="text-[10px] text-muted-foreground uppercase tracking-wider">Confidence</p>
                              <p className="text-xs font-bold text-emerald-600">{confidence}%</p>
                            </div>
                          </div>
                        )}
                      </div>
                    </div>
                  </HoverCardContent>
                </HoverCard>

                {/* Copy Button with tick animation */}
                <Button
                  variant="ghost"
                  size="icon"
                  onClick={handleCopy}
                  className="h-8 w-8 relative"
                >
                  <div className={cn(
                    "transition-all duration-300",
                    copied ? "scale-0 opacity-0" : "scale-100 opacity-100"
                  )}>
                    <CopyIcon size={16} />
                  </div>
                  <div className={cn(
                    "absolute inset-0 flex items-center justify-center transition-all duration-300",
                    copied ? "scale-100 opacity-100" : "scale-0 opacity-0"
                  )}>
                    <Check className="h-4 w-4 text-emerald-500" />
                  </div>
                </Button>

                {/* Export Dropdown */}
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    <Button variant="ghost" size="icon" className="h-8 w-8">
                      <DownloadIcon size={16} />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent align="end">
                    <DropdownMenuItem onClick={() => handleExport("pdf")}>
                      <FileText className="mr-2 h-4 w-4 text-red-500" />
                      Export as PDF
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => handleExport("csv")}>
                      <Table2 className="mr-2 h-4 w-4 text-green-500" />
                      Export as CSV
                    </DropdownMenuItem>
                    <DropdownMenuItem onClick={() => handleExport("markdown")}>
                      <FileCode className="mr-2 h-4 w-4 text-blue-500" />
                      Export as Markdown
                    </DropdownMenuItem>
                  </DropdownMenuContent>
                </DropdownMenu>
              </div>
            </div>

            {/* Content Area - Conditional based on active tab */}
            {activeTab === "extracted" ? (
              /* Data Table */
              <div className="flex-1 min-h-0 overflow-y-auto overflow-x-hidden">
                <div className="w-full max-w-full min-w-0">
                  <div className="divide-y min-w-0">
                  {Object.entries(extractedData).map(([key, value]) => {
                    // Detect if this is a segment header (multi-segment job grouping)
                    // A segment header is an object with nested extracted fields, NOT an array or primitive
                    const isSegmentHeader = isMultiSegmentJob &&
                      typeof value === "object" &&
                      value !== null &&
                      !Array.isArray(value) &&
                      // Check if this looks like segment data (has field-like keys, not just one wrapper)
                      Object.keys(value as Record<string, unknown>).length > 0;

                    // For segment headers, render as collapsible section with nested fields
                    if (isSegmentHeader) {
                      const segmentData = value as Record<string, unknown>;
                      const isCollapsed = collapsedSections.has(key);
                      // Get segment index and page range for this segment
                      const segmentIndex = segmentIndexMap.get(key);
                      const pageRange = segmentIndex !== undefined ? segmentPageRanges.get(segmentIndex) : undefined;
                      const segPart =
                        segmentIndex !== undefined
                          ? sortedJobParts.find(
                              (p) => parseSegmentIndex(p.part_name) === segmentIndex
                            )?.part_name ?? `segment-${segmentIndex}`
                          : null;
                      const segmentHighlightOpts = { segmentPartName: segPart };

                      return (
                        <div key={key} className={cn(compactView ? "py-1 px-2" : "py-3 px-4")}>
                          {/* Segment Header */}
                          <div
                            className="flex items-center justify-between cursor-pointer mb-2"
                            onClick={() => toggleSection(key)}
                          >
                            <div className="flex items-center gap-2 flex-1 min-w-0">
                              <span className="text-sm font-semibold text-foreground truncate">
                                {segmentTitles.get(key) ?? key}
                              </span>
                              <Badge variant="secondary" className="h-5 px-1.5 text-[10px] font-medium shrink-0">
                                {Object.keys(segmentData).length} fields
                              </Badge>
                            </div>
                            <div className="flex items-center gap-1.5 shrink-0 ml-2">
                              {/* Page number pills */}
                              {pageRange && (
                                <div className="flex items-center gap-1" onClick={(e) => e.stopPropagation()}>
                                  {pageRange.pageStart === pageRange.pageEnd ? (
                                    <Badge
                                      variant={currentPage === pageRange.pageStart ? "default" : "outline"}
                                      className="cursor-pointer text-[10px] h-5 px-1.5 hover:bg-primary hover:text-primary-foreground transition-colors"
                                      onClick={() => handlePageClick(pageRange.pageStart)}
                                    >
                                      P{pageRange.pageStart}
                                    </Badge>
                                  ) : (
                                    <>
                                      {Array.from(
                                        { length: Math.min(pageRange.pageEnd - pageRange.pageStart + 1, 5) },
                                        (_, i) => pageRange.pageStart + i
                                      ).map((page) => (
                                        <Badge
                                          key={page}
                                          variant={currentPage === page ? "default" : "outline"}
                                          className="cursor-pointer text-[10px] h-5 px-1.5 hover:bg-primary hover:text-primary-foreground transition-colors"
                                          onClick={() => handlePageClick(page)}
                                        >
                                          {page}
                                        </Badge>
                                      ))}
                                      {pageRange.pageEnd - pageRange.pageStart + 1 > 5 && (
                                        <Badge
                                          variant="outline"
                                          className="cursor-pointer text-[10px] h-5 px-1.5 hover:bg-primary hover:text-primary-foreground transition-colors"
                                          onClick={() => handlePageClick(pageRange.pageEnd)}
                                        >
                                          ...{pageRange.pageEnd}
                                        </Badge>
                                      )}
                                    </>
                                  )}
                                </div>
                              )}
                              <ChevronDown
                                className={cn(
                                  "w-4 h-4 text-slate-400 transition-transform duration-200 ease-out",
                                  isCollapsed && "-rotate-90"
                                )}
                              />
                            </div>
                          </div>

                          {/* Segment Content - Nested Fields */}
                          <div className={cn(
                            "border-l-2 border-muted pl-3 space-y-0 divide-y transition-all duration-300 ease-out overflow-hidden",
                            isCollapsed ? "max-h-0 opacity-0" : "max-h-[5000px] opacity-100"
                          )}>
                            {Object.entries(segmentData).map(([fieldKey, fieldValue]) => {
                              // Use the original field key for highlighting lookups
                              const canHighlight = hasHighlights(fieldKey);
                              const isSelected = selectedField === fieldKey;
                              const isHovered = hoveredField === fieldKey && !isSelected;
                              const fieldBorderColor = canHighlight ? getFieldBorderColor(fieldKey) : undefined;
                              const isFieldValueRef =
                                typeof fieldValue === "object" &&
                                fieldValue !== null &&
                                !Array.isArray(fieldValue) &&
                                isValueRefWrapper(fieldValue);
                              const isFieldComplex =
                                (Array.isArray(fieldValue) && fieldValue.length > 0 && typeof fieldValue[0] === "object") ||
                                (typeof fieldValue === "object" &&
                                  fieldValue !== null &&
                                  !Array.isArray(fieldValue) &&
                                  !isFieldValueRef);
                              const isFieldCollapsed = collapsedSections.has(`${key}.${fieldKey}`);
                              const isActive = isSelected || isHovered;

                              return (
                                <div
                                  key={fieldKey}
                                  className={cn(
                                    "py-2 transition-all duration-150 relative",
                                    canHighlight && !isFieldComplex && "cursor-pointer"
                                  )}
                                  style={isActive && fieldBorderColor ? {
                                    backgroundColor: hexToRgba(fieldBorderColor, isSelected ? 0.1 : 0.05),
                                    borderLeft: `3px solid ${fieldBorderColor}`,
                                    paddingLeft: '9px',
                                    marginLeft: '-12px',
                                  } : undefined}
                                  onClick={() => {
                                    if (canHighlight && !isFieldComplex) {
                                      handleSelectField(fieldKey, segmentHighlightOpts);
                                    }
                                  }}
                                  onMouseEnter={() => {
                                    if (canHighlight && !isFieldComplex) {
                                      handleHoverField(fieldKey, segmentHighlightOpts);
                                    }
                                  }}
                                  onMouseLeave={() => handleHoverField(null)}
                                >
                                  <div
                                    className={cn(
                                      "flex items-center justify-between mb-1",
                                      isFieldComplex && "cursor-pointer"
                                    )}
                                    onClick={() => isFieldComplex && toggleSection(`${key}.${fieldKey}`)}
                                  >
                                    <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                                      {formatFieldName(fieldKey)}
                                      {canHighlight && (
                                        <span
                                          className="highlight-indicator"
                                          style={{ backgroundColor: fieldBorderColor }}
                                          title="Click to highlight in PDF"
                                        />
                                      )}
                                    </div>
                                    {isFieldComplex && (
                                      <div className="flex items-center gap-1.5">
                                        {Array.isArray(fieldValue) && (
                                          <Badge variant="secondary" className="h-5 px-1.5 text-[10px] font-medium">
                                            {fieldValue.length}
                                          </Badge>
                                        )}
                                        <ChevronDown
                                          className={cn(
                                            "w-4 h-4 text-slate-400 transition-transform duration-200 ease-out",
                                            isFieldCollapsed && "-rotate-90"
                                          )}
                                        />
                                      </div>
                                    )}
                                  </div>
                                  <div className={cn(
                                    "text-sm font-medium break-words transition-all duration-300 ease-out overflow-hidden",
                                    isFieldCollapsed && isFieldComplex && "max-h-0 opacity-0",
                                    (!isFieldCollapsed || !isFieldComplex) && "max-h-[2000px] opacity-100"
                                  )}>
                                    {/* Handle arrays - render as a table */}
                                    {isBarcodeHitList(fieldValue) || (Array.isArray(fieldValue) && fieldValue.length === 0 && fieldKey.toLowerCase().includes("barcode")) ? (
                                      renderBarcodeHits(fieldKey, isBarcodeHitList(fieldValue) ? fieldValue : [], segPart)
                                    ) : isSignatureHit(fieldValue) ? (
                                      renderSignatureHit(fieldKey, fieldValue)
                                    ) : Array.isArray(fieldValue) && fieldValue.length > 0 && typeof fieldValue[0] === "object" ? (
                                      (() => {
                                        const { unwrapped, wrapperKey } = unwrapArrayItems(fieldValue);
                                        const displayItems = unwrapped as Record<string, unknown>[];
                                        const columnKeys =
                                          displayItems.length > 0 &&
                                          typeof displayItems[0] === "object" &&
                                          displayItems[0] !== null
                                            ? objectKeysForDisplayRow(displayItems[0] as Record<string, unknown>)
                                            : [];

                                        return (
                                          <div className="mt-2 border rounded-lg overflow-auto max-h-[500px] w-full min-w-0">
                                            <table className="w-full min-w-max text-xs">
                                              <thead className="bg-muted/50">
                                                <tr>
                                                  {columnKeys.map((col) => (
                                                    <th key={col} className="px-3 py-2 text-left font-medium text-muted-foreground">
                                                      {formatFieldName(col)}
                                                    </th>
                                                  ))}
                                                </tr>
                                              </thead>
                                              <tbody className="divide-y">
                                                {displayItems.map((item, idx) => {
                                                  if (typeof item !== 'object' || item === null) {
                                                    return (
                                                      <tr key={idx} className="hover:bg-muted/30">
                                                        <td className="px-3 py-2">{formatValue(item)}</td>
                                                      </tr>
                                                    );
                                                  }
                                                  const itemObj = item as Record<string, unknown>;
                                                  return (
                                                    <tr key={idx} className="hover:bg-muted/30">
                                                      {columnKeys.map((colKey, cellIdx) => {
                                                        // Use original field path for highlighting
                                                        const cellKey = wrapperKey
                                                          ? `${fieldKey}[${idx}].${wrapperKey}.${colKey}`
                                                          : `${fieldKey}[${idx}].${colKey}`;
                                                        const cellHk = highlightKeyForPath(cellKey);
                                                        const cellCanHighlight = hasDirectHighlights(cellHk);
                                                        const cellBorderColor = cellCanHighlight ? getFieldBorderColor(cellHk) : undefined;
                                                        const cellValue = itemObj[colKey];
                                                        const isCellActive = selectedField === cellHk || hoveredField === cellHk;
                                                        return (
                                                          <td
                                                            key={cellIdx}
                                                            className={cn(
                                                              "px-3 py-2 transition-colors",
                                                              cellCanHighlight && "cursor-pointer"
                                                            )}
                                                            style={
                                                              cellCanHighlight && isCellActive && cellBorderColor
                                                                ? { backgroundColor: hexToRgba(cellBorderColor, selectedField === cellHk ? 0.15 : 0.08) }
                                                                : undefined
                                                            }
                                                            onClick={(e) => {
                                                              if (cellCanHighlight) {
                                                                e.stopPropagation();
                                                                if (hasMultipleDataParts && segPart) {
                                                                  setSelectedHighlightPartName(segPart);
                                                                }
                                                                selectField(cellHk);
                                                              }
                                                            }}
                                                            onMouseEnter={() => {
                                                              if (!cellCanHighlight) return;
                                                              if (hasMultipleDataParts && segPart) {
                                                                setHoverHighlightPartName(segPart);
                                                              }
                                                              hoverField(cellHk);
                                                            }}
                                                            onMouseLeave={() => {
                                                              setHoverHighlightPartName(null);
                                                              hoverField(null);
                                                            }}
                                                          >
                                                            <span className="flex items-center gap-1">
                                                              {renderEditableLeaf(cellKey, cellValue, segPart)}
                                                              {cellCanHighlight && (
                                                                <span
                                                                  className="highlight-indicator flex-shrink-0"
                                                                  style={{ backgroundColor: cellBorderColor }}
                                                                />
                                                              )}
                                                            </span>
                                                          </td>
                                                        );
                                                      })}
                                                    </tr>
                                                  );
                                                })}
                                              </tbody>
                                            </table>
                                          </div>
                                        );
                                      })()
                                    ) : Array.isArray(fieldValue) ? (
                                      <span>{fieldValue.map(v => formatValue(v)).join(", ")}</span>
                                    ) : isValueRefWrapper(fieldValue) ? (
                                      <span className="break-words">{renderEditableLeaf(fieldKey, fieldValue, segPart)}</span>
                                    ) : typeof fieldValue === "object" && fieldValue !== null ? (
                                      <div className="mt-1 pl-3 border-l-2 border-muted space-y-1">
                                        {objectEntriesForDisplay(fieldValue as Record<string, unknown>).map(([nk, nv]) => {
                                          const nestedKey = `${fieldKey}.${nk}`;
                                          const nestedHk = highlightKeyForPath(nestedKey);
                                          const nestedCanHighlight = hasDirectHighlights(nestedHk);
                                          const nestedBorderColor = nestedCanHighlight ? getFieldBorderColor(nestedHk) : undefined;
                                          const isNestedActive = selectedField === nestedHk || hoveredField === nestedHk;
                                          return (
                                            <div
                                              key={nk}
                                              className={cn(
                                                "flex gap-2 rounded px-1 -mx-1 transition-colors",
                                                nestedCanHighlight && "cursor-pointer"
                                              )}
                                              style={
                                                nestedCanHighlight && isNestedActive && nestedBorderColor
                                                  ? { backgroundColor: hexToRgba(nestedBorderColor, selectedField === nestedHk ? 0.15 : 0.08) }
                                                  : undefined
                                              }
                                              onClick={(e) => {
                                                if (nestedCanHighlight) {
                                                  e.stopPropagation();
                                                  if (hasMultipleDataParts && segPart) {
                                                    setSelectedHighlightPartName(segPart);
                                                  }
                                                  selectField(nestedHk);
                                                }
                                              }}
                                              onMouseEnter={() => {
                                                if (!nestedCanHighlight) return;
                                                if (hasMultipleDataParts && segPart) {
                                                  setHoverHighlightPartName(segPart);
                                                }
                                                hoverField(nestedHk);
                                              }}
                                              onMouseLeave={() => {
                                                setHoverHighlightPartName(null);
                                                hoverField(null);
                                              }}
                                            >
                                              <span className="text-muted-foreground flex items-center gap-1">
                                                {formatFieldName(nk)}:
                                                {nestedCanHighlight && (
                                                  <span
                                                    className="highlight-indicator"
                                                    style={{ backgroundColor: nestedBorderColor }}
                                                  />
                                                )}
                                              </span>
                                              <span>{renderEditableLeaf(nestedKey, nv, segPart)}</span>
                                            </div>
                                          );
                                        })}
                                      </div>
                                    ) : (
                                      renderEditableLeaf(fieldKey, fieldValue, segPart)
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        </div>
                      );
                    }

                    // Standard field rendering (non-segment)
                    const canHighlight = hasHighlights(key);
                    const isSelected = selectedField === key;
                    const isHovered = hoveredField === key && !isSelected;
                    const fieldBorderColor = canHighlight ? getFieldBorderColor(key) : undefined;
                    const isValueRef =
                      typeof value === "object" &&
                      value !== null &&
                      !Array.isArray(value) &&
                      isValueRefWrapper(value);
                    const isComplex =
                      (Array.isArray(value) && value.length > 0 && typeof value[0] === "object") ||
                      (typeof value === "object" && value !== null && !Array.isArray(value) && !isValueRef);
                    const isCollapsed = collapsedSections.has(key);

                    const isActive = isSelected || isHovered;

                    return (
                      <div
                        key={key}
                        className={cn(
                          "transition-all duration-150 relative",
                          compactView ? "py-1 px-2" : "py-3 px-4",
                          canHighlight && (!isComplex || isValueRef) && "cursor-pointer"
                        )}
                        style={isActive && fieldBorderColor ? {
                          backgroundColor: hexToRgba(fieldBorderColor, isSelected ? 0.1 : 0.05),
                          borderLeft: `3px solid ${fieldBorderColor}`,
                          paddingLeft: '13px',
                        } : undefined}
                        onClick={() => {
                          if (canHighlight && (!isComplex || isValueRef)) {
                            handleSelectField(key);
                          }
                        }}
                        onMouseEnter={() => {
                          if (canHighlight && (!isComplex || isValueRef)) {
                            handleHoverField(key);
                          }
                        }}
                        onMouseLeave={() => handleHoverField(null)}
                      >
                        <div
                          className={cn(
                            "flex items-center justify-between mb-1",
                            isComplex && "cursor-pointer"
                          )}
                          onClick={() => isComplex && toggleSection(key)}
                        >
                          <div className="flex items-center gap-1.5 text-sm text-muted-foreground">
                            {formatFieldName(key)}
                            {Array.isArray(value) ? ` (${value.length})` : ""}
                            {canHighlight && (
                              <span
                                className="highlight-indicator"
                                style={{ backgroundColor: fieldBorderColor }}
                                title="Click to highlight in PDF"
                              />
                            )}
                          </div>
                          {isComplex && (
                            <div className="flex items-center gap-1.5">
                              {Array.isArray(value) && (
                                <Badge variant="secondary" className="h-5 px-1.5 text-[10px] font-medium">
                                  {value.length}
                                </Badge>
                              )}
                              <ChevronDown
                                className={cn(
                                  "w-4 h-4 text-slate-400 transition-transform duration-200 ease-out",
                                  isCollapsed && "-rotate-90"
                                )}
                              />
                            </div>
                          )}
                        </div>
                        <div className={cn(
                          "text-sm font-medium break-words transition-all duration-300 ease-out overflow-hidden",
                          isCollapsed && isComplex && "max-h-0 opacity-0",
                          (!isCollapsed || !isComplex) && "max-h-[2000px] opacity-100"
                        )}>
                          {/* Handle arrays - render as a table */}
                          {isBarcodeHitList(value) || (Array.isArray(value) && value.length === 0 && key.toLowerCase().includes("barcode")) ? (
                            renderBarcodeHits(key, isBarcodeHitList(value) ? value : [])
                          ) : isSignatureHit(value) ? (
                            renderSignatureHit(key, value)
                          ) : Array.isArray(value) && value.length > 0 && typeof value[0] === "object" ? (
                            (() => {
                              // Unwrap array items if they use wrapper pattern
                              const { unwrapped, wrapperKey } = unwrapArrayItems(value);
                              const displayItems = unwrapped as Record<string, unknown>[];

                              // Get column keys from the first unwrapped item
                              const columnKeys =
                                displayItems.length > 0 &&
                                typeof displayItems[0] === "object" &&
                                displayItems[0] !== null
                                  ? objectKeysForDisplayRow(displayItems[0] as Record<string, unknown>)
                                  : [];

                              return (
                                <div className="mt-2 border rounded-lg overflow-auto max-h-[500px] w-full min-w-0">
                                  <table className="w-full min-w-max text-xs">
                                    <thead className="bg-muted/50">
                                      <tr>
                                        {columnKeys.map((col) => (
                                          <th key={col} className="px-3 py-2 text-left font-medium text-muted-foreground">
                                            {formatFieldName(col)}
                                          </th>
                                        ))}
                                      </tr>
                                    </thead>
                                    <tbody className="divide-y">
                                      {displayItems.map((item, idx) => {
                                        if (typeof item !== 'object' || item === null) {
                                          return (
                                            <tr key={idx} className="hover:bg-muted/30">
                                              <td className="px-3 py-2">{formatValue(item)}</td>
                                            </tr>
                                          );
                                        }
                                        const itemObj = item as Record<string, unknown>;
                                        return (
                                          <tr key={idx} className="hover:bg-muted/30">
                                            {columnKeys.map((colKey, cellIdx) => {
                                              // Build the correct path for highlighting
                                              // If wrapped: key[idx].wrapperKey.colKey, otherwise: key[idx].colKey
                                              const cellKey = wrapperKey
                                                ? `${key}[${idx}].${wrapperKey}.${colKey}`
                                                : `${key}[${idx}].${colKey}`;
                                              const cellHk = highlightKeyForPath(cellKey);
                                              const cellCanHighlight = hasDirectHighlights(cellHk);
                                              const cellBorderColor = cellCanHighlight ? getFieldBorderColor(cellHk) : undefined;
                                              const cellValue = itemObj[colKey];
                                              const isCellActive = selectedField === cellHk || hoveredField === cellHk;
                                              return (
                                                <td
                                                  key={cellIdx}
                                                  className={cn(
                                                    "px-3 py-2 transition-colors",
                                                    cellCanHighlight && "cursor-pointer"
                                                  )}
                                                  style={
                                                    cellCanHighlight && isCellActive && cellBorderColor
                                                      ? { backgroundColor: hexToRgba(cellBorderColor, selectedField === cellHk ? 0.15 : 0.08) }
                                                      : undefined
                                                  }
                                                  onClick={(e) => {
                                                    if (cellCanHighlight) {
                                                      e.stopPropagation();
                                                      selectField(cellHk);
                                                    }
                                                  }}
                                                  onMouseEnter={() => cellCanHighlight && hoverField(cellHk)}
                                                  onMouseLeave={() => hoverField(null)}
                                                >
                                                  <span className="flex items-center gap-1">
                                                    {renderEditableLeaf(cellKey, cellValue, findPartNameForFieldPath(sortedJobParts, cellKey))}
                                                    {cellCanHighlight && (
                                                      <span
                                                        className="highlight-indicator flex-shrink-0"
                                                        style={{ backgroundColor: cellBorderColor }}
                                                      />
                                                    )}
                                                  </span>
                                                </td>
                                              );
                                            })}
                                          </tr>
                                        );
                                      })}
                                    </tbody>
                                  </table>
                                </div>
                              );
                            })()
                          ) : Array.isArray(value) ? (
                            /* Simple array - show as comma-separated */
                            <span>{value.map(v => formatValue(v)).join(", ")}</span>
                          ) : isValueRefWrapper(value) ? (
                            /* Single LLM field object: show value only (same as primitive schema) */
                            <span className="break-words">{renderEditableLeaf(key, value, findPartNameForFieldPath(sortedJobParts, key))}</span>
                          ) : typeof value === "object" && value !== null ? (
                            /* Object - show as formatted JSON or key-value pairs */
                            <div className="mt-1 pl-3 border-l-2 border-muted space-y-1">
                              {objectEntriesForDisplay(value as Record<string, unknown>).map(([k, v]) => {
                                const nestedKey = `${key}.${k}`;
                                const nestedHk = highlightKeyForPath(nestedKey);
                                const nestedCanHighlight = hasDirectHighlights(nestedHk);
                                const nestedBorderColor = nestedCanHighlight ? getFieldBorderColor(nestedHk) : undefined;

                                // Check if this nested value is an array of objects - render as table
                                if (Array.isArray(v) && v.length > 0 && typeof v[0] === 'object' && v[0] !== null) {
                                  const { unwrapped, wrapperKey } = unwrapArrayItems(v);
                                  const displayItems = unwrapped as Record<string, unknown>[];
                                  const columnKeys = displayItems.length > 0 && typeof displayItems[0] === 'object' && displayItems[0] !== null
                                    ? objectKeysForDisplayRow(displayItems[0] as Record<string, unknown>)
                                    : [];
                                  const isNestedArrayCollapsed = collapsedSections.has(nestedKey);

                                  return (
                                    <div key={k} className="py-1">
                                      <div
                                        className="flex items-center justify-between cursor-pointer"
                                        onClick={() => toggleSection(nestedKey)}
                                      >
                                        <div className="text-muted-foreground text-sm flex items-center gap-1">
                                          {formatFieldName(k)}
                                          {nestedCanHighlight && (
                                            <span
                                              className="highlight-indicator"
                                              style={{ backgroundColor: nestedBorderColor }}
                                            />
                                          )}
                                        </div>
                                        <div className="flex items-center gap-1.5">
                                          <Badge variant="secondary" className="h-5 px-1.5 text-[10px] font-medium">
                                            {displayItems.length}
                                          </Badge>
                                          <ChevronDown
                                            className={cn(
                                              "w-3.5 h-3.5 text-slate-400 transition-transform duration-200 ease-out",
                                              isNestedArrayCollapsed && "-rotate-90"
                                            )}
                                          />
                                        </div>
                                      </div>
                                      <div className={cn(
                                        "border rounded-lg overflow-hidden transition-all duration-200",
                                        isNestedArrayCollapsed ? "max-h-0 opacity-0 mt-0" : "max-h-[1000px] opacity-100 mt-1"
                                      )}>
                                        <table className="w-full text-xs">
                                          <thead className="bg-muted/50">
                                            <tr>
                                              {columnKeys.map((col) => (
                                                <th key={col} className="px-3 py-2 text-left font-medium text-muted-foreground">
                                                  {formatFieldName(col)}
                                                </th>
                                              ))}
                                            </tr>
                                          </thead>
                                          <tbody className="divide-y">
                                            {displayItems.map((item, idx) => {
                                              if (typeof item !== 'object' || item === null) {
                                                return (
                                                  <tr key={idx} className="hover:bg-muted/30">
                                                    <td className="px-3 py-2">{formatValue(item)}</td>
                                                  </tr>
                                                );
                                              }
                                              const itemObj = item as Record<string, unknown>;
                                              return (
                                                <tr key={idx} className="hover:bg-muted/30">
                                                  {columnKeys.map((colKey, cellIdx) => {
                                                    const cellKey = wrapperKey
                                                      ? `${nestedKey}[${idx}].${wrapperKey}.${colKey}`
                                                      : `${nestedKey}[${idx}].${colKey}`;
                                                    const cellHk2 = highlightKeyForPath(cellKey);
                                                    const cellCanHighlight = hasDirectHighlights(cellHk2);
                                                    const cellBorderColor = cellCanHighlight ? getFieldBorderColor(cellHk2) : undefined;
                                                    const cellValue = itemObj[colKey];
                                                    return (
                                                      <td
                                                        key={cellIdx}
                                                        className={cn(
                                                          "px-3 py-2 transition-colors",
                                                          cellCanHighlight && "cursor-pointer"
                                                        )}
                                                        style={
                                                          cellCanHighlight && (selectedField === cellHk2 || hoveredField === cellHk2) && cellBorderColor
                                                            ? { backgroundColor: hexToRgba(cellBorderColor, selectedField === cellHk2 ? 0.15 : 0.08) }
                                                            : undefined
                                                        }
                                                        onClick={(e) => {
                                                          if (cellCanHighlight) {
                                                            e.stopPropagation();
                                                            selectField(cellHk2);
                                                          }
                                                        }}
                                                        onMouseEnter={() => cellCanHighlight && hoverField(cellHk2)}
                                                        onMouseLeave={() => hoverField(null)}
                                                      >
                                                        <span className="flex items-center gap-1">
                                                          {renderEditableLeaf(cellKey, cellValue, findPartNameForFieldPath(sortedJobParts, cellKey))}
                                                          {cellCanHighlight && (
                                                            <span
                                                              className="highlight-indicator flex-shrink-0"
                                                              style={{ backgroundColor: cellBorderColor }}
                                                            />
                                                          )}
                                                        </span>
                                                      </td>
                                                    );
                                                  })}
                                                </tr>
                                              );
                                            })}
                                          </tbody>
                                        </table>
                                      </div>
                                    </div>
                                  );
                                }

                                // ``{ value, ref_id }`` leaf: one row (do not expand into Value / Ref Id sub-rows)
                                if (isValueRefWrapper(v)) {
                                  const isNestedActive = selectedField === nestedHk || hoveredField === nestedHk;
                                  return (
                                    <div
                                      key={k}
                                      className={cn(
                                        "flex gap-2 rounded px-1 -mx-1 transition-colors",
                                        nestedCanHighlight && "cursor-pointer"
                                      )}
                                      style={
                                        nestedCanHighlight && isNestedActive && nestedBorderColor
                                          ? { backgroundColor: hexToRgba(nestedBorderColor, selectedField === nestedHk ? 0.15 : 0.08) }
                                          : undefined
                                      }
                                      onClick={(e) => {
                                        if (nestedCanHighlight) {
                                          e.stopPropagation();
                                          selectField(nestedHk);
                                        }
                                      }}
                                      onMouseEnter={() => nestedCanHighlight && hoverField(nestedHk)}
                                      onMouseLeave={() => hoverField(null)}
                                    >
                                      <span className="text-muted-foreground flex items-center gap-1">
                                        {formatFieldName(k)}:
                                        {nestedCanHighlight && (
                                          <span
                                            className="highlight-indicator"
                                            style={{ backgroundColor: nestedBorderColor }}
                                          />
                                        )}
                                      </span>
                                      <span className="break-words">{renderEditableLeaf(nestedKey, v, findPartNameForFieldPath(sortedJobParts, nestedKey))}</span>
                                    </div>
                                  );
                                }

                                // Check if nested value is an object - render recursively
                                if (typeof v === 'object' && v !== null && !Array.isArray(v)) {
                                  const nestedObj = v as Record<string, unknown>;
                                  const isNestedObjCollapsed = collapsedSections.has(nestedKey);
                                  return (
                                    <div key={k} className="py-1">
                                      <div
                                        className="flex items-center justify-between cursor-pointer"
                                        onClick={() => toggleSection(nestedKey)}
                                      >
                                        <div className="text-muted-foreground text-sm flex items-center gap-1">
                                          {formatFieldName(k)}
                                          {nestedCanHighlight && (
                                            <span
                                              className="highlight-indicator"
                                              style={{ backgroundColor: nestedBorderColor }}
                                            />
                                          )}
                                        </div>
                                        <ChevronDown
                                          className={cn(
                                            "w-3.5 h-3.5 text-slate-400 transition-transform duration-200 ease-out",
                                            isNestedObjCollapsed && "-rotate-90"
                                          )}
                                        />
                                      </div>
                                      <div className={cn(
                                        "pl-3 border-l-2 border-muted space-y-1 transition-all duration-200 overflow-hidden",
                                        isNestedObjCollapsed ? "max-h-0 opacity-0" : "max-h-[2000px] opacity-100"
                                      )}>
                                        {objectEntriesForDisplay(nestedObj).map(([nk, nv]) => {
                                          const deepKey = `${nestedKey}.${nk}`;
                                          const deepHk = highlightKeyForPath(deepKey);
                                          const deepCanHighlight = hasDirectHighlights(deepHk);
                                          const deepBorderColor = deepCanHighlight ? getFieldBorderColor(deepHk) : undefined;

                                          // Handle arrays inside nested objects (e.g., layers inside data_warehouse)
                                          if (Array.isArray(nv) && nv.length > 0 && typeof nv[0] === 'object' && nv[0] !== null) {
                                            const { unwrapped, wrapperKey } = unwrapArrayItems(nv);
                                            const displayItems = unwrapped as Record<string, unknown>[];
                                            const columnKeys =
                                              displayItems.length > 0 &&
                                              typeof displayItems[0] === "object" &&
                                              displayItems[0] !== null
                                                ? objectKeysForDisplayRow(displayItems[0] as Record<string, unknown>)
                                                : [];
                                            const isDeepArrayCollapsed = collapsedSections.has(deepKey);

                                            return (
                                              <div key={nk} className="py-1">
                                                <div
                                                  className="flex items-center justify-between cursor-pointer"
                                                  onClick={() => toggleSection(deepKey)}
                                                >
                                                  <div className="text-muted-foreground text-xs flex items-center gap-1">
                                                    {formatFieldName(nk)}
                                                    {deepCanHighlight && (
                                                      <span
                                                        className="highlight-indicator"
                                                        style={{ backgroundColor: deepBorderColor }}
                                                      />
                                                    )}
                                                  </div>
                                                  <div className="flex items-center gap-1.5">
                                                    <Badge variant="secondary" className="h-4 px-1 text-[9px] font-medium">
                                                      {displayItems.length}
                                                    </Badge>
                                                    <ChevronDown
                                                      className={cn(
                                                        "w-3 h-3 text-slate-400 transition-transform duration-200 ease-out",
                                                        isDeepArrayCollapsed && "-rotate-90"
                                                      )}
                                                    />
                                                  </div>
                                                </div>
                                                <div className={cn(
                                                  "border rounded-lg overflow-hidden transition-all duration-200",
                                                  isDeepArrayCollapsed ? "max-h-0 opacity-0 mt-0" : "max-h-[500px] opacity-100 mt-1"
                                                )}>
                                                  <table className="w-full text-xs">
                                                    <thead className="bg-muted/50">
                                                      <tr>
                                                        {columnKeys.map((col) => (
                                                          <th key={col} className="px-2 py-1 text-left font-medium text-muted-foreground">
                                                            {formatFieldName(col)}
                                                          </th>
                                                        ))}
                                                      </tr>
                                                    </thead>
                                                    <tbody className="divide-y">
                                                      {displayItems.map((item, idx) => {
                                                        if (typeof item !== 'object' || item === null) {
                                                          return (
                                                            <tr key={idx}>
                                                              <td className="px-2 py-1">{formatValue(item)}</td>
                                                            </tr>
                                                          );
                                                        }
                                                        const itemObj = item as Record<string, unknown>;
                                                        return (
                                                          <tr key={idx}>
                                                            {columnKeys.map((colKey, cellIdx) => (
                                                              <td key={cellIdx} className="px-2 py-1">
                                                                {formatValue(itemObj[colKey])}
                                                              </td>
                                                            ))}
                                                          </tr>
                                                        );
                                                      })}
                                                    </tbody>
                                                  </table>
                                                </div>
                                              </div>
                                            );
                                          }

                                          const isDeepActive = selectedField === deepHk || hoveredField === deepHk;
                                          return (
                                            <div
                                              key={nk}
                                              className={cn(
                                                "flex gap-2 text-sm rounded px-1 -mx-1 transition-colors",
                                                deepCanHighlight && "cursor-pointer"
                                              )}
                                              style={
                                                deepCanHighlight && isDeepActive && deepBorderColor
                                                  ? { backgroundColor: hexToRgba(deepBorderColor, selectedField === deepHk ? 0.15 : 0.08) }
                                                  : undefined
                                              }
                                              onClick={(e) => {
                                                if (deepCanHighlight) {
                                                  e.stopPropagation();
                                                  selectField(deepHk);
                                                }
                                              }}
                                              onMouseEnter={() => deepCanHighlight && hoverField(deepHk)}
                                              onMouseLeave={() => hoverField(null)}
                                            >
                                              <span className="text-muted-foreground flex items-center gap-1">
                                                {formatFieldName(nk)}:
                                                {deepCanHighlight && (
                                                  <span
                                                    className="highlight-indicator"
                                                    style={{ backgroundColor: deepBorderColor }}
                                                  />
                                                )}
                                              </span>
                                              <span>{formatValue(nv)}</span>
                                            </div>
                                          );
                                        })}
                                      </div>
                                    </div>
                                  );
                                }

                                const isNestedActive = selectedField === nestedHk || hoveredField === nestedHk;
                                return (
                                  <div
                                    key={k}
                                    className={cn(
                                      "flex gap-2 rounded px-1 -mx-1 transition-colors",
                                      nestedCanHighlight && "cursor-pointer"
                                    )}
                                    style={
                                      nestedCanHighlight && isNestedActive && nestedBorderColor
                                        ? { backgroundColor: hexToRgba(nestedBorderColor, selectedField === nestedHk ? 0.15 : 0.08) }
                                        : undefined
                                    }
                                    onClick={(e) => {
                                      if (nestedCanHighlight) {
                                        e.stopPropagation();
                                        selectField(nestedHk);
                                      }
                                    }}
                                    onMouseEnter={() => nestedCanHighlight && hoverField(nestedHk)}
                                    onMouseLeave={() => hoverField(null)}
                                  >
                                    <span className="text-muted-foreground flex items-center gap-1">
                                      {formatFieldName(k)}:
                                      {nestedCanHighlight && (
                                        <span
                                          className="highlight-indicator"
                                          style={{ backgroundColor: nestedBorderColor }}
                                        />
                                      )}
                                    </span>
                                    <span>{renderEditableLeaf(nestedKey, v, findPartNameForFieldPath(sortedJobParts, nestedKey))}</span>
                                  </div>
                                );
                              })}
                            </div>
                          ) : (
                            /* Primitive value */
                            renderEditableLeaf(key, value, findPartNameForFieldPath(sortedJobParts, key))
                          )}
                        </div>
                      </div>
                    );
                  })}
                  {Object.keys(extractedData).length === 0 && (
                    <div className="py-8 text-center text-muted-foreground">
                      {job.status === "processing" || job.status === "pending" ? (
                        <div className="flex flex-col items-center gap-3">
                          <Loader2 className="h-8 w-8 animate-spin" />
                          <p>Extracting data...</p>
                        </div>
                      ) : (
                        "No data extracted"
                      )}
                    </div>
                  )}
                </div>
                </div>
              </div>
            ) : (
              /* OCR Text View */
              <ScrollArea className="flex-1">
                {ocrLoading ? (
                  <div className="h-full flex items-center justify-center py-12">
                    <div className="flex flex-col items-center gap-3">
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                      <p className="text-sm text-muted-foreground">Loading OCR text...</p>
                    </div>
                  </div>
                ) : ocrError ? (
                  <div className="h-full flex items-center justify-center py-12">
                    <div className="flex flex-col items-center gap-3 text-center px-4">
                      <AlertCircle className="h-8 w-8 text-destructive" />
                      <p className="text-sm text-destructive">{ocrError}</p>
                      <p className="text-xs text-muted-foreground">
                        OCR text may not be available for older jobs
                      </p>
                    </div>
                  </div>
                ) : ocrText ? (
                  <div className="p-4">
                    <div className="prose prose-sm dark:prose-invert max-w-none">
                      <pre className="whitespace-pre-wrap text-xs font-mono bg-muted/50 rounded-lg p-4 overflow-x-auto">
                        {ocrText}
                      </pre>
                    </div>
                  </div>
                ) : (
                  <div className="h-full flex items-center justify-center py-12">
                    <div className="flex flex-col items-center gap-3 text-center px-4">
                      {job.status === "processing" || job.status === "pending" ? (
                        <>
                          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                          <p className="text-sm text-muted-foreground">
                            Processing document...
                          </p>
                        </>
                      ) : (
                        <>
                          <ScanText className="h-8 w-8 text-muted-foreground" />
                          <p className="text-sm text-muted-foreground">
                            No OCR text available
                          </p>
                        </>
                      )}
                    </div>
                  </div>
                )}
              </ScrollArea>
            )}
          </Card>

          {/* Right Card - PDF Preview */}
          <Card className="flex flex-col min-h-0 overflow-hidden">
            {/* Card Header */}
            <div className={cn("flex-none flex items-center justify-between border-b", compactView ? "px-2 py-1 h-10" : "px-4 py-3 h-14")}>
              <div className="flex items-center gap-2 min-w-0 flex-1">
                <FileTextIcon size={16} className="text-muted-foreground flex-shrink-0" />
                <span className="text-sm font-medium truncate" title={job.document_name}>
                  {job.document_name}
                </span>
              </div>
              <Badge
                variant="outline"
                className="border-violet-500 text-violet-600 bg-violet-50 dark:bg-violet-950/30 text-xs capitalize flex-shrink-0"
              >
                {job.doc_type || "document"}
              </Badge>
            </div>

            {/* Document Viewer (PDF or Excel) */}
            <div className="flex-1 min-h-0 relative">
              {documentFile ? (
                (() => {
                  const isExcel =
                    job?.document_name?.toLowerCase().endsWith(".xlsx") ||
                    job?.document_name?.toLowerCase().endsWith(".xls");
                  return isExcel ? (
                    <ExcelViewer file={documentFile} className="h-full w-full" />
                  ) : (
                    <PDFViewer
                      file={documentFile}
                      fileName={job.document_name}
                      highlights={pdfHighlights}
                      initialPage={currentPage || highlightPage || undefined}
                      onPageChange={setCurrentPage}
                      activeFieldId={selectedField || hoveredField}
                      drawMode={editMode && drawMode}
                      drawPreviewPolygon={
                        selectedField && pendingGeometry[selectedField]
                          ? pendingGeometry[selectedField].page === currentPage
                            ? pendingGeometry[selectedField].polygon
                            : null
                          : null
                      }
                      onBoxDrawn={handleBoxDrawn}
                    />
                  );
                })()
              ) : job?.has_stored_document ? (
                <div className="h-full flex items-center justify-center text-muted-foreground">
                  <div className="text-center">
                    <Loader2 className="h-10 w-10 mx-auto mb-2 animate-spin opacity-70" />
                    <p>Loading document…</p>
                  </div>
                </div>
              ) : (
                <div className="h-full flex items-center justify-center text-muted-foreground">
                  <div className="text-center">
                    {job.status === "processing" || job.status === "pending" ? (
                      <>
                        <Loader2 className="h-12 w-12 mx-auto mb-2 animate-spin opacity-50" />
                        <p>Loading document...</p>
                      </>
                    ) : (
                      <>
                        <FileText className="h-12 w-12 mx-auto mb-2 opacity-50" />
                        <p>Document preview not available</p>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>
          </Card>
        </div>
      )}

      {/* Save as Workflow Modal */}
      <SaveAsWorkflowModal
        open={workflowModalOpen}
        onOpenChange={setWorkflowModalOpen}
        job={job}
      />
    </div>
  );
}

// =============================================================================
// Legacy ExtractionResults component (for backwards compatibility)
// =============================================================================

interface ExtractionResultsProps {
  job: Job | null;
  parts: JobPart[];
  error: string | null;
  isExtracting: boolean;
}

export function ExtractionResults({
  job,
  parts,
  error,
  isExtracting,
}: ExtractionResultsProps) {
  // This is a wrapper that creates a Job-like object for the new component
  if (!job && !isExtracting && !error) {
    return (
      <Card className="h-full">
        <CardContent className="h-full flex flex-col items-center justify-center text-muted-foreground">
          <FileText className="h-12 w-12 mb-4" />
          <p className="text-lg font-medium">No Results Yet</p>
          <p className="text-sm text-center mt-2">
            Upload a document and start extraction to see results
          </p>
        </CardContent>
      </Card>
    );
  }

  if (error) {
    return (
      <Card className="border-destructive">
        <CardContent className="py-6">
          <div className="flex flex-col items-center text-destructive">
            <XCircle className="h-12 w-12 mb-4" />
            <p className="text-lg font-medium">Extraction Failed</p>
            <p className="text-sm text-center mt-2">{error}</p>
          </div>
        </CardContent>
      </Card>
    );
  }

  if (!job) {
    return (
      <Card className="h-full">
        <CardContent className="h-full flex items-center justify-center">
          <div className="animate-pulse text-muted-foreground">Processing...</div>
        </CardContent>
      </Card>
    );
  }

  // Use the new component with hideHeader since the main page has its own header
  return (
    <ExtractionResultsView
      job={{ ...job, parts }}
      documentFile={null}
      hideHeader={true}
    />
  );
}
