"use client";

import { useState, useCallback } from "react";
import { Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface CopyButtonProps {
  value: string;
  className?: string;
  variant?: "ghost" | "outline" | "default" | "secondary";
  size?: "default" | "sm" | "lg" | "icon";
  iconSize?: number;
  onCopy?: () => void;
}

export function CopyButton({
  value,
  className,
  variant = "ghost",
  size = "icon",
  iconSize = 16,
  onCopy,
}: CopyButtonProps) {
  const [state, setState] = useState<"idle" | "loading" | "success">("idle");

  const handleCopy = useCallback(async () => {
    setState("loading");

    // Small delay for visual feedback
    await new Promise((resolve) => setTimeout(resolve, 300));

    try {
      await navigator.clipboard.writeText(value);
      setState("success");
      onCopy?.();

      // Reset after 1.5 seconds
      setTimeout(() => {
        setState("idle");
      }, 1500);
    } catch (err) {
      console.error("Failed to copy:", err);
      setState("idle");
    }
  }, [value, onCopy]);

  const iconStyle = { width: iconSize, height: iconSize };

  return (
    <Button
      variant={variant}
      size={size}
      className={cn(
        "relative transition-all duration-200",
        state === "success" && "bg-green-500 hover:bg-green-500 text-white rounded-full !opacity-100",
        state === "loading" && "bg-green-500 hover:bg-green-500 rounded-full !opacity-100",
        className
      )}
      onClick={handleCopy}
      disabled={state === "loading"}
    >
      {state === "idle" && <Copy style={iconStyle} />}
      {state === "loading" && (
        <svg style={iconStyle} className="animate-spin" viewBox="0 0 24 24" fill="none">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="white"
            strokeWidth="3"
          />
          <path
            className="opacity-100"
            fill="white"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"
          />
        </svg>
      )}
      {state === "success" && (
        <svg
          style={iconStyle}
          className="animate-scale-in"
          viewBox="0 0 24 24"
          fill="none"
          stroke="white"
          strokeWidth="2.5"
          strokeLinecap="round"
          strokeLinejoin="round"
        >
          <polyline
            points="4 12 9 17 20 6"
            className="animate-draw-check"
            style={{ strokeDasharray: 24 }}
          />
        </svg>
      )}
    </Button>
  );
}
