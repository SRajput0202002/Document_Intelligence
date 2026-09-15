"use client";

import { Circle, Loader2, XCircle } from "lucide-react";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { cn } from "@/lib/utils";

export interface AgentStepData {
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  timeMs?: number;
  details?: string;
}

interface AgentStepProps {
  data: AgentStepData;
}

/**
 * Agent Step Component
 *
 * Displays a single agent step in the activity panel.
 */
export function AgentStep({ data }: AgentStepProps) {
  const { name, status, timeMs, details } = data;

  const getIcon = () => {
    switch (status) {
      case "completed":
        return <CircleCheckIcon size={16} className="text-green-500" />;
      case "running":
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
      case "failed":
        return <XCircle className="h-4 w-4 text-red-500" />;
      default:
        return <Circle className="h-4 w-4 text-muted-foreground" />;
    }
  };

  const formatAgentName = (name: string): string => {
    const nameMap: Record<string, string> = {
      content_analyzer: "Content Analyzer",
      mapping: "Mapping Agent",
      extraction: "Extraction Agent",
      validation: "Validation Agent",
    };
    return nameMap[name] || name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
  };

  return (
    <div
      className={cn(
        "flex items-center justify-between p-2 rounded-md",
        status === "completed" && "bg-green-50 dark:bg-green-950/20",
        status === "running" && "bg-blue-50 dark:bg-blue-950/20",
        status === "failed" && "bg-red-50 dark:bg-red-950/20",
        status === "pending" && "bg-muted/50"
      )}
    >
      <div className="flex items-center gap-2">
        {getIcon()}
        <div>
          <span className="font-medium text-sm">{formatAgentName(name)}</span>
          {details && (
            <div className="text-xs text-muted-foreground">{details}</div>
          )}
        </div>
      </div>
      <div className="flex items-center gap-2">
        {timeMs !== undefined && status === "completed" && (
          <span className="text-xs text-muted-foreground">{timeMs}ms</span>
        )}
        {status === "running" && (
          <span className="text-xs text-blue-500">in progress</span>
        )}
      </div>
    </div>
  );
}
