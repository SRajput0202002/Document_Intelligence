"use client";

import { useState, useCallback, useMemo } from "react";
import { useWebSocket, WebSocketMessage } from "./use-websocket";
import type { AgentEvent } from "@/components/agui";

/**
 * Agent event types
 */
export const AGENT_EVENT_TYPES = [
  "agent_started",
  "agent_reasoning",
  "agent_completed",
  "tool_started",
  "tool_completed",
  "extraction_plan",
  "content_analysis",
  "extraction_progress",
  "validation_started",
  "validation_completed",
] as const;

export type AgentEventType = (typeof AGENT_EVENT_TYPES)[number];

/**
 * Check if a message is an agent event
 */
export function isAgentEvent(message: WebSocketMessage): boolean {
  return AGENT_EVENT_TYPES.includes(message.type as AgentEventType);
}

interface UseAgentEventsOptions {
  jobId: string | null;
  onAgentEvent?: (event: AgentEvent) => void;
  onStatusUpdate?: (message: WebSocketMessage) => void;
}

interface UseAgentEventsReturn {
  isConnected: boolean;
  agentEvents: AgentEvent[];
  isAgentActive: boolean;
  clearEvents: () => void;
}

/**
 * Hook for handling agent-specific WebSocket events.
 *
 * Separates agent events from regular status updates and provides
 * structured state for the AGUI components.
 *
 * @example
 * ```tsx
 * const { agentEvents, isAgentActive } = useAgentEvents({
 *   jobId: "123",
 *   onStatusUpdate: (msg) => updateJobStatus(msg),
 * });
 *
 * return <AgentActivity events={agentEvents} isActive={isAgentActive} />;
 * ```
 */
export function useAgentEvents({
  jobId,
  onAgentEvent,
  onStatusUpdate,
}: UseAgentEventsOptions): UseAgentEventsReturn {
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [isAgentActive, setIsAgentActive] = useState(false);

  // Debug: log when jobId changes
  console.log("[useAgentEvents] jobId:", jobId, "isAgentActive:", isAgentActive, "events:", agentEvents.length);

  const handleMessage = useCallback(
    (message: WebSocketMessage) => {
      console.log("[useAgentEvents] Received message:", message.type, message);
      if (isAgentEvent(message)) {
        // It's an agent event
        const agentEvent: AgentEvent = {
          type: message.type,
          job_id: message.job_id,
          payload: message.payload,
        };

        setAgentEvents((prev) => [...prev, agentEvent]);
        onAgentEvent?.(agentEvent);

        // Track active state
        if (message.type === "agent_started" && message.payload?.agent === "extraction") {
          setIsAgentActive(true);
        } else if (
          message.type === "agent_completed" &&
          message.payload?.agent === "extraction"
        ) {
          setIsAgentActive(false);
        }
      } else {
        // Regular status update
        onStatusUpdate?.(message);
      }
    },
    [onAgentEvent, onStatusUpdate]
  );

  const { isConnected } = useWebSocket({
    jobId,
    onMessage: handleMessage,
  });

  const clearEvents = useCallback(() => {
    setAgentEvents([]);
    setIsAgentActive(false);
  }, []);

  return {
    isConnected,
    agentEvents,
    isAgentActive,
    clearEvents,
  };
}

/**
 * Combined hook that handles both regular job updates and agent events.
 *
 * Useful when you need to track both job status and agent activity.
 */
interface UseJobWithAgentsOptions {
  jobId: string | null;
  onJobUpdate?: (message: WebSocketMessage) => void;
}

interface UseJobWithAgentsReturn extends UseAgentEventsReturn {
  // Additional job-specific state could be added here
}

export function useJobWithAgents({
  jobId,
  onJobUpdate,
}: UseJobWithAgentsOptions): UseJobWithAgentsReturn {
  return useAgentEvents({
    jobId,
    onStatusUpdate: onJobUpdate,
  });
}
