"use client";

import { useState, useEffect, useCallback, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api, Workflow, API_BASE_URL } from "@/lib/api";
import { useExtraction } from "@/hooks/use-extraction";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { PipelineFlow, PipelineStage } from "@/components/extraction/pipeline-flow";
import {
  Upload,
  FileText,
  Loader2,
  Play,
  Check,
  AlertCircle,
  Scan,
  Cpu,
  FileType,
  X,
  Terminal,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { toast } from "@/components/ui/toast";
import { CopyButton } from "@/components/ui/copy-button";
import { Progress } from "@/components/ui/progress";
import { ArrowRight } from "lucide-react";
import { formatApiErrorDetail } from "@/lib/format-api-error";

interface TestWorkflowModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  workflow: Workflow;
  initialMode?: "direct" | "api";
}

type TestStep = "upload" | "processing" | "results";

export function TestWorkflowModal({
  open,
  onOpenChange,
  workflow,
  initialMode = "direct",
}: TestWorkflowModalProps) {
  const workflowId = String(workflow.id);
  const router = useRouter();
  const testMode = initialMode;
  const [step, setStep] = useState<TestStep>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [pipelineStage, setPipelineStage] = useState<PipelineStage>("idle");

  // API test state
  const [apiKey, setApiKey] = useState<string>("");
  const [apiResponse, setApiResponse] = useState<any>(null);
  const [apiError, setApiError] = useState<string | null>(null);
  const [apiLoading, setApiLoading] = useState(false);
  const [apiResponseTime, setApiResponseTime] = useState<number | null>(null);

  // Fresh workflow so OCR/LLM (and schema_id) match server after settings save — list cards can be stale
  const { data: freshWorkflow } = useQuery({
    queryKey: ["workflow", workflowId],
    queryFn: () => api.getWorkflow(workflowId),
    enabled: open,
    staleTime: 0,
    gcTime: 0,
    refetchOnMount: "always",
  });

  const resolvedWorkflow = freshWorkflow ?? workflow;

  const { data: schema } = useQuery({
    queryKey: ["schema", resolvedWorkflow.schema_id],
    queryFn: () => api.getSchema(resolvedWorkflow.schema_id),
    enabled: open && !!resolvedWorkflow.schema_id,
  });




  // Extraction hook
  const {
    startExtraction,
    startWorkflowMultidocExtraction,
    job,
    isExtracting,
    progress,
    currentStep: processingStep,
    parts,
    error,
    reset: resetExtraction,
  } = useExtraction();

  // Reset state when modal opens/closes
  useEffect(() => {
    if (open) {
      setStep("upload");
      setFile(null);
      setPipelineStage("idle");
      resetExtraction();
      setApiKey("");
      setApiResponse(null);
      setApiError(null);
      setApiResponseTime(null);
    }
  }, [open, resetExtraction]);

  // Map processing step to pipeline stage
  useEffect(() => {
    if (!isExtracting && step !== "processing") {
      setPipelineStage("idle");
      return;
    }

    if (error) {
      setPipelineStage("failed");
      return;
    }

    const stepLower = processingStep.toLowerCase();

    if (stepLower.includes("start") || stepLower.includes("initializ") || stepLower.includes("analyz")) {
      setPipelineStage("configuration");
    } else if (stepLower.includes("ocr") || stepLower.includes("scanning")) {
      setPipelineStage("ocr");
    } else if (stepLower.includes("extract")) {
      setPipelineStage("llm");
    } else if (stepLower.includes("validat") || stepLower.includes("check")) {
      setPipelineStage("validation");
    } else if (stepLower.includes("prepar") || stepLower.includes("final")) {
      setPipelineStage("preparing");
    } else if (stepLower.includes("complet") || stepLower.includes("done")) {
      setPipelineStage("completed");
    }
  }, [processingStep, isExtracting, step, error]);

  // Transition to results when job completes
  useEffect(() => {
    if (job?.status === "completed" && step === "processing") {
      setStep("results");
    }
  }, [job?.status, step]);

  // Handle file drop
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    const droppedFile = e.dataTransfer.files[0];
    if (droppedFile) {
      setFile(droppedFile);
    }
  }, []);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
  }, []);

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0];
    if (selectedFile) {
      setFile(selectedFile);
    }
    // Allow re-selecting the same file after remove (browser skips change if value unchanged)
    e.target.value = "";
  }, []);

  // Start direct extraction (segmented path when workflow.is_multidoc matches API behavior)
  const handleStartExtraction = useCallback(async () => {
    if (!file || !schema) return;

    setStep("processing");
    setPipelineStage("configuration");

    if (workflow.is_multidoc && workflow.schema_id) {
      await startWorkflowMultidocExtraction(
        file,
        workflow.schema_id,
        workflow.ocr_provider,
        workflow.llm_provider,
        false,
        workflow.segmentation_settings ?? null,
        workflow.ocr_model_config as Record<string, string> | undefined
      );
      return;
    }

    await startExtraction(
      file,
      schema.doc_type,
      resolvedWorkflow.ocr_provider,
      resolvedWorkflow.llm_provider,
      resolvedWorkflow.schema_id,
      false, // useAgents
      resolvedWorkflow.ocr_model_config as Record<string, string> | undefined,
      workflow.id
    );
  }, [file, schema, workflow, startExtraction, startWorkflowMultidocExtraction]);

  // Test API endpoint
  const handleTestApi = useCallback(async () => {
    if (!file || !apiKey) {
      toast.error("Please select a file and API key");
      return;
    }

    setApiLoading(true);
    setApiError(null);
    setApiResponse(null);
    setApiResponseTime(null);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const response = await fetch(
        `${API_BASE_URL}/api/v1/workflows/${resolvedWorkflow.slug}/extract`,
        {
          method: "POST",
          headers: {
            "X-API-Key": apiKey,
          },
          body: formData,
        }
      );

      const data = await response.json();
      const serverResponseTime =
        typeof data?.processing_time_ms === "number"
          ? Math.round(data.processing_time_ms)
          : typeof data?.response_time_ms === "number"
            ? Math.round(data.response_time_ms)
            : null;
      setApiResponseTime(serverResponseTime);

      if (!response.ok) {
        setApiError(
          formatApiErrorDetail(
            data?.detail,
            `HTTP ${response.status}: ${response.statusText}`
          )
        );
      } else {
        setApiResponse(data);
        toast.success("API request successful");
      }
    } catch (err) {
      setApiError(err instanceof Error ? err.message : "Request failed");
    } finally {
      setApiLoading(false);
    }
  }, [file, apiKey, resolvedWorkflow.slug]);

  // Handle close
  const handleClose = useCallback(() => {
    if (isExtracting || apiLoading) return;
    onOpenChange(false);
  }, [isExtracting, apiLoading, onOpenChange]);

  // View full results
  const handleViewFullResults = useCallback(() => {
    if (job) {
      onOpenChange(false);
      router.push(`/jobs/${job.id}?from=workflow`);
    }
  }, [job, onOpenChange, router]);

  // Calculate confidence
  const confidence = useMemo(() => {
    if (!parts || parts.length === 0) return 0;
    return parts.reduce((acc, p) => acc + (p.confidence || 0), 0) / parts.length;
  }, [parts]);

  // API Test Modal - Two Column Layout
  if (testMode === "api") {
    return (
      <Dialog open={open} onOpenChange={handleClose}>
        <DialogContent className="max-w-2xl p-0 gap-0">
          <DialogHeader className="px-6 pt-6 pb-6">
            <DialogTitle className="flex items-center gap-2">
              <Terminal className="w-5 h-5" />
              {resolvedWorkflow.name}
            </DialogTitle>
          </DialogHeader>

          <div className="px-6 pb-6">
            <div className="grid grid-cols-2 gap-6">
              {/* Left Column */}
              <div className="space-y-4">
                {/* Config Details */}
                <div className="space-y-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                      <FileType className="w-4 h-4 text-blue-600" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase">Schema</p>
                      <p className="text-sm font-medium">{schema?.name || "..."}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                      <Scan className="w-4 h-4 text-amber-600" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase">OCR</p>
                      <p className="text-sm font-medium">{resolvedWorkflow.ocr_provider}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                      <Cpu className="w-4 h-4 text-purple-600" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase">LLM</p>
                      <p className="text-sm font-medium">{resolvedWorkflow.llm_provider}</p>
                    </div>
                  </div>
                </div>

                {/* API Key Input */}
                <div className="space-y-1.5">
                  <label className="text-[10px] text-muted-foreground uppercase">API Key</label>
                  <Input
                    placeholder="wf_..."
                    value={apiKey}
                    onChange={(e) => setApiKey(e.target.value)}
                    className="h-9 font-mono text-sm"
                  />
                </div>

                {/* cURL Command */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-[10px] text-muted-foreground uppercase">cURL</label>
                    <CopyButton
                      value={`curl -X POST "${API_BASE_URL}/api/v1/workflows/${resolvedWorkflow.slug}/extract" -H "X-API-Key: ${apiKey || 'wf_your_api_key'}" -F "file=@${file?.name || 'document.pdf'}"`}
                      className="h-6 w-6"
                    />
                  </div>
                  <pre className="text-[11px] font-mono text-muted-foreground bg-muted p-3 rounded-lg overflow-x-auto">
{`curl -X POST \\
  ".../api/v1/workflows/${resolvedWorkflow.slug}/extract" \\
  -H "X-API-Key: ${apiKey || 'wf_...'}" \\
  -F "file=@${file?.name || 'document.pdf'}"`}
                  </pre>
                </div>
              </div>

              {/* Right Column */}
              <div className="space-y-4">
                {/* File Upload Area */}
                <input
                  type="file"
                  className="hidden"
                  id="api-test-file-input"
                  onChange={handleFileSelect}
                  accept=".pdf,.png,.jpg,.jpeg,.tiff,.heic,.gif,.webp,.bmp,.docx,.xlsx,.doc,.xls,.txt,.csv"
                />
                <label
                  htmlFor={file ? undefined : "api-test-file-input"}
                  className={cn(
                    "border border-dashed rounded-lg p-6 transition-colors min-h-[160px] flex flex-col items-center justify-center",
                    file
                      ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/20"
                      : "border-muted-foreground/30 hover:border-primary/50 cursor-pointer"
                  )}
                  onDrop={handleDrop}
                  onDragOver={handleDragOver}
                >
                  {file ? (
                    <div className="text-center">
                      <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/50 flex items-center justify-center mx-auto mb-2">
                        <FileText className="w-5 h-5 text-emerald-600" />
                      </div>
                      <p className="font-medium text-sm mb-0.5">{file.name}</p>
                      <p className="text-[10px] text-muted-foreground mb-2">
                        {(file.size / 1024 / 1024).toFixed(2)} MB
                      </p>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs"
                        onClick={(e) => {
                          e.preventDefault();
                          e.stopPropagation();
                          setFile(null);
                          const input = document.getElementById("api-test-file-input") as HTMLInputElement | null;
                          if (input) input.value = "";
                        }}
                      >
                        <X className="w-3 h-3 mr-1" />
                        Remove
                      </Button>
                    </div>
                  ) : (
                    <div className="text-center">
                      <Upload className="w-8 h-8 text-muted-foreground/50 mx-auto mb-2" />
                      <p className="text-sm mb-0.5">Drop document here</p>
                      <p className="text-[10px] text-muted-foreground">or click to browse</p>
                    </div>
                  )}
                </label>

                {/* Response Area */}
                <div className="bg-muted/30 rounded-lg overflow-hidden">
                  <div className="flex items-center justify-between px-3 py-2">
                    <span className="text-[10px] text-muted-foreground uppercase">Response</span>
                    <div className="flex items-center gap-2">
                      {apiResponseTime && (
                        <Badge variant="outline" className="text-[10px] h-5">{apiResponseTime}ms</Badge>
                      )}
                      {apiResponse && (
                        <CopyButton
                          value={JSON.stringify(apiResponse, null, 2)}
                          className="h-5 w-5"
                          iconSize={12}
                        />
                      )}
                    </div>
                  </div>
                  <div className="px-3 pb-3 min-h-[100px] max-h-[180px] overflow-auto">
                    {apiLoading ? (
                      <div className="flex items-center justify-center py-8 text-muted-foreground">
                        <Loader2 className="w-4 h-4 animate-spin mr-2" />
                        <span className="text-xs">Sending...</span>
                      </div>
                    ) : apiError ? (
                      <div className="flex items-start gap-2 text-destructive py-2">
                        <AlertCircle className="w-3.5 h-3.5 mt-0.5 flex-shrink-0" />
                        <p className="text-xs">{apiError}</p>
                      </div>
                    ) : apiResponse ? (
                      <pre className="text-[10px] font-mono text-muted-foreground">
                        {JSON.stringify(apiResponse, null, 2)}
                      </pre>
                    ) : (
                      <p className="text-xs text-muted-foreground text-center py-8">
                        Response will appear here
                      </p>
                    )}
                  </div>
                </div>

                {/* Send Button */}
                <Button
                  onClick={handleTestApi}
                  disabled={!file || !apiKey || apiLoading}
                  className="w-full h-9"
                >
                  {apiLoading ? (
                    <>
                      <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      Sending...
                    </>
                  ) : (
                    <>
                      <Play className="w-4 h-4 mr-2" />
                      Run API Test
                    </>
                  )}
                </Button>
              </div>
            </div>
          </div>
        </DialogContent>
      </Dialog>
    );
  }

  // Direct Test Modal
  return (
    <Dialog open={open} onOpenChange={handleClose}>
      <DialogContent className={cn(
        "p-0 gap-0 flex flex-col",
        step === "upload"
          ? "max-w-2xl"
          : "h-[70vh] max-h-[70vh] w-[70vw] max-w-[70vw]"
      )}>
        {/* Header with Step Indicators */}
        <DialogHeader className="flex-none px-6 py-4 pr-12">
          <div className="flex items-center justify-between">
            <DialogTitle className="flex items-center gap-2">
              <Play className="w-5 h-5" />
              {resolvedWorkflow.name}
            </DialogTitle>
            <div className="flex items-center gap-2">
              <StepIndicator step={1} label="Upload" currentStep={step === "upload" ? 1 : step === "processing" ? 2 : 3} />
              <StepConnector active={step !== "upload"} />
              <StepIndicator step={2} label="Process" currentStep={step === "upload" ? 1 : step === "processing" ? 2 : 3} />
              <StepConnector active={step === "results"} />
              <StepIndicator step={3} label="Results" currentStep={step === "upload" ? 1 : step === "processing" ? 2 : 3} />
            </div>
          </div>
        </DialogHeader>

        {/* Content */}
        <div className={cn(
          step === "upload" ? "p-6" : "flex-1 flex flex-col min-h-0"
        )}>
          {step === "upload" && (
            <div className="grid grid-cols-2 gap-6">
                {/* Left Column - Config */}
                <div className="space-y-3">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-blue-100 dark:bg-blue-900/30 flex items-center justify-center">
                      <FileType className="w-4 h-4 text-blue-600" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase">Schema</p>
                      <p className="text-sm font-medium">{schema?.name || "..."}</p>
                      {workflow.is_multidoc && (
                        <p className="text-[10px] text-emerald-600 dark:text-emerald-400 mt-0.5">
                          Multi-document: segment PDF, then extract each part
                        </p>
                      )}
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-amber-100 dark:bg-amber-900/30 flex items-center justify-center">
                      <Scan className="w-4 h-4 text-amber-600" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase">OCR</p>
                      <p className="text-sm font-medium">{resolvedWorkflow.ocr_provider}</p>
                    </div>
                  </div>
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                      <Cpu className="w-4 h-4 text-purple-600" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground uppercase">LLM</p>
                      <p className="text-sm font-medium">{resolvedWorkflow.llm_provider}</p>
                    </div>
                  </div>
                </div>

                {/* Right Column - Upload & Action */}
                <div className="space-y-4">
                  {/* File Upload */}
                  <input
                    type="file"
                    className="hidden"
                    id="direct-test-file-input"
                    onChange={handleFileSelect}
                    accept=".pdf,.png,.jpg,.jpeg,.tiff,.heic,.gif,.webp,.bmp,.docx,.xlsx,.doc,.xls,.txt,.csv"
                  />
                  <label
                    htmlFor={file ? undefined : "direct-test-file-input"}
                    className={cn(
                      "border border-dashed rounded-lg p-6 transition-colors min-h-[160px] flex flex-col items-center justify-center",
                      file
                        ? "border-emerald-500 bg-emerald-50 dark:bg-emerald-950/20"
                        : "border-muted-foreground/30 hover:border-primary/50 cursor-pointer"
                    )}
                    onDrop={handleDrop}
                    onDragOver={handleDragOver}
                  >
                    {file ? (
                      <div className="text-center">
                        <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/50 flex items-center justify-center mx-auto mb-2">
                          <FileText className="w-5 h-5 text-emerald-600" />
                        </div>
                        <p className="font-medium text-sm mb-0.5">{file.name}</p>
                        <p className="text-[10px] text-muted-foreground mb-2">
                          {(file.size / 1024 / 1024).toFixed(2)} MB
                        </p>
                        <Button
                          type="button"
                          variant="ghost"
                          size="sm"
                          className="h-7 text-xs"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            setFile(null);
                            const input = document.getElementById("direct-test-file-input") as HTMLInputElement | null;
                            if (input) input.value = "";
                          }}
                        >
                          <X className="w-3 h-3 mr-1" />
                          Remove
                        </Button>
                      </div>
                    ) : (
                      <div className="text-center">
                        <Upload className="w-8 h-8 text-muted-foreground/50 mx-auto mb-2" />
                        <p className="text-sm mb-0.5">Drop document here</p>
                        <p className="text-[10px] text-muted-foreground">or click to browse</p>
                      </div>
                    )}
                  </label>

                  {/* Start Button */}
                  <Button
                    onClick={handleStartExtraction}
                    disabled={!file}
                    className="w-full h-9"
                  >
                    <Play className="w-4 h-4 mr-2" />
                    Start Extraction
                  </Button>
                </div>
              </div>
          )}

          {step === "processing" && (
            <div className="flex-1 min-h-0 relative">
              {/* Pipeline Flow */}
              <PipelineFlow
                currentStage={pipelineStage}
                isConsensusMode={false}
                ocrProviders={[resolvedWorkflow.ocr_provider]}
                llmProviders={[resolvedWorkflow.llm_provider]}
                progress={progress}
                confidenceThreshold={70}
                currentConfidence={confidence}
                className="absolute inset-0"
                embedInDialog
              />

              {/* Top Left: Document Info */}
              <div className="absolute top-4 left-4 z-10">
                <div className="bg-card border border-border rounded-lg px-3 py-2 shadow-sm">
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-muted-foreground" />
                    <div>
                      <p className="text-xs font-medium truncate max-w-[200px]">{file?.name}</p>
                      <p className="text-[10px] text-muted-foreground">{schema?.name}</p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Bottom Right: Status Panel */}
              <div className="absolute bottom-4 right-4 z-10">
                <div className="bg-card border border-border rounded-lg p-4 shadow-sm min-w-[280px]">
                  {/* Status Header */}
                  <div className="flex items-center gap-3 mb-3">
                    {error ? (
                      <div className="w-9 h-9 rounded-lg bg-red-500 flex items-center justify-center">
                        <X className="w-4 h-4 text-white" />
                      </div>
                    ) : (
                      <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center">
                        <Loader2 className="w-4 h-4 text-white animate-spin" />
                      </div>
                    )}
                    <div className="flex-1">
                      <p className="font-semibold text-sm">
                        {error ? "Extraction Failed" : processingStep || "Processing..."}
                      </p>
                      <p className="text-xs text-muted-foreground">
                        {workflow.is_multidoc ? "Multi-document (segment + extract)" : "Single provider"}
                      </p>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-muted-foreground">Progress</span>
                      <span className="font-medium">{Math.min(Math.round(progress), 100)}%</span>
                    </div>
                    <Progress value={Math.min(progress, 100)} className="h-1.5" />
                  </div>

                  {/* Providers */}
                  <div className="flex items-center gap-3 py-2 border-t border-border">
                    <div className="flex items-center gap-2 flex-1">
                      <div className="w-6 h-6 rounded bg-amber-100 dark:bg-amber-500/20 flex items-center justify-center">
                        <Scan className="w-3 h-3 text-amber-600 dark:text-amber-400" />
                      </div>
                      <div>
                        <p className="text-[10px] text-muted-foreground">OCR</p>
                        <p className="text-xs font-medium">{resolvedWorkflow.ocr_provider}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-1">
                      <div className="w-6 h-6 rounded bg-purple-100 dark:bg-purple-500/20 flex items-center justify-center">
                        <Cpu className="w-3 h-3 text-purple-600 dark:text-purple-400" />
                      </div>
                      <div>
                        <p className="text-[10px] text-muted-foreground">LLM</p>
                        <p className="text-xs font-medium">{resolvedWorkflow.llm_provider}</p>
                      </div>
                    </div>
                  </div>

                  {/* Error message */}
                  {error && (
                    <p className="text-xs text-destructive mt-2">{error}</p>
                  )}
                </div>
              </div>
            </div>
          )}

          {step === "results" && job && (
            <div className="flex-1 min-h-0 relative">
              {/* Pipeline Flow - Completed */}
              <PipelineFlow
                currentStage="completed"
                isConsensusMode={false}
                ocrProviders={[resolvedWorkflow.ocr_provider]}
                llmProviders={[resolvedWorkflow.llm_provider]}
                progress={100}
                confidenceThreshold={70}
                currentConfidence={confidence}
                className="absolute inset-0"
                embedInDialog
              />

              {/* Top Left: Document Info */}
              <div className="absolute top-4 left-4 z-10">
                <div className="bg-card border border-border rounded-lg px-3 py-2 shadow-sm">
                  <div className="flex items-center gap-2">
                    <FileText className="w-4 h-4 text-muted-foreground" />
                    <div>
                      <p className="text-xs font-medium truncate max-w-[200px]">{file?.name}</p>
                      <p className="text-[10px] text-muted-foreground">{schema?.name}</p>
                    </div>
                  </div>
                </div>
              </div>

              {/* Bottom Right: Status Panel */}
              <div className="absolute bottom-4 right-4 z-10">
                <div className="bg-card border border-border rounded-lg p-4 shadow-sm min-w-[280px]">
                  {/* Status Header */}
                  <div className="flex items-center gap-3 mb-3">
                    <div className="w-9 h-9 rounded-lg bg-emerald-500 flex items-center justify-center">
                      <Check className="w-4 h-4 text-white" />
                    </div>
                    <div className="flex-1">
                      <p className="font-semibold text-sm">Extraction Complete</p>
                      <p className="text-xs text-muted-foreground">
                        {parts?.length || 0} fields • {Math.round(confidence)}% confidence
                      </p>
                    </div>
                  </div>

                  {/* Progress bar */}
                  <div className="mb-3">
                    <div className="flex items-center justify-between text-xs mb-1">
                      <span className="text-muted-foreground">Progress</span>
                      <span className="font-medium">100%</span>
                    </div>
                    <Progress value={100} className="h-1.5" />
                  </div>

                  {/* Providers */}
                  <div className="flex items-center gap-3 py-2 border-t border-border">
                    <div className="flex items-center gap-2 flex-1">
                      <div className="w-6 h-6 rounded bg-amber-100 dark:bg-amber-500/20 flex items-center justify-center">
                        <Scan className="w-3 h-3 text-amber-600 dark:text-amber-400" />
                      </div>
                      <div>
                        <p className="text-[10px] text-muted-foreground">OCR</p>
                        <p className="text-xs font-medium">{resolvedWorkflow.ocr_provider}</p>
                      </div>
                    </div>
                    <div className="flex items-center gap-2 flex-1">
                      <div className="w-6 h-6 rounded bg-purple-100 dark:bg-purple-500/20 flex items-center justify-center">
                        <Cpu className="w-3 h-3 text-purple-600 dark:text-purple-400" />
                      </div>
                      <div>
                        <p className="text-[10px] text-muted-foreground">LLM</p>
                        <p className="text-xs font-medium">{resolvedWorkflow.llm_provider}</p>
                      </div>
                    </div>
                  </div>

                  {/* View Results Button */}
                  <Button
                    className="w-full mt-3"
                    onClick={handleViewFullResults}
                  >
                    <Check className="w-4 h-4 mr-2" />
                    View Results
                    <ArrowRight className="w-4 h-4 ml-2" />
                  </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

// Step indicator component
function StepIndicator({ step, label, currentStep }: { step: number; label: string; currentStep: number }) {
  const isCompleted = currentStep > step;
  const isActive = currentStep === step;

  return (
    <div className="flex items-center gap-1.5">
      <div className={cn(
        "w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-medium transition-colors",
        isCompleted && "bg-emerald-500 text-white",
        isActive && "bg-primary text-primary-foreground",
        !isCompleted && !isActive && "bg-muted text-muted-foreground"
      )}>
        {isCompleted ? <Check className="w-3 h-3" /> : step}
      </div>
      <span className={cn(
        "text-xs transition-colors",
        isActive && "font-medium text-foreground",
        !isActive && "text-muted-foreground"
      )}>
        {label}
      </span>
    </div>
  );
}

// Step connector line
function StepConnector({ active }: { active: boolean }) {
  return (
    <div className={cn(
      "w-8 h-px transition-colors",
      active ? "bg-emerald-500" : "bg-muted"
    )} />
  );
}
