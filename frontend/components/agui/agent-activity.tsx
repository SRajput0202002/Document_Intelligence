"use client";

import { useState, useEffect, useCallback } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { Activity, Loader2 } from "lucide-react";
import { AgentStep, AgentStepData } from "./agent-step";
import { ToolExecution, ToolExecutionData } from "./tool-execution";

/**
 * Agent event types from WebSocket
 */
export interface AgentEvent {
  type: string;
  job_id?: string;
  payload?: {
    agent?: string;
    tool?: string;
    field?: string;
    step?: string;
    success?: boolean;
    time_ms?: number;
    confidence?: number;
    error?: string;
    timestamp?: number;
    total_fields?: number;
    parallel_count?: number;
    sequential_count?: number;
    region_count?: number;
    region_types?: Record<string, number>;
    pages_analyzed?: number;
    tools_used?: string[];
    completed?: number;
    total?: number;
    current_field?: string;
    progress?: number;
    [key: string]: unknown;
  };
}

interface AgentActivityProps {
  isActive: boolean;
  events: AgentEvent[];
  className?: string;
}

interface AgentState {
  name: string;
  status: "pending" | "running" | "completed" | "failed";
  startTime?: number;
  endTime?: number;
  metadata?: Record<string, unknown>;
}

interface ToolState {
  name: string;
  field: string;
  status: "pending" | "running" | "completed" | "failed";
  startTime?: number;
  endTime?: number;
  timeMs?: number;
  confidence?: number;
  error?: string;
}

/**
 * Agent Activity Panel
 *
 * Real-time visualization of multi-agent extraction progress.
 * Shows agent steps, tool executions, and overall progress.
 */
export function AgentActivity({
  isActive,
  events,
  className,
}: AgentActivityProps) {
  const [agents, setAgents] = useState<Map<string, AgentState>>(new Map());
  const [tools, setTools] = useState<ToolState[]>([]);
  const [extractionProgress, setExtractionProgress] = useState({
    completed: 0,
    total: 0,
  });

  // Process incoming events
  useEffect(() => {
    if (events.length === 0) return;

    const latestEvent = events[events.length - 1];
    const { type, payload } = latestEvent;

    if (!payload) return;

    switch (type) {
      case "agent_started": {
        const agentName = payload.agent as string;
        setAgents((prev) => {
          const newMap = new Map(prev);
          newMap.set(agentName, {
            name: agentName,
            status: "running",
            startTime: payload.timestamp as number,
            metadata: payload as Record<string, unknown>,
          });
          return newMap;
        });
        break;
      }

      case "agent_completed": {
        const agentName = payload.agent as string;
        setAgents((prev) => {
          const newMap = new Map(prev);
          const existing = prev.get(agentName);
          newMap.set(agentName, {
            ...existing,
            name: agentName,
            status: payload.success ? "completed" : "failed",
            endTime: payload.timestamp as number,
            metadata: { ...existing?.metadata, ...payload },
          });
          return newMap;
        });
        break;
      }

      case "tool_started": {
        const toolName = payload.tool as string;
        const field = payload.field as string;
        setTools((prev) => [
          ...prev,
          {
            name: toolName,
            field,
            status: "running",
            startTime: payload.timestamp as number,
          },
        ]);
        break;
      }

      case "tool_completed": {
        const field = payload.field as string;
        setTools((prev) =>
          prev.map((t) =>
            t.field === field
              ? {
                  ...t,
                  status: payload.success ? "completed" : "failed",
                  endTime: payload.timestamp as number,
                  timeMs: payload.time_ms as number,
                  confidence: payload.confidence as number,
                  error: payload.error as string,
                }
              : t
          )
        );
        break;
      }

      case "extraction_progress": {
        setExtractionProgress({
          completed: payload.completed as number,
          total: payload.total as number,
        });
        break;
      }

      case "content_analysis": {
        // Content analysis complete event
        setAgents((prev) => {
          const newMap = new Map(prev);
          const existing = prev.get("content_analyzer");
          if (existing) {
            newMap.set("content_analyzer", {
              ...existing,
              metadata: {
                ...existing.metadata,
                region_count: payload.region_count,
                region_types: payload.region_types,
                pages_analyzed: payload.pages_analyzed,
              },
            });
          }
          return newMap;
        });
        break;
      }

      case "extraction_plan": {
        // Extraction plan ready event
        setAgents((prev) => {
          const newMap = new Map(prev);
          const existing = prev.get("mapping");
          if (existing) {
            newMap.set("mapping", {
              ...existing,
              metadata: {
                ...existing.metadata,
                total_fields: payload.total_fields,
                parallel_count: payload.parallel_count,
                sequential_count: payload.sequential_count,
                tools_used: payload.tools_used,
              },
            });
          }
          return newMap;
        });
        break;
      }
    }
  }, [events]);

  // Convert agents map to array for rendering
  const agentSteps: AgentStepData[] = Array.from(agents.values()).map((agent) => ({
    name: agent.name,
    status: agent.status,
    timeMs: agent.endTime && agent.startTime
      ? Math.round((agent.endTime - agent.startTime) * 1000)
      : undefined,
    details: formatAgentDetails(agent),
  }));

  // Convert tools to ToolExecutionData
  const toolExecutions: ToolExecutionData[] = tools.map((tool) => ({
    tool: tool.name,
    field: tool.field,
    status: tool.status,
    timeMs: tool.timeMs,
    confidence: tool.confidence,
    error: tool.error,
  }));

  // Always show when mounted (for debugging)
  // if (!isActive && events.length === 0) {
  //   return null;
  // }

  return (
    <Card className={cn("", className)}>
      <CardHeader className="py-3 px-4 flex flex-row items-center justify-between">
        <CardTitle className="text-lg flex items-center gap-2">
          <Activity className="h-5 w-5" />
          Agent Activity
        </CardTitle>
        {isActive && (
          <Badge variant="outline" className="flex items-center gap-1">
            <Loader2 className="h-3 w-3 animate-spin" />
            Live
          </Badge>
        )}
      </CardHeader>
      <CardContent className="p-4 pt-0 space-y-4">
        {/* Waiting for events */}
        {agentSteps.length === 0 && toolExecutions.length === 0 && (
          <div className="text-sm text-muted-foreground text-center py-4">
            <Loader2 className="h-4 w-4 animate-spin mx-auto mb-2" />
            Waiting for agent events...
            <div className="text-xs mt-1">({events.length} events received)</div>
          </div>
        )}

        {/* Agent Steps */}
        {agentSteps.length > 0 && (
          <div className="space-y-2">
            {agentSteps.map((step) => (
              <AgentStep key={step.name} data={step} />
            ))}
          </div>
        )}

        {/* Tool Executions (nested under Extraction agent) */}
        {toolExecutions.length > 0 && (
          <div className="pl-6 border-l-2 border-muted space-y-1">
            {toolExecutions.map((exec, idx) => (
              <ToolExecution key={`${exec.field}-${idx}`} data={exec} />
            ))}
          </div>
        )}

        {/* Progress summary */}
        {extractionProgress.total > 0 && (
          <div className="text-sm text-muted-foreground text-center pt-2">
            {extractionProgress.completed} / {extractionProgress.total} fields extracted
          </div>
        )}
      </CardContent>
    </Card>
  );
}

/**
 * Format agent details for display
 */
function formatAgentDetails(agent: AgentState): string | undefined {
  if (!agent.metadata) return undefined;

  const details: string[] = [];

  if (agent.name === "content_analyzer") {
    const regionCount = agent.metadata.region_count as number | undefined;
    const pagesAnalyzed = agent.metadata.pages_analyzed as number | undefined;
    if (regionCount !== undefined) {
      details.push(`${regionCount} regions`);
    }
    if (pagesAnalyzed !== undefined) {
      details.push(`${pagesAnalyzed} pages`);
    }
  }

  if (agent.name === "mapping") {
    const totalFields = agent.metadata.total_fields as number | undefined;
    const parallelCount = agent.metadata.parallel_count as number | undefined;
    if (totalFields !== undefined) {
      details.push(`${totalFields} fields`);
    }
    if (parallelCount !== undefined) {
      details.push(`${parallelCount} parallel`);
    }
  }

  if (agent.name === "extraction") {
    const fieldsExtracted = agent.metadata.fields_extracted as number | undefined;
    if (fieldsExtracted !== undefined) {
      details.push(`${fieldsExtracted} fields extracted`);
    }
  }

  return details.length > 0 ? details.join(", ") : undefined;
}
