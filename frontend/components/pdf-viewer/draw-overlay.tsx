"use client";

/**
 * Drag-to-draw rectangle overlay for human bbox correction.
 * Emits normalized 0–1 page coordinates (axis-aligned quad).
 */

import { useCallback, useEffect, useRef, useState } from "react";

export interface DrawBoxResult {
  page: number;
  /** Normalized 0–1 quad TL, TR, BR, BL */
  polygon: number[][];
}

interface DrawOverlayProps {
  pageNumber: number;
  enabled: boolean;
  /** Preview polygon while editing (normalized 0–1) */
  previewPolygon?: number[][] | null;
  onDrawn: (result: DrawBoxResult) => void;
}

function toQuad(x0: number, y0: number, x1: number, y1: number): number[][] {
  const minX = Math.min(x0, x1);
  const maxX = Math.max(x0, x1);
  const minY = Math.min(y0, y1);
  const maxY = Math.max(y0, y1);
  return [
    [minX, minY],
    [maxX, minY],
    [maxX, maxY],
    [minX, maxY],
  ];
}

export function DrawOverlay({
  pageNumber,
  enabled,
  previewPolygon,
  onDrawn,
}: DrawOverlayProps) {
  const layerRef = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState<{
    x0: number;
    y0: number;
    x1: number;
    y1: number;
  } | null>(null);
  const drawingRef = useRef(false);

  const normFromEvent = useCallback((e: React.PointerEvent) => {
    const el = layerRef.current;
    if (!el) return { x: 0, y: 0 };
    const rect = el.getBoundingClientRect();
    return {
      x: Math.max(0, Math.min(1, (e.clientX - rect.left) / Math.max(rect.width, 1))),
      y: Math.max(0, Math.min(1, (e.clientY - rect.top) / Math.max(rect.height, 1))),
    };
  }, []);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!enabled) return;
      e.preventDefault();
      e.stopPropagation();
      layerRef.current?.setPointerCapture?.(e.pointerId);
      const p = normFromEvent(e);
      drawingRef.current = true;
      setDrag({ x0: p.x, y0: p.y, x1: p.x, y1: p.y });
    },
    [enabled, normFromEvent],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!drawingRef.current) return;
      e.preventDefault();
      const p = normFromEvent(e);
      setDrag((d) => (d ? { ...d, x1: p.x, y1: p.y } : d));
    },
    [normFromEvent],
  );

  const finish = useCallback(
    (e: React.PointerEvent) => {
      if (!drawingRef.current) return;
      drawingRef.current = false;
      const p = normFromEvent(e);
      setDrag((d) => {
        if (!d) return null;
        const w = Math.abs(p.x - d.x0);
        const h = Math.abs(p.y - d.y0);
        if (w > 0.005 && h > 0.005) {
          onDrawn({ page: pageNumber, polygon: toQuad(d.x0, d.y0, p.x, p.y) });
        }
        return null;
      });
    },
    [normFromEvent, pageNumber, onDrawn],
  );

  useEffect(() => {
    if (!enabled) {
      drawingRef.current = false;
      setDrag(null);
    }
  }, [enabled]);

  if (!enabled) return null;

  const activePoly = drag
    ? toQuad(drag.x0, drag.y0, drag.x1, drag.y1)
    : previewPolygon && previewPolygon.length >= 2
      ? previewPolygon
      : null;

  let boxStyle: React.CSSProperties | undefined;
  if (activePoly) {
    const xs = activePoly.map((pt) => pt[0]);
    const ys = activePoly.map((pt) => pt[1]);
    const minX = Math.min(...xs);
    const maxX = Math.max(...xs);
    const minY = Math.min(...ys);
    const maxY = Math.max(...ys);
    boxStyle = {
      position: "absolute",
      left: `${minX * 100}%`,
      top: `${minY * 100}%`,
      width: `${(maxX - minX) * 100}%`,
      height: `${(maxY - minY) * 100}%`,
      border: "2px dashed #2563eb",
      backgroundColor: "rgba(37, 99, 235, 0.15)",
      boxSizing: "border-box",
      pointerEvents: "none",
    };
  }

  return (
    <div
      ref={layerRef}
      className="pdf-draw-overlay"
      style={{
        position: "absolute",
        inset: 0,
        zIndex: 30,
        cursor: "crosshair",
        pointerEvents: "auto",
      }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={finish}
      onPointerCancel={finish}
    >
      {boxStyle && <div style={boxStyle} />}
    </div>
  );
}
