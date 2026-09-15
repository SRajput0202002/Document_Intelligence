"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { api, type Job, type JobPart, type WorkflowSegmentationSettings } from "@/lib/api";
import { useWebSocket, type WebSocketMessage } from "./use-websocket";
import { toast } from "@/components/ui/toast";
import type { AgentEvent } from "@/components/agui";

// Agent event types that we handle
const AGENT_EVENT_TYPES = [
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

function isAgentEvent(type: string): boolean {
  return AGENT_EVENT_TYPES.includes(type as typeof AGENT_EVENT_TYPES[number]);
}

interface UseExtractionReturn {
  startExtraction: (
    file: File,
    docType: string,
    ocrProvider: string,
    llmProvider: string,
    schemaId?: string,
    useAgents?: boolean,
    ocrModelConfig?: Record<string, string>,
    workflowId?: string
  ) => Promise<void>;
  /** Segment PDF then extract each segment (matches workflow multidoc + Extract page multi-doc). */
  startWorkflowMultidocExtraction: (
    file: File,
    workflowSchemaId: string,
    ocrProvider: string,
    llmProvider: string,
    useAgents: boolean,
    segmentationSettings?: WorkflowSegmentationSettings | null,
    ocrModelConfig?: Record<string, string>
  ) => Promise<void>;
  job: Job | null;
  isExtracting: boolean;
  progress: number;
  currentStep: string;
  parts: JobPart[];
  error: string | null;
  reset: () => void;
  // Agent events (for AGUI)
  agentEvents: AgentEvent[];
  isAgentActive: boolean;
  clearAgentEvents: () => void;
}

export function useExtraction(): UseExtractionReturn {
  const [job, setJob] = useState<Job | null>(null);
  const [isExtracting, setIsExtracting] = useState(false);
  const [progress, setProgress] = useState(0);
  const [currentStep, setCurrentStep] = useState("");
  const [parts, setParts] = useState<JobPart[]>([]);
  const [error, setError] = useState<string | null>(null);
  const pollingRef = useRef<NodeJS.Timeout | null>(null);
  const jobIdRef = useRef<string | null>(null);
  const isPollingRef = useRef(false);

  // Agent events state (for AGUI)
  const [agentEvents, setAgentEvents] = useState<AgentEvent[]>([]);
  const [isAgentActive, setIsAgentActive] = useState(false);

  // Polling function - extracted so it can be called immediately when job ID is set
  const pollJobStatus = useCallback(async () => {
    const jobId = jobIdRef.current;
    if (!jobId || isPollingRef.current) return;

    isPollingRef.current = true;
    try {
      const jobData = await api.getJob(jobId);
      console.log(`[Poll] Job ${jobId}: status=${jobData.status}, progress=${jobData.progress}`);

      // Update state with polled data
      setJob(jobData);
      setProgress(jobData.progress * 100);
      setCurrentStep(jobData.current_step || "Processing...");
      setParts(jobData.parts || []);

      // Check if job is complete
      if (jobData.status === "completed" || jobData.status === "failed") {
        console.log(`[Poll] Job ${jobId} finished with status: ${jobData.status}`);
        setIsExtracting(false);
        if (pollingRef.current) {
          clearInterval(pollingRef.current);
          pollingRef.current = null;
        }

        if (jobData.status === "completed") {
          const completedParts = jobData.parts?.filter(p => p.status === "completed").length || 0;
          const failedParts = jobData.parts?.filter(p => p.status === "failed").length || 0;
          toast({
            title: "Extraction Complete",
            description: `${completedParts} parts extracted successfully${
              failedParts > 0 ? `, ${failedParts} failed` : ""
            }.`,
          });
        } else if (jobData.status === "failed") {
          setError(jobData.error || "Extraction failed");
          toast({
            title: "Extraction Failed",
            description: jobData.error || "Unknown error",
            variant: "destructive",
          });
        }
      }
    } catch (err) {
      console.error("Polling error:", err);
    } finally {
      isPollingRef.current = false;
    }
  }, []);

  // Start polling when we have a job and are extracting
  useEffect(() => {
    if (!isExtracting) {
      if (pollingRef.current) {
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
      return;
    }

    // Start polling every 500ms (faster than before)
    console.log("[Poll] Starting polling interval");
    pollingRef.current = setInterval(pollJobStatus, 500);

    return () => {
      if (pollingRef.current) {
        console.log("[Poll] Clearing polling interval");
        clearInterval(pollingRef.current);
        pollingRef.current = null;
      }
    };
  }, [isExtracting, pollJobStatus]);

  const handleWebSocketMessage = useCallback((message: WebSocketMessage) => {
    switch (message.type) {
      case "initial_status":
        if (message.payload) {
          const jobData = message.payload as unknown as Job;
          setJob(jobData);
          setProgress(jobData.progress * 100);
          setCurrentStep(jobData.current_step);
          setParts(jobData.parts || []);
        }
        break;

      case "status_update":
        if (message.payload) {
          const { status, progress: prog, current_step } = message.payload as {
            status: Job["status"];
            progress: number;
            current_step: string;
          };
          setProgress(prog * 100);
          setCurrentStep(current_step);
          setJob((prev) =>
            prev ? { ...prev, status, progress: prog, current_step } : prev
          );
        }
        break;

      case "part_started":
        if (message.payload) {
          const { part_name } = message.payload as { part_name: string };
          setCurrentStep(`Extracting ${part_name}...`);
          setParts((prev) =>
            prev.map((p) =>
              p.part_name === part_name ? { ...p, status: "processing" as const } : p
            )
          );
        }
        break;

      case "part_completed":
        if (message.payload) {
          const { part_name, status, confidence, error: partError } = message.payload as {
            part_name: string;
            status: JobPart["status"];
            confidence: number;
            error: string | null;
          };
          setParts((prev) =>
            prev.map((p) =>
              p.part_name === part_name
                ? { ...p, status, confidence, error: partError ?? undefined }
                : p
            )
          );
        }
        break;

      case "job_completed":
        if (message.payload) {
          const { status, total_time, parts_completed, parts_failed } = message.payload as {
            status: Job["status"];
            total_time: number;
            parts_completed: number;
            parts_failed: number;
          };
          setIsExtracting(false);
          setProgress(100);
          setCurrentStep("Completed");
          setJob((prev) => (prev ? { ...prev, status } : prev));

          // Fetch final job data using job_id from message (not stale closure)
          const jobIdFromMessage = message.job_id;
          if (jobIdFromMessage) {
            api.getJob(jobIdFromMessage).then((finalJob) => {
              setJob(finalJob);
              setParts(finalJob.parts);
            }).catch((err) => {
              console.error("Failed to fetch final job data:", err);
            });
          }

          toast({
            title: "Extraction Complete",
            description: `${parts_completed} parts extracted successfully${
              parts_failed > 0 ? `, ${parts_failed} failed` : ""
            }. Time: ${total_time.toFixed(1)}s`,
          });
        }
        break;

      case "error":
        if (message.payload) {
          const { message: errorMessage, part_name } = message.payload as {
            message: string;
            part_name: string | null;
          };
          setError(errorMessage);
          if (part_name) {
            setParts((prev) =>
              prev.map((p) =>
                p.part_name === part_name
                  ? { ...p, status: "failed" as const, error: errorMessage }
                  : p
              )
            );
          }
          toast({
            title: "Extraction Error",
            description: errorMessage,
            variant: "destructive",
          });
        }
        break;

      case "ping":
        // Respond to server pings
        break;

      default:
        // Check if it's an agent event
        if (isAgentEvent(message.type)) {
          console.log("[useExtraction] Agent event received:", message.type, message.payload);
          const agentEvent: AgentEvent = {
            type: message.type,
            job_id: message.job_id,
            payload: message.payload,
          };
          setAgentEvents((prev) => [...prev, agentEvent]);

          // Track active state
          if (message.type === "agent_started" && message.payload?.agent === "extraction") {
            setIsAgentActive(true);
          } else if (message.type === "agent_completed" && message.payload?.agent === "extraction") {
            setIsAgentActive(false);
          }
        } else {
          console.log("Unknown WebSocket message type:", message.type);
        }
    }
  }, [job?.id]);

  useWebSocket({
    jobId: isExtracting && job ? job.id : null,
    onMessage: handleWebSocketMessage,
    onConnect: () => {
      console.log("WebSocket connected");
    },
    onDisconnect: () => {
      console.log("WebSocket disconnected");
    },
  });

  const startExtraction = useCallback(
    async (
      file: File,
      docType: string,
      ocrProvider: string,
      llmProvider: string,
      schemaId?: string,
      useAgents: boolean = false,
      ocrModelConfig?: Record<string, string>,
      workflowId?: string
    ) => {
      setError(null);
      setIsExtracting(true);
      setProgress(0);
      setCurrentStep("Starting extraction...");
      setParts([]);
      // Clear any previous agent events
      setAgentEvents([]);
      setIsAgentActive(false);

      try {
        const newJob = await api.startExtraction(
          file,
          docType,
          ocrProvider,
          llmProvider,
          schemaId,
          useAgents,
          ocrModelConfig,
          workflowId
        );

        // Store job ID in ref for polling
        jobIdRef.current = newJob.id;
        console.log(`[Extraction] Started job ${newJob.id}, status=${newJob.status}`);

        setJob(newJob);
        setParts(newJob.parts || []);
        setProgress(newJob.progress * 100);
        setCurrentStep(newJob.current_step || "Initializing...");

        if (newJob.status === "completed" || newJob.status === "failed") {
          setIsExtracting(false);
          if (newJob.status === "completed") {
            const completedParts =
              newJob.parts?.filter((p) => p.status === "completed").length || 0;
            const failedParts = newJob.parts?.filter((p) => p.status === "failed").length || 0;
            toast({
              title: "Extraction Complete",
              description: `${completedParts} parts extracted successfully${
                failedParts > 0 ? `, ${failedParts} failed` : ""
              }.`,
            });
          } else {
            setError(newJob.error || "Extraction failed");
            toast({
              title: "Extraction Failed",
              description: newJob.error || "Unknown error",
              variant: "destructive",
            });
          }
        } else {
          setTimeout(() => pollJobStatus(), 100);
          toast({
            title: "Extraction Started",
            description: `Processing ${file.name}...`,
          });
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : "Failed to start extraction";
        jobIdRef.current = null;
        setError(errorMessage);
        setIsExtracting(false);
        toast({
          title: "Extraction Failed",
          description: errorMessage,
          variant: "destructive",
        });
      }
    },
    [pollJobStatus]
  );

  const startWorkflowMultidocExtraction = useCallback(
    async (
      file: File,
      workflowSchemaId: string,
      ocrProvider: string,
      llmProvider: string,
      useAgents: boolean,
      segmentationSettings?: WorkflowSegmentationSettings | null,
      ocrModelConfig?: Record<string, string>
    ) => {
      setError(null);
      setIsExtracting(true);
      setProgress(0);
      setCurrentStep("Analyzing document segments...");
      setParts([]);
      setAgentEvents([]);
      setIsAgentActive(false);

      const seg = segmentationSettings ?? {};
      const mode = seg.mode ?? "homogeneous";
      let expectedTypes: string[] = [];
      const et = seg.expected_types;
      if (Array.isArray(et)) {
        expectedTypes = et.filter(Boolean).map(String);
      } else if (typeof et === "string") {
        expectedTypes = et.split(",").map((s) => s.trim()).filter(Boolean);
      }
      const profile = seg.profile;
      const enableLlmFallback = Boolean(seg.enable_llm_fallback);
      const confidenceThreshold =
        typeof seg.confidence_threshold === "number" ? seg.confidence_threshold : 0.6;

      try {
        const analysis = await api.analyzeSegments(
          file,
          mode,
          expectedTypes,
          enableLlmFallback,
          confidenceThreshold,
          ocrProvider,
          profile && profile !== "auto" ? profile : undefined,
          ocrModelConfig
        );

        if (!analysis.success) {
          throw new Error(analysis.error || "Segment analysis failed");
        }
        if (!analysis.segments?.length) {
          throw new Error("No document segments detected in this file");
        }

        const segmentSchemas: Record<number, string> = {};
        for (const s of analysis.segments) {
          segmentSchemas[s.index] = workflowSchemaId;
        }

        setCurrentStep("Starting multi-document extraction...");
        const newJob = await api.startSegmentedExtraction(
          file,
          segmentSchemas,
          mode,
          expectedTypes,
          enableLlmFallback,
          confidenceThreshold,
          ocrProvider,
          llmProvider,
          useAgents,
          profile && profile !== "auto" ? profile : undefined,
          analysis.document_cache_id,
          analysis.segmentation_config_hash,
          ocrModelConfig
        );

        const jobId = newJob.id;
        jobIdRef.current = jobId;
        setJob({
          ...newJob,
          parts: newJob.parts ?? [],
        });
        setParts(newJob.parts ?? []);
        setProgress((newJob.progress ?? 0) * 100);
        setCurrentStep(newJob.current_step || "Processing segments...");

        setTimeout(() => pollJobStatus(), 100);

        toast({
          title: "Segmented extraction started",
          description: `${analysis.segments.length} segment(s) — ${file.name}`,
        });
      } catch (err) {
        const errorMessage =
          err instanceof Error ? err.message : "Failed to start segmented extraction";
        jobIdRef.current = null;
        setError(errorMessage);
        setIsExtracting(false);
        toast({
          title: "Segmented extraction failed",
          description: errorMessage,
          variant: "destructive",
        });
      }
    },
    [pollJobStatus]
  );

  const reset = useCallback(() => {
    jobIdRef.current = null;
    if (pollingRef.current) {
      clearInterval(pollingRef.current);
      pollingRef.current = null;
    }
    setJob(null);
    setIsExtracting(false);
    setProgress(0);
    setCurrentStep("");
    setParts([]);
    setError(null);
    // Clear agent events
    setAgentEvents([]);
    setIsAgentActive(false);
  }, []);

  const clearAgentEvents = useCallback(() => {
    setAgentEvents([]);
    setIsAgentActive(false);
  }, []);

  return {
    startExtraction,
    startWorkflowMultidocExtraction,
    job,
    isExtracting,
    progress,
    currentStep,
    parts,
    error,
    reset,
    // Agent events (for AGUI)
    agentEvents,
    isAgentActive,
    clearAgentEvents,
  };
}
