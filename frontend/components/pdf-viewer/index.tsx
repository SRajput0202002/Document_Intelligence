"use client";

import { useState, useEffect, useCallback, useRef, useMemo } from "react";
import { Document, Page, pdfjs } from "react-pdf";
import {
  ZoomIn,
  ZoomOut,
  RotateCw,
  LayoutGrid,
  Download,
  Loader2,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";
import { XIcon } from "@/components/ui/x";
import { cn } from "@/lib/utils";
import { HighlightOverlay, HighlightConfig } from "./highlight-overlay";
import { DrawOverlay, type DrawBoxResult } from "./draw-overlay";
import "react-pdf/dist/Page/AnnotationLayer.css";
import "react-pdf/dist/Page/TextLayer.css";

// Set up PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface PDFViewerProps {
  file: File | Blob | string | null;
  fileName?: string;
  className?: string;
  showToolbar?: boolean;
  showThumbnails?: boolean;
  /** Highlight configurations for text matching */
  highlights?: HighlightConfig[];
  /** Callback when page changes */
  onPageChange?: (page: number) => void;
  /** Initial page to display (1-indexed) */
  initialPage?: number;
  /** Whether to auto-scroll to the first highlight when it becomes visible */
  scrollToHighlight?: boolean;
  /** Active field identifier for scroll tracking - triggers scroll when changed */
  activeFieldId?: string | null;
  /** Enable drag-to-draw bbox correction on the PDF */
  drawMode?: boolean;
  /** Pending preview polygon (normalized 0–1) for the active field on the current page */
  drawPreviewPolygon?: number[][] | null;
  /** Fired when user finishes drawing a box */
  onBoxDrawn?: (result: DrawBoxResult) => void;
  /**
   * Continuous scroll mode: stack pages vertically so the user can scroll
   * through them (used for multi-page segment preview).
   */
  continuous?: boolean;
  /** Inclusive 1-indexed start page when limiting the view to a range */
  pageStart?: number;
  /** Inclusive 1-indexed end page when limiting the view to a range */
  pageEnd?: number;
}

export function PDFViewer({
  file,
  fileName,
  className,
  highlights,
  onPageChange,
  initialPage,
  scrollToHighlight = true,
  activeFieldId,
  drawMode = false,
  drawPreviewPolygon = null,
  onBoxDrawn,
  continuous = false,
  pageStart,
  pageEnd,
}: PDFViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [scale, setScale] = useState<number>(1);
  const [rotation, setRotation] = useState<number>(0);
  const [pdfFile, setPdfFile] = useState<string | File | Blob | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [showThumbnailStrip, setShowThumbnailStrip] = useState(false);
  const [pageWidth, setPageWidth] = useState<number>(600);
  const containerRef = useRef<HTMLDivElement>(null);
  const thumbnailStripRef = useRef<HTMLDivElement>(null);
  const thumbnailButtonRef = useRef<HTMLButtonElement>(null);
  const activeThumbnailRef = useRef<HTMLButtonElement>(null);
  const pageContainerRef = useRef<HTMLDivElement>(null);
  const scrollContainerRef = useRef<HTMLDivElement>(null);
  const continuousPageRefs = useRef<Map<number, HTMLDivElement>>(new Map());
  const [pageElement, setPageElement] = useState<HTMLElement | null>(null);
  const lastScrolledHighlightRef = useRef<string | null>(null);
  const suppressScrollSyncRef = useRef(false);

  /** Polygon highlights from OCR include a 1-based page; only draw them on the matching visible page. */
  const highlightsForCurrentPage = useMemo(() => {
    if (!highlights?.length) return [];
    return highlights.filter((h) => {
      if (h.polygon && h.polygon.length >= 3 && h.page != null) {
        return h.page === currentPage;
      }
      return true;
    });
  }, [highlights, currentPage]);

  const effectivePageStart = useMemo(() => {
    if (!numPages) return 1;
    const start = pageStart != null ? Math.max(1, Math.min(pageStart, numPages)) : 1;
    return start;
  }, [pageStart, numPages]);

  const effectivePageEnd = useMemo(() => {
    if (!numPages) return 1;
    const end = pageEnd != null ? Math.max(1, Math.min(pageEnd, numPages)) : numPages;
    return Math.max(effectivePageStart, end);
  }, [pageEnd, numPages, effectivePageStart]);

  const continuousPages = useMemo(() => {
    if (!continuous || !numPages) return [] as number[];
    const pages: number[] = [];
    for (let p = effectivePageStart; p <= effectivePageEnd; p++) pages.push(p);
    return pages;
  }, [continuous, numPages, effectivePageStart, effectivePageEnd]);

  // Drag-to-pan state
  const [isDragging, setIsDragging] = useState(false);
  const dragStartRef = useRef<{ x: number; y: number; scrollLeft: number; scrollTop: number } | null>(null);

  // Update page element reference when page renders
  const onPageRenderSuccess = useCallback(() => {
    if (pageContainerRef.current) {
      const pageEl = pageContainerRef.current.querySelector('.react-pdf__Page');
      setPageElement(pageEl as HTMLElement | null);
    }
  }, []);

  const scrollContinuousPageIntoView = useCallback((page: number, behavior: ScrollBehavior = "smooth") => {
    const el = continuousPageRefs.current.get(page);
    if (!el || !scrollContainerRef.current) return;
    suppressScrollSyncRef.current = true;
    el.scrollIntoView({ behavior, block: "start" });
    window.setTimeout(() => {
      suppressScrollSyncRef.current = false;
    }, behavior === "smooth" ? 400 : 50);
  }, []);

  // Handle initialPage / range changes
  useEffect(() => {
    if (!numPages) return;
    const preferred = initialPage ?? effectivePageStart;
    const clamped = Math.max(effectivePageStart, Math.min(preferred, effectivePageEnd));
    setCurrentPage(clamped);
    if (continuous) {
      // Wait a tick for pages to mount
      const t = window.setTimeout(() => scrollContinuousPageIntoView(clamped, "auto"), 50);
      return () => window.clearTimeout(t);
    }
  }, [
    initialPage,
    numPages,
    effectivePageStart,
    effectivePageEnd,
    continuous,
    scrollContinuousPageIntoView,
  ]);

  // Keep current page inside the active range
  useEffect(() => {
    if (!numPages) return;
    if (currentPage < effectivePageStart || currentPage > effectivePageEnd) {
      setCurrentPage(effectivePageStart);
    }
  }, [currentPage, effectivePageStart, effectivePageEnd, numPages]);

  // Continuous mode: track which page is most visible while scrolling
  useEffect(() => {
    if (!continuous || !scrollContainerRef.current || continuousPages.length === 0) return;

    const root = scrollContainerRef.current;
    const ratios = new Map<number, number>();

    const observer = new IntersectionObserver(
      (entries) => {
        if (suppressScrollSyncRef.current) return;
        for (const entry of entries) {
          const pageAttr = (entry.target as HTMLElement).dataset.pageNumber;
          if (!pageAttr) continue;
          ratios.set(Number(pageAttr), entry.intersectionRatio);
        }
        let bestPage = currentPage;
        let bestRatio = -1;
        ratios.forEach((ratio, page) => {
          if (ratio > bestRatio) {
            bestRatio = ratio;
            bestPage = page;
          }
        });
        if (bestRatio > 0 && bestPage !== currentPage) {
          setCurrentPage(bestPage);
          onPageChange?.(bestPage);
        }
      },
      { root, threshold: [0.25, 0.5, 0.75] }
    );

    continuousPages.forEach((page) => {
      const el = continuousPageRefs.current.get(page);
      if (el) observer.observe(el);
    });

    return () => observer.disconnect();
  }, [continuous, continuousPages, currentPage, onPageChange]);

  // Reset page element when page changes or scale changes (so highlights recalculate)
  useEffect(() => {
    if (continuous) return;
    setPageElement(null);
    // Small delay then re-fetch the page element
    const timer = setTimeout(() => {
      if (pageContainerRef.current) {
        const pageEl = pageContainerRef.current.querySelector('.react-pdf__Page');
        setPageElement(pageEl as HTMLElement | null);
      }
    }, 100);
    return () => clearTimeout(timer);
  }, [currentPage, scale, continuous]);

  useEffect(() => {
    if (file) {
      setPdfFile(file);
      setLoadError(null);
    }
  }, [file]);

  // Responsive page width based on container size
  useEffect(() => {
    if (!containerRef.current) return;

    const updateWidth = () => {
      if (containerRef.current) {
        // Get container width minus padding for controls (80px for right side controls)
        const containerWidth = containerRef.current.clientWidth - 100;
        // Clamp between 400 and 1200px for reasonable PDF display
        const newWidth = Math.max(400, Math.min(containerWidth, 1200));
        setPageWidth(newWidth);
      }
    };

    // Initial measurement
    updateWidth();

    // Observe container size changes
    const resizeObserver = new ResizeObserver(updateWidth);
    resizeObserver.observe(containerRef.current);

    return () => resizeObserver.disconnect();
  }, []);

  // Scroll to active thumbnail when strip opens or page changes
  useEffect(() => {
    if (showThumbnailStrip && activeThumbnailRef.current) {
      activeThumbnailRef.current.scrollIntoView({
        behavior: "smooth",
        block: "nearest",
        inline: "center",
      });
    }
  }, [showThumbnailStrip, currentPage]);

  // Handle scroll to highlight when boxes are ready
  const handleHighlightBoxesReady = useCallback((boxes: Array<{ x: number; y: number; width: number; height: number }>) => {
    if (!scrollToHighlight || boxes.length === 0 || !scrollContainerRef.current || !pageContainerRef.current) {
      return;
    }

    // Use activeFieldId for tracking if available, otherwise use highlight text
    const scrollKey = activeFieldId || highlights?.map(h => h.text).join('|') || '';
    if (!scrollKey || scrollKey === lastScrolledHighlightRef.current) {
      return;
    }
    lastScrolledHighlightRef.current = scrollKey;

    // Get the first highlight box
    const firstBox = boxes[0];
    const container = scrollContainerRef.current;
    const pageContainer = pageContainerRef.current;

    // Get the page container's position relative to scroll container
    const pageRect = pageContainer.getBoundingClientRect();
    const containerRect = container.getBoundingClientRect();

    // Calculate the highlight's position in the scroll container's coordinate system
    // Account for scale and current scroll position
    const highlightTop = (pageRect.top - containerRect.top) + (firstBox.y * scale) + container.scrollTop;
    const highlightLeft = (pageRect.left - containerRect.left) + (firstBox.x * scale) + container.scrollLeft;

    // Calculate target scroll position to center the highlight in view
    const targetScrollTop = highlightTop - (containerRect.height / 2) + ((firstBox.height * scale) / 2);
    const targetScrollLeft = highlightLeft - (containerRect.width / 2) + ((firstBox.width * scale) / 2);

    // Smooth scroll to the highlight
    container.scrollTo({
      top: Math.max(0, targetScrollTop),
      left: Math.max(0, targetScrollLeft),
      behavior: 'smooth',
    });
  }, [scrollToHighlight, highlights, scale, activeFieldId]);

  // Reset scroll tracking when active field changes
  useEffect(() => {
    if (activeFieldId !== undefined) {
      lastScrolledHighlightRef.current = null;
    }
  }, [activeFieldId]);

  const onDocumentLoadSuccess = useCallback(({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setIsLoading(false);
    setLoadError(null);
  }, []);

  const onDocumentLoadError = useCallback((error: Error) => {
    console.error("PDF load error:", error);
    setIsLoading(false);
    setLoadError(error.message || "Failed to load PDF file");
  }, []);

  const zoomIn = useCallback(() => setScale((s) => Math.min(s + 0.25, 3)), []);
  const zoomOut = useCallback(() => setScale((s) => Math.max(s - 0.25, 0.5)), []);
  const rotate = () => setRotation((r) => (r + 90) % 360);
  const handleDownload = useCallback(() => {
    if (!pdfFile) return;

    let href: string;
    let downloadFileName = "document.pdf";
    let shouldRevoke = false;

    if (typeof pdfFile === "string") {
      href = pdfFile;
    } else {
      href = URL.createObjectURL(pdfFile);
      shouldRevoke = true;
      if (pdfFile instanceof File && pdfFile.name) {
        downloadFileName = pdfFile.name;
      }
    }

    if (fileName?.trim()) {
      downloadFileName = fileName.trim();
    } else if (typeof pdfFile === "string") {
      // Try extracting a useful filename from URL/blob paths before falling back.
      try {
        const parsed = new URL(pdfFile, window.location.origin);
        const lastSegment = parsed.pathname.split("/").filter(Boolean).pop();
        if (lastSegment) {
          downloadFileName = decodeURIComponent(lastSegment);
        }
      } catch {
        const lastSegment = pdfFile.split("/").filter(Boolean).pop();
        if (lastSegment) {
          downloadFileName = decodeURIComponent(lastSegment.split("?")[0].split("#")[0]);
        }
      }
    }

    const anchor = document.createElement("a");
    anchor.href = href;
    anchor.download = downloadFileName;
    anchor.target = "_blank";
    anchor.rel = "noopener noreferrer";
    document.body.appendChild(anchor);
    anchor.click();
    document.body.removeChild(anchor);

    if (shouldRevoke) {
      URL.revokeObjectURL(href);
    }
  }, [pdfFile, fileName]);
  const goToPrev = () => {
    const newPage = Math.max(currentPage - 1, effectivePageStart);
    setCurrentPage(newPage);
    onPageChange?.(newPage);
    if (continuous) scrollContinuousPageIntoView(newPage);
  };
  const goToNext = () => {
    const newPage = Math.min(currentPage + 1, effectivePageEnd);
    setCurrentPage(newPage);
    onPageChange?.(newPage);
    if (continuous) scrollContinuousPageIntoView(newPage);
  };
  const goToPage = (page: number) => {
    const newPage = Math.max(effectivePageStart, Math.min(page, effectivePageEnd));
    setCurrentPage(newPage);
    onPageChange?.(newPage);
    if (continuous) scrollContinuousPageIntoView(newPage);
  };

  // Drag-to-pan handlers
  const handleMouseDown = useCallback((e: React.MouseEvent) => {
    // Only enable drag when zoomed in (scale > 1) and using left mouse button
    if (drawMode || scale <= 1 || e.button !== 0) return;

    const container = scrollContainerRef.current;
    if (!container) return;

    // Don't start drag if clicking on buttons or interactive elements
    const target = e.target as HTMLElement;
    if (target.closest('button') || target.closest('a')) return;

    setIsDragging(true);
    dragStartRef.current = {
      x: e.clientX,
      y: e.clientY,
      scrollLeft: container.scrollLeft,
      scrollTop: container.scrollTop,
    };

    // Prevent text selection while dragging
    e.preventDefault();
  }, [scale, drawMode]);

  const handleMouseMove = useCallback((e: React.MouseEvent) => {
    if (!isDragging || !dragStartRef.current || !scrollContainerRef.current) return;

    const container = scrollContainerRef.current;
    const dx = e.clientX - dragStartRef.current.x;
    const dy = e.clientY - dragStartRef.current.y;

    container.scrollLeft = dragStartRef.current.scrollLeft - dx;
    container.scrollTop = dragStartRef.current.scrollTop - dy;
  }, [isDragging]);

  const handleMouseUp = useCallback(() => {
    setIsDragging(false);
    dragStartRef.current = null;
  }, []);

  const handleMouseLeave = useCallback(() => {
    if (isDragging) {
      setIsDragging(false);
      dragStartRef.current = null;
    }
  }, [isDragging]);

  // Ctrl/Cmd + scroll wheel zoom - using native event for proper preventDefault
  useEffect(() => {
    const container = scrollContainerRef.current;
    if (!container) return;

    let lastZoomTime = 0;
    const ZOOM_THROTTLE_MS = 50; // Minimum ms between zoom steps
    const ZOOM_STEP = 0.15; // Consistent zoom increment

    const handleWheel = (e: WheelEvent) => {
      // Check if Ctrl (Windows/Linux) or Meta/Cmd (Mac) is pressed
      if (e.ctrlKey || e.metaKey) {
        e.preventDefault();
        e.stopPropagation();

        // Throttle zoom to prevent runaway zooming
        const now = Date.now();
        if (now - lastZoomTime < ZOOM_THROTTLE_MS) {
          return;
        }
        lastZoomTime = now;

        // Normalize deltaY - just check direction, ignore magnitude
        // This prevents trackpad gestures from causing huge zoom jumps
        if (e.deltaY < 0) {
          // Scroll up = zoom in
          setScale((s) => Math.min(s + ZOOM_STEP, 3));
        } else if (e.deltaY > 0) {
          // Scroll down = zoom out
          setScale((s) => Math.max(s - ZOOM_STEP, 0.5));
        }
      }
    };

    // Use { passive: false } to allow preventDefault
    container.addEventListener('wheel', handleWheel, { passive: false });

    return () => {
      container.removeEventListener('wheel', handleWheel);
    };
  }, []);

  if (!file) {
    return (
      <div className={cn("flex items-center justify-center h-full bg-neutral-50", className)}>
        <p className="text-sm text-neutral-400">No document selected</p>
      </div>
    );
  }

  return (
    <div ref={containerRef} className={cn("relative flex flex-col h-full w-full bg-neutral-100", className)}>
      {/* Scrollable PDF content - takes full height */}
      <div
        ref={scrollContainerRef}
        className={cn(
          "flex-1 overflow-auto pdf-thin-scrollbar",
          scale > 1 && !isDragging && "cursor-grab",
          isDragging && "cursor-grabbing select-none"
        )}
        onMouseDown={handleMouseDown}
        onMouseMove={handleMouseMove}
        onMouseUp={handleMouseUp}
        onMouseLeave={handleMouseLeave}
      >
        {/* PDF container with inline-block for proper scrolling */}
        <div
          className="min-h-full"
          style={{
            // Use text-align center for inline-block centering (allows left scrolling)
            textAlign: 'center',
            padding: '24px',
          }}
        >
          {pdfFile && (
            <Document
              file={pdfFile}
              onLoadSuccess={onDocumentLoadSuccess}
              onLoadError={onDocumentLoadError}
              loading={
                <div className="flex items-center justify-center h-64">
                  <Loader2 className="w-6 h-6 animate-spin text-neutral-400" />
                </div>
              }
            >
              {continuous ? (
                <div
                  className="inline-flex flex-col items-center gap-4"
                  style={{
                    padding: scale > 1
                      ? `${(scale - 1) * pageWidth * 0.35}px ${(scale - 1) * pageWidth * 0.5}px`
                      : "0",
                  }}
                >
                  {continuousPages.map((pageNumber) => (
                    <div
                      key={pageNumber}
                      data-page-number={pageNumber}
                      ref={(el) => {
                        if (el) continuousPageRefs.current.set(pageNumber, el);
                        else continuousPageRefs.current.delete(pageNumber);
                      }}
                      className="shadow-lg bg-white rounded overflow-hidden"
                      style={{
                        transform: `scale(${scale}) rotate(${rotation}deg)`,
                        transformOrigin: "center top",
                      }}
                    >
                      <Page
                        pageNumber={pageNumber}
                        width={pageWidth}
                        renderTextLayer={true}
                        renderAnnotationLayer={true}
                        loading={
                          <div className="flex items-center justify-center h-64 w-[600px]">
                            <Loader2 className="w-6 h-6 animate-spin text-neutral-400" />
                          </div>
                        }
                      />
                    </div>
                  ))}
                </div>
              ) : (
              /* Wrapper sized for scaled content with padding for center-origin overflow */
              <div
                style={{
                  display: 'inline-block',
                  textAlign: 'left',
                  // Add padding to account for center-origin scaling overflow
                  // When scaled from center, content extends by (scale-1)*size/2 on each side
                  padding: scale > 1
                    ? `${(scale - 1) * pageWidth * 0.7}px ${(scale - 1) * pageWidth * 0.5}px`
                    : '0',
                }}
              >
                <div
                  ref={pageContainerRef}
                  className="shadow-lg bg-white rounded pdf-page-container"
                  style={{
                    transform: `scale(${scale}) rotate(${rotation}deg)`,
                    transformOrigin: "center center",
                  }}
                >
                <Page
                  pageNumber={currentPage}
                  width={pageWidth}
                  renderTextLayer={true}
                  renderAnnotationLayer={true}
                  onRenderTextLayerSuccess={onPageRenderSuccess}
                  loading={
                    <div className="flex items-center justify-center h-64 w-[600px]">
                      <Loader2 className="w-6 h-6 animate-spin text-neutral-400" />
                    </div>
                  }
                />
                {/* Highlight overlay positioned on top of the PDF page */}
                {highlightsForCurrentPage.length > 0 && (
                  <HighlightOverlay
                    pageElement={pageElement}
                    highlights={highlightsForCurrentPage}
                    scale={scale}
                    onHighlightBoxesReady={handleHighlightBoxesReady}
                  />
                )}
                {drawMode && onBoxDrawn && (
                  <DrawOverlay
                    pageNumber={currentPage}
                    enabled={drawMode}
                    previewPolygon={drawPreviewPolygon}
                    onDrawn={onBoxDrawn}
                  />
                )}
              </div>
              </div>
              )}
            </Document>
          )}

          {isLoading && !pdfFile && (
            <div className="flex items-center justify-center h-64">
              <Loader2 className="w-6 h-6 animate-spin text-neutral-400" />
            </div>
          )}

          {loadError && (
            <div className="flex flex-col items-center justify-center h-64 text-neutral-500">
              <svg className="w-12 h-12 mb-3 text-neutral-300" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
              </svg>
              <p className="text-sm font-medium">Failed to load PDF file.</p>
              <p className="text-xs text-neutral-400 mt-1 max-w-xs text-center">{loadError}</p>
            </div>
          )}
        </div>
      </div>

      {/* Floating pagination at bottom-center */}
      {numPages > 0 && (
        <div className={cn(
          "absolute left-1/2 -translate-x-1/2 z-40 transition-all duration-300",
          showThumbnailStrip ? "bottom-[180px]" : "bottom-4"
        )}>
          <div className="flex items-center gap-0.5 bg-white rounded-full shadow-md border border-neutral-200/80 px-1.5 py-0.5">
            <button
              onClick={goToPrev}
              disabled={currentPage <= effectivePageStart}
              className={cn(
                "p-0.5 rounded-full transition-colors",
                currentPage <= effectivePageStart
                  ? "text-neutral-300 cursor-not-allowed"
                  : "text-neutral-600 hover:bg-neutral-100"
              )}
            >
              <ChevronLeft className="w-3.5 h-3.5" />
            </button>
            <span className="text-xs font-medium text-neutral-700 min-w-[40px] text-center">
              {currentPage}/{effectivePageEnd}
            </span>
            <button
              onClick={goToNext}
              disabled={currentPage >= effectivePageEnd}
              className={cn(
                "p-0.5 rounded-full transition-colors",
                currentPage >= effectivePageEnd
                  ? "text-neutral-300 cursor-not-allowed"
                  : "text-neutral-600 hover:bg-neutral-100"
              )}
            >
              <ChevronRight className="w-3.5 h-3.5" />
            </button>
          </div>
        </div>
      )}

      {/* Floating buttons at bottom-right */}
      <div className={cn(
        "absolute right-4 z-40 flex flex-col gap-1.5 transition-all duration-300",
        showThumbnailStrip ? "bottom-[180px]" : "bottom-4"
      )}>
        {/* Download */}
        <button
          onClick={handleDownload}
          disabled={!pdfFile}
          className={cn(
            "w-9 h-9 sm:w-8 sm:h-8 rounded-full bg-white shadow-lg border border-neutral-200 flex items-center justify-center transition-colors",
            !pdfFile
              ? "text-neutral-300 cursor-not-allowed"
              : "text-neutral-600 hover:bg-neutral-50"
          )}
          title="Download PDF"
          aria-label="Download PDF"
        >
          <Download className="w-4 h-4" />
        </button>

        {/* Zoom In */}
        <button
          onClick={zoomIn}
          disabled={scale >= 3}
          className={cn(
            "w-9 h-9 sm:w-8 sm:h-8 rounded-full bg-white shadow-lg border border-neutral-200 flex items-center justify-center transition-colors",
            scale >= 3
              ? "text-neutral-300 cursor-not-allowed"
              : "text-neutral-600 hover:bg-neutral-50"
          )}
          title="Zoom in"
        >
          <ZoomIn className="w-4 h-4" />
        </button>

        {/* Zoom Out */}
        <button
          onClick={zoomOut}
          disabled={scale <= 0.5}
          className={cn(
            "w-9 h-9 sm:w-8 sm:h-8 rounded-full bg-white shadow-lg border border-neutral-200 flex items-center justify-center transition-colors",
            scale <= 0.5
              ? "text-neutral-300 cursor-not-allowed"
              : "text-neutral-600 hover:bg-neutral-50"
          )}
          title="Zoom out"
        >
          <ZoomOut className="w-4 h-4" />
        </button>

        {/* Rotate */}
        <button
          onClick={rotate}
          className="w-9 h-9 sm:w-8 sm:h-8 rounded-full bg-white shadow-lg border border-neutral-200 flex items-center justify-center text-neutral-600 hover:bg-neutral-50 transition-colors"
          title="Rotate"
        >
          <RotateCw className="w-4 h-4" />
        </button>

        {/* Thumbnails Toggle */}
        <button
          ref={thumbnailButtonRef}
          onClick={() => setShowThumbnailStrip(!showThumbnailStrip)}
          disabled={numPages === 0}
          className={cn(
            "w-9 h-9 sm:w-8 sm:h-8 rounded-full bg-white shadow-lg border border-neutral-200 flex items-center justify-center transition-colors",
            numPages === 0
              ? "text-neutral-300 cursor-not-allowed"
              : showThumbnailStrip
              ? "bg-neutral-800 text-white border-neutral-800"
              : "text-neutral-600 hover:bg-neutral-50"
          )}
          title="Thumbnails"
        >
          <LayoutGrid className="w-4 h-4" />
        </button>
      </div>

      {/* Horizontal Thumbnail Strip at Bottom */}
      {showThumbnailStrip && numPages > 0 && pdfFile && (
        <div
          ref={thumbnailStripRef}
          className="absolute bottom-0 left-0 right-0 z-50 bg-white/80 backdrop-blur-sm border-t border-neutral-200 shadow-[0_-4px_20px_rgba(0,0,0,0.1)]"
        >
          {/* Close button */}
          <button
            onClick={() => setShowThumbnailStrip(false)}
            className="absolute top-2 right-3 z-10 p-1 rounded-full bg-neutral-100 hover:bg-neutral-200 text-neutral-500 hover:text-neutral-700 transition-colors"
          >
            <XIcon size={16} />
          </button>

          {/* Scrollable thumbnail container */}
          <div className="overflow-x-auto overflow-y-hidden thumbnail-strip-scrollbar">
            <Document file={pdfFile} loading={null}>
              <div className="flex items-start gap-3 px-4 py-3">
                {(continuous && continuousPages.length > 0
                  ? continuousPages
                  : Array.from({ length: numPages }, (_, i) => i + 1)
                ).map((pageNumber) => {
                  const isSelected = currentPage === pageNumber;
                  return (
                    <button
                      key={pageNumber}
                      ref={isSelected ? activeThumbnailRef : null}
                      onClick={() => goToPage(pageNumber)}
                      className={cn(
                        "flex-shrink-0 flex flex-col items-center gap-2 p-2 rounded-lg transition-all",
                        isSelected
                          ? "bg-neutral-50"
                          : "hover:bg-neutral-50"
                      )}
                    >
                      <div
                        className={cn(
                          "rounded-lg overflow-hidden bg-white transition-all",
                          isSelected
                            ? "ring-2 ring-neutral-900 ring-offset-2 shadow-lg"
                            : "shadow-md border border-neutral-200 hover:shadow-lg"
                        )}
                      >
                        <Page
                          pageNumber={pageNumber}
                          width={100}
                          renderTextLayer={false}
                          renderAnnotationLayer={false}
                        />
                      </div>
                      <span
                        className={cn(
                          "text-xs tabular-nums",
                          isSelected
                            ? "font-bold text-neutral-900"
                            : "font-medium text-neutral-500"
                        )}
                      >
                        {pageNumber}
                      </span>
                    </button>
                  );
                })}
              </div>
            </Document>
          </div>
        </div>
      )}

      {/* Custom scrollbar styles */}
      <style jsx global>{`
        .pdf-thin-scrollbar::-webkit-scrollbar {
          width: 8px;
          height: 8px;
        }
        .pdf-thin-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .pdf-thin-scrollbar::-webkit-scrollbar-thumb {
          background-color: rgba(0, 0, 0, 0.15);
          border-radius: 4px;
        }
        .pdf-thin-scrollbar::-webkit-scrollbar-thumb:hover {
          background-color: rgba(0, 0, 0, 0.25);
        }
        .pdf-thin-scrollbar {
          scrollbar-width: thin;
          scrollbar-color: rgba(0, 0, 0, 0.15) transparent;
        }

        .thumbnail-strip-scrollbar::-webkit-scrollbar {
          height: 6px;
        }
        .thumbnail-strip-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .thumbnail-strip-scrollbar::-webkit-scrollbar-thumb {
          background-color: rgba(0, 0, 0, 0.2);
          border-radius: 3px;
        }
        .thumbnail-strip-scrollbar::-webkit-scrollbar-thumb:hover {
          background-color: rgba(0, 0, 0, 0.3);
        }
        .thumbnail-strip-scrollbar {
          scrollbar-width: thin;
          scrollbar-color: rgba(0, 0, 0, 0.2) transparent;
        }
      `}</style>
    </div>
  );
}

export default PDFViewer;

// Re-export types for convenience
export type { HighlightConfig } from "./highlight-overlay";
export { HIGHLIGHT_COLORS } from "./highlight-overlay";
