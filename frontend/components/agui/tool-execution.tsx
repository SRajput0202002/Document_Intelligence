"use client";

import { Circle, Loader2, XCircle } from "lucide-react";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { cn } from "@/lib/utils";

export interface ToolExecutionData {
  tool: string;
  field: string;
  status: "pending" | "running" | "completed" | "failed";
  timeMs?: number;
  confidence?: number;
  error?: string;
}

interface ToolExecutionProps {
  data: ToolExecutionData;
}

/**
 * Tool Execution Component
 *
 * Displays a single tool execution in the activity panel.
 */
export function ToolExecution({ data }: ToolExecutionProps) {
  const { tool, field, status, timeMs, confidence, error } = data;

  const getIcon = () => {
    switch (status) {
      case "completed":
        return <CircleCheckIcon size={14} className="text-green-500" />;
      case "running":
        return <Loader2 className="h-3.5 w-3.5 text-blue-500 animate-spin" />;
      case "failed":
        return <XCircle className="h-3.5 w-3.5 text-red-500" />;
      default:
        return <Circle className="h-3.5 w-3.5 text-muted-foreground" />;
    }
  };

  const formatToolName = (name: string): string => {
    const toolMap: Record<string, string> = {
      field_extractor: "Field",
      table_extractor: "Table",
      vertical_table_extractor: "Vertical Table",
      list_extractor: "List",
      nested_extractor: "Nested",
      entity_extractor: "Entity",
      form_field_extractor: "Form",
      chart_extractor: "Chart",
      image_analyzer: "Image",
    };
    return toolMap[name] || name.replace(/_/g, " ");
  };

  const formatFieldName = (name: string): string => {
    return name.replace(/_/g, " ");
  };

  return (
    <div
      className={cn(
        "flex items-center justify-between py-1.5 px-2 rounded text-sm",
        status === "completed" && "text-green-700 dark:text-green-400",
        status === "running" && "text-blue-700 dark:text-blue-400",
        status === "failed" && "text-red-700 dark:text-red-400",
        status === "pending" && "text-muted-foreground"
      )}
    >
      <div className="flex items-center gap-2">
        {getIcon()}
        <span className="text-xs text-muted-foreground">
          {formatToolName(tool)}
        </span>
        <span className="font-medium">{formatFieldName(field)}</span>
      </div>
      <div className="flex items-center gap-2 text-xs">
        {timeMs !== undefined && status === "completed" && (
          <span className="text-muted-foreground">{timeMs}ms</span>
        )}
        {confidence !== undefined && status === "completed" && (
          <span className="text-green-600 dark:text-green-400">
            {Math.round(confidence * 100)}%
          </span>
        )}
        {status === "running" && (
          <span className="animate-pulse">running...</span>
        )}
        {status === "failed" && error && (
          <span className="text-red-500 truncate max-w-[100px]" title={error}>
            {error}
          </span>
        )}
      </div>
    </div>
  );
}
