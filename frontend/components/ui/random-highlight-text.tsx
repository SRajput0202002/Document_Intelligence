"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import { cn } from "@/lib/utils";

interface HighlightRow {
  words: string[];
  className?: string;
  dotClassName?: string;
}

interface RandomHighlightTextProps {
  rows: HighlightRow[];
  className?: string;
  highlightInterval?: number; // ms between highlights
  highlightDuration?: number; // how long each highlight lasts
  maxConcurrentHighlights?: number; // how many words can be highlighted at once
}

export function RandomHighlightText({
  rows,
  className,
  highlightInterval = 100,
  highlightDuration = 400,
  maxConcurrentHighlights = 3,
}: RandomHighlightTextProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const [isInView, setIsInView] = useState(false);
  const [highlightedIndices, setHighlightedIndices] = useState<Set<string>>(new Set());

  // Flatten all words with their indices for random selection
  const allWordIndices = rows.flatMap((row, rowIndex) =>
    row.words.map((_, wordIndex) => `${rowIndex}-${wordIndex}`)
  );

  // Intersection Observer to detect when in view
  useEffect(() => {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          setIsInView(entry.isIntersecting);
        });
      },
      {
        threshold: 0.3, // Trigger when 30% of the element is visible
        rootMargin: "0px",
      }
    );

    if (containerRef.current) {
      observer.observe(containerRef.current);
    }

    return () => {
      observer.disconnect();
    };
  }, []);

  // Random highlight effect
  const addRandomHighlight = useCallback(() => {
    if (allWordIndices.length === 0) return;

    // Pick a random word index
    const randomIndex = allWordIndices[Math.floor(Math.random() * allWordIndices.length)];

    setHighlightedIndices((prev) => {
      const next = new Set(prev);
      // If we've reached max concurrent highlights, don't add more
      if (next.size >= maxConcurrentHighlights) {
        return next;
      }
      next.add(randomIndex);
      return next;
    });

    // Remove highlight after duration
    setTimeout(() => {
      setHighlightedIndices((prev) => {
        const next = new Set(prev);
        next.delete(randomIndex);
        return next;
      });
    }, highlightDuration);
  }, [allWordIndices, highlightDuration, maxConcurrentHighlights]);

  // Start/stop highlight animation based on visibility
  useEffect(() => {
    if (!isInView) {
      setHighlightedIndices(new Set());
      return;
    }

    const intervalId = setInterval(addRandomHighlight, highlightInterval);

    return () => {
      clearInterval(intervalId);
    };
  }, [isInView, addRandomHighlight, highlightInterval]);

  return (
    <div ref={containerRef} className={cn("space-y-2", className)}>
      {rows.map((row, rowIndex) => (
        <div
          key={rowIndex}
          className={cn(
            "flex items-center justify-center gap-2 flex-wrap",
            row.className
          )}
        >
          {row.words.map((word, wordIndex) => {
            const isHighlighted = highlightedIndices.has(`${rowIndex}-${wordIndex}`);
            const isLastWord = wordIndex === row.words.length - 1;

            return (
              <span key={wordIndex} className="contents">
                <span
                  className="inline-block whitespace-nowrap"
                  style={{
                    color: isHighlighted ? "hsl(var(--primary))" : undefined,
                    textShadow: isHighlighted ? "0 0 10px hsl(var(--primary) / 0.6)" : "none",
                    transition: "color 150ms ease-out, text-shadow 150ms ease-out",
                  }}
                >
                  {word}
                </span>
                {!isLastWord && (
                  <span className={cn("rounded-full", row.dotClassName)} />
                )}
              </span>
            );
          })}
        </div>
      ))}
    </div>
  );
}
