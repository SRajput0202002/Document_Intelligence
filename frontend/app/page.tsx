"use client";

import { useState, useCallback, useEffect, useRef } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useDropzone, type FileRejection } from "react-dropzone";
import {
  ChevronRight,
  ChevronLeft,
  Loader2,
  AlertCircle,
  Shield,
  Settings2,
  Cloud,
  HardDrive,
  Timer,
  Info,
  ScanText,
  Brain,
  Bolt,
  CheckCircle2,
  Cpu,
} from "lucide-react";

// Animated icons from lucide-animated
import { UploadIcon } from "@/components/ui/upload";
import { FileTextIcon } from "@/components/ui/file-text";
import { ChevronDownIcon } from "@/components/ui/chevron-down";
import { CheckIcon } from "@/components/ui/check";
import { PlayIcon } from "@/components/ui/play";
import { XIcon } from "@/components/ui/x";
import { DownloadIcon } from "@/components/ui/download";
import { CopyIcon } from "@/components/ui/copy";
import { RefreshCWIcon } from "@/components/ui/refresh-cw";
import { SparklesIcon } from "@/components/ui/sparkles";
import { ZapIcon } from "@/components/ui/zap";
import { ClockIcon } from "@/components/ui/clock";
import { ArrowRightIcon } from "@/components/ui/arrow-right";
import { PlusIcon } from "@/components/ui/plus";
import { SearchIcon } from "@/components/ui/search";
import { CpuIcon } from "@/components/ui/cpu";
import { GaugeIcon } from "@/components/ui/gauge";
import { LayersIcon } from "@/components/ui/layers";
import { DollarSignIcon } from "@/components/ui/dollar-sign";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { WorkflowIcon } from "@/components/ui/workflow";
import { SchemaBuilder, type SchemaField } from "@/components/schema-builder";
import { RandomHighlightText } from "@/components/ui/random-highlight-text";
import { PDFViewer } from "@/components/pdf-viewer";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Slider } from "@/components/ui/slider";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "@/components/ui/dialog";
import { cn } from "@/lib/utils";
import { api, type Schema, type Provider, type Job, type DocumentTypeResult } from "@/lib/api";
import { useExtraction } from "@/hooks/use-extraction";
import { getAuthHeaders } from "@/hooks/use-auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// Segmentation Profile type
interface SegmentationProfile {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  is_builtin: boolean;
}
// AgentActivity moved inline to Status Panel for compact view

// Animated icons for features
import { ScanTextIcon } from "@/components/ui/scan-text";
import { ShieldCheckIcon } from "@/components/ui/shield-check";
import { UsersIcon } from "@/components/ui/users";
import { FileCheckIcon } from "@/components/ui/file-check";
import { CogIcon } from "@/components/ui/cog";

// Pipeline flow for processing visualization
import { PipelineFlow, type PipelineStage } from "@/components/extraction/pipeline-flow";
import Image from "next/image";

type Step = "upload" | "segments" | "schema" | "config" | "processing";

// Supported image extensions for direct preview
const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.heic', '.heif'];

// Extensions that need server-side conversion to PDF for preview
const CONVERTIBLE_EXTENSIONS = ['.docx', '.xlsx', '.doc', '.xls', '.txt', '.rtf', '.csv'];

// Check if a file is an image that can be previewed
function isPreviewableImage(filename: string): boolean {
  const ext = filename.toLowerCase().slice(filename.lastIndexOf('.'));
  return IMAGE_EXTENSIONS.includes(ext);
}

// Check if file is a PDF
function isPDF(filename: string): boolean {
  return filename.toLowerCase().endsWith('.pdf');
}

// Check if file needs conversion (Office docs, text files)
function needsConversion(filename: string): boolean {
  const ext = filename.toLowerCase().slice(filename.lastIndexOf('.'));
  return CONVERTIBLE_EXTENSIONS.includes(ext);
}

export default function ExtractPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [currentStep, setCurrentStep] = useState<Step>("upload");
  const [file, setFile] = useState<File | null>(null);
  const [selectedSchema, setSelectedSchema] = useState<Schema | null>(null);
  const [ocrProvider, setOcrProvider] = useState<string>("");
  const [ocrModelConfig, setOcrModelConfig] = useState<Record<string, any>>({});
  const [llmProvider, setLlmProvider] = useState<string>("");
  /** When true, document-type suggestions must not overwrite the user's configure-step choice. */
  const userPickedOcrProviderRef = useRef(false);
  const userPickedLlmProviderRef = useRef(false);
  const [useAgents, setUseAgents] = useState<boolean>(false);
  const [isCreatingSchema, setIsCreatingSchema] = useState(false);
  const [schemaSearch, setSchemaSearch] = useState("");

  // Document type detection state
  const [detectedType, setDetectedType] = useState<DocumentTypeResult | null>(null);
  const [isDetecting, setIsDetecting] = useState(false);

  // Schema inference state for inline builder
  const [isInferringSchema, setIsInferringSchema] = useState(false);
  const [inferredFields, setInferredFields] = useState<SchemaField[]>([]);
  const [inferredSchemaName, setInferredSchemaName] = useState<string>("");
  const [inferredDocType, setInferredDocType] = useState<string>("");

  // Consensus extraction state
  const [enableConsensus, setEnableConsensus] = useState(false);
  const [consensusOcrProviders, setConsensusOcrProviders] = useState<string[]>([]);
  const [consensusLlmProviders, setConsensusLlmProviders] = useState<string[]>([]);

  // Advanced options state
  const [showAdvanced, setShowAdvanced] = useState(false);
  const [confidenceThreshold, setConfidenceThreshold] = useState([70]);
  const [enableFallback, setEnableFallback] = useState(true);
  const [parallelProcessing, setParallelProcessing] = useState(true);
  const [streamingMode, setStreamingMode] = useState(true);

  // Pipeline stage tracking
  const [pipelineStage, setPipelineStage] = useState<PipelineStage>("idle");

  // Image preview URL (for non-PDF files)
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);

  // Converted PDF for document preview (DOCX, XLSX, etc.)
  const [convertedPdfBlob, setConvertedPdfBlob] = useState<Blob | null>(null);
  const [isConverting, setIsConverting] = useState(false);
  const [conversionError, setConversionError] = useState<string | null>(null);

  // ============================================================================
  // Segmentation State - Multi-document PDF splitting
  // ============================================================================
  const [enableSegmentation, setEnableSegmentation] = useState(false);
  const [showSegmentationDialog, setShowSegmentationDialog] = useState(false);
  const [segmentationMode, setSegmentationMode] = useState<"homogeneous" | "heterogeneous">("homogeneous");
  const [segmentationExpectedTypes, setSegmentationExpectedTypes] = useState<string[]>([]);
  const [segmentationTypeInput, setSegmentationTypeInput] = useState("");
  const [segmentationLlmFallback, setSegmentationLlmFallback] = useState(false);
  const [segmentationConfidence, setSegmentationConfidence] = useState(0.6);
  const [segmentationProfileId, setSegmentationProfileId] = useState<string>("auto");
  const [advancedOptionsOpen, setAdvancedOptionsOpen] = useState(false);
  const [isAnalyzingSegments, setIsAnalyzingSegments] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [segmentationResult, setSegmentationResult] = useState<{
    success: boolean;
    segments: Array<{
      index: number;
      page_start: number;
      page_end: number;
      page_count: number;
      detected_type?: string;
      type_confidence: number;
      schema_id?: string;
      extraction_status: string;
    }>;
    boundaries: Array<{
      page_after: number;
      confidence: number;
      signals: string[];
      detection_method: string;
    }>;
    detection_method: string;
    total_pages: number;
    processing_time: number;
    llm_tokens_used: number;
    heuristic_only: boolean;
    // Cache IDs for reuse in extraction
    document_cache_id?: string;
    segmentation_config_hash?: string;
  } | null>(null);
  // Schema assignments for each segment (heterogeneous mode)
  const [segmentSchemas, setSegmentSchemas] = useState<Record<number, string>>({});
  // Apply same schema to all segments toggle
  const [applyToAllEnabled, setApplyToAllEnabled] = useState(false);
  // Currently selected segment for PDF preview navigation
  const [segmentPreviewPage, setSegmentPreviewPage] = useState<number>(1);

  // Segmented extraction job tracking (for polling until completion)
  const [segmentedJobId, setSegmentedJobId] = useState<string | null>(null);

  // Poll segmented job status until completion
  const { data: segmentedJob } = useQuery({
    queryKey: ["segmented-job", segmentedJobId],
    queryFn: () => api.getJob(segmentedJobId!),
    enabled: !!segmentedJobId,
    refetchInterval: (query) => {
      const jobData = query.state.data;
      if (!jobData) return 2000;
      // Stop polling when completed or failed
      if (jobData.status === "completed" || jobData.status === "failed") {
        return false;
      }
      return 2000; // Poll every 2 seconds
    },
  });

  // Navigate to results when segmented job completes
  useEffect(() => {
    if (segmentedJob && segmentedJobId) {
      if (segmentedJob.status === "completed" || segmentedJob.status === "failed") {
        console.log(`[Multi-doc] Job ${segmentedJobId} finished with status: ${segmentedJob.status}`);
        router.push(`/jobs/${segmentedJobId}`);
        setSegmentedJobId(null); // Clear the tracking state
      }
    }
  }, [segmentedJob, segmentedJobId, router]);

  // Create/revoke image preview URL when file changes
  useEffect(() => {
    if (file && isPreviewableImage(file.name)) {
      const url = URL.createObjectURL(file);
      setImagePreviewUrl(url);
      return () => {
        URL.revokeObjectURL(url);
        setImagePreviewUrl(null);
      };
    } else {
      setImagePreviewUrl(null);
    }
  }, [file]);

  // Convert documents (DOCX, XLSX, etc.) to PDF for preview
  useEffect(() => {
    if (file && needsConversion(file.name)) {
      setIsConverting(true);
      setConversionError(null);
      setConvertedPdfBlob(null);

      api.convertForPreview(file)
        .then((blob) => {
          setConvertedPdfBlob(blob);
          setIsConverting(false);
        })
        .catch((err) => {
          console.error("Document conversion failed:", err);
          setConversionError(err.message || "Failed to convert document");
          setIsConverting(false);
        });
    } else {
      setConvertedPdfBlob(null);
      setConversionError(null);
    }
  }, [file]);

  // Classifier setting (loaded from user settings API - NO hardcoded default)
  const [classifier, setClassifier] = useState<string>("");

  // Fetch user settings from API
  const { data: userSettings, isLoading: settingsLoading } = useQuery({
    queryKey: ["userSettings"],
    queryFn: () => api.getSettings(),
    staleTime: 30000, // Cache for 30 seconds
  });

  // Update classifier when user settings load - use settings value or server defaults
  useEffect(() => {
    if (userSettings) {
      const classifierValue = userSettings.settings?.document_classifier
        ?? userSettings.defaults?.document_classifier
        ?? "";
      setClassifier(classifierValue);
    }
  }, [userSettings]);

  const {
    startExtraction,
    job,
    isExtracting,
    progress,
    currentStep: processingStep,
    parts,
    error,
    reset: resetExtraction,
    // Agent events from the SAME WebSocket connection
    agentEvents,
    isAgentActive,
    clearAgentEvents,
  } = useExtraction();

  // Debug: log agent events
  console.log("[page.tsx] Agent events:", {
    useAgents,
    eventCount: agentEvents.length,
    isAgentActive,
    jobId: job?.id,
  });

  // Fetch schemas
  const { data: schemas = [] } = useQuery({
    queryKey: ["schemas"],
    queryFn: () => api.listSchemas(),
  });

  // Fetch providers
  const { data: providers } = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.getProviders(),
  });

  // Fetch segmentation profiles
  const { data: segmentationProfiles = [] } = useQuery({
    queryKey: ["segmentation-profiles"],
    queryFn: async (): Promise<SegmentationProfile[]> => {
      const res = await fetch(`${API_BASE_URL}/api/segmentation-profiles`, {
        headers: getAuthHeaders(),
      });
      if (!res.ok) throw new Error("Failed to fetch profiles");
      return res.json();
    },
  });

  const availableOcrProviders = providers?.ocr_providers?.filter(p => p.is_available) || [];
  const availableLlmProviders = providers?.llm_providers?.filter(p => p.is_available) || [];

  /** Azure DI etc.: merge provider default model when UI left blank (matches single-doc extract). */
  const getEffectiveOcrModelConfig = (): Record<string, string> => {
    const selectedOcrProvider = availableOcrProviders.find(
      (p) => p.name === (ocrProvider || availableOcrProviders[0]?.name)
    );
    const modelConfig = selectedOcrProvider?.config_options?.model as { default?: string } | undefined;
    const hasModelOptions = modelConfig && typeof modelConfig.default === "string";
    if (hasModelOptions && (ocrModelConfig?.model == null || ocrModelConfig.model === "")) {
      return { ...ocrModelConfig, model: modelConfig.default };
    }
    return { ...ocrModelConfig };
  };

  // Set defaults from user settings when providers load
  useEffect(() => {
    if (userSettings && availableOcrProviders.length > 0 && !ocrProvider) {
      // Use user's default_ocr_provider setting, or fall back to first available
      const defaultOcr = userSettings.settings?.default_ocr_provider
        ?? userSettings.defaults?.default_ocr_provider;
      if (defaultOcr && availableOcrProviders.some(p => p.name === defaultOcr)) {
        setOcrProvider(defaultOcr);
      } else if (availableOcrProviders[0]?.name) {
        setOcrProvider(availableOcrProviders[0].name);
      }
    }
    if (userSettings && availableLlmProviders.length > 0 && !llmProvider) {
      // Use user's default_llm_provider setting, or fall back to first available
      const defaultLlm = userSettings.settings?.default_llm_provider
        ?? userSettings.defaults?.default_llm_provider;
      if (defaultLlm && availableLlmProviders.some(p => p.name === defaultLlm)) {
        setLlmProvider(defaultLlm);
      } else if (availableLlmProviders[0]?.name) {
        setLlmProvider(availableLlmProviders[0].name);
      }
    }
  }, [availableOcrProviders, availableLlmProviders, userSettings, ocrProvider, llmProvider]);

  // Track pipeline stage based on extraction progress
  useEffect(() => {
    // Reset to idle when not processing
    if (!isExtracting && currentStep !== "processing") {
      setPipelineStage("idle");
      return;
    }

    // Handle error state
    if (error) {
      setPipelineStage("failed");
      return;
    }

    const step = processingStep.toLowerCase();

    // Backend status messages:
    // "Starting extraction...", "Analyzing document..." - configuration
    // "Running OCR..." - ocr
    // "Extracting {part_name}..." - llm
    // "Completed" - completed

    if (step.includes("start") || step.includes("initializ") || step.includes("analyz")) {
      setPipelineStage("configuration");
    } else if (step.includes("ocr") || step.includes("scanning") || step.includes("running ocr")) {
      setPipelineStage(enableConsensus ? "ocr_consensus" : "ocr");
    } else if (step.includes("extract")) {
      setPipelineStage(enableConsensus ? "llm_consensus" : "llm");
    } else if (step.includes("validat") || step.includes("check") || step.includes("threshold")) {
      setPipelineStage(enableConsensus ? "comparison" : "validation");
    } else if (step.includes("prepar") || step.includes("final") || step.includes("saving")) {
      setPipelineStage("preparing");
    } else if (step.includes("complet") || step.includes("done") || step.includes("finish")) {
      setPipelineStage("completed");
    }
    // Keep current stage if no match (don't reset to idle during processing)
  }, [processingStep, isExtracting, currentStep, enableConsensus, error]);

  const onDrop = useCallback(async (acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      const uploadedFile = acceptedFiles[0];
      setUploadError(null);
      if (uploadedFile.size === 0) {
        setFile(null);
        setUploadError("Cannot process empty document.");
        return;
      }
      userPickedOcrProviderRef.current = false;
      userPickedLlmProviderRef.current = false;
      setFile(uploadedFile);

      if (enableSegmentation) {
        // Multi-doc mode: Go to segments step and analyze
        setCurrentStep("segments");
        setIsAnalyzingSegments(true);
        setSegmentationResult(null);
        try {
          const result = await api.analyzeSegments(
            uploadedFile,
            segmentationMode,
            segmentationExpectedTypes,
            segmentationLlmFallback,
            segmentationConfidence,
            ocrProvider || undefined,
            segmentationProfileId,
            getEffectiveOcrModelConfig()
          );
          setSegmentationResult(result);
          // Auto-assign schemas based on detected types
          if (result.segments) {
            const assignments: Record<number, string> = {};
            result.segments.forEach((seg) => {
              if (seg.detected_type) {
                const matchingSchema = schemas.find(
                  (s) => s.doc_type === seg.detected_type
                );
                if (matchingSchema) {
                  assignments[seg.index] = matchingSchema.id;
                }
              }
            });
            setSegmentSchemas(assignments);
          }
        } catch (err) {
          console.error("Segment analysis failed:", err);
        } finally {
          setIsAnalyzingSegments(false);
        }
      } else {
        // Single-doc mode: Go to schema step
        setCurrentStep("schema");

        // Auto-detect document type using user's settings
        setIsDetecting(true);
        setDetectedType(null);
        try {
          console.log(`Detecting document type (using user settings)`);
          const result = await api.detectDocumentType(uploadedFile);
          setDetectedType(result);
          if (result.classifier_used) {
            setClassifier(result.classifier_used);
          }
          if (result.primary_type) {
            setSchemaSearch(result.primary_type.replace(/_/g, " "));
          }
          if (result.suggested_ocr?.provider) {
            setOcrProvider((prev) =>
              userPickedOcrProviderRef.current ? prev : result.suggested_ocr!.provider
            );
          }
          if (result.suggested_llm?.provider) {
            setLlmProvider((prev) =>
              userPickedLlmProviderRef.current ? prev : result.suggested_llm!.provider
            );
          }
        } catch (err) {
          console.error("Document type detection failed:", err);
        } finally {
          setIsDetecting(false);
        }
      }
    }
  }, [enableSegmentation, segmentationMode, segmentationExpectedTypes, segmentationLlmFallback, segmentationConfidence, segmentationProfileId, ocrProvider, ocrModelConfig, availableOcrProviders, schemas]);

  const onDropRejected = useCallback((fileRejections: FileRejection[]) => {
    if (!fileRejections.length) return;
    setFile(null);
    const first = fileRejections[0];
    const code = first.errors[0]?.code;
    if (code === "file-invalid-type") {
      setUploadError("File format not supported.");
      return;
    }
    if (code === "too-many-files") {
      setUploadError("Please upload only one file.");
      return;
    }
    setUploadError("Unable to upload this file.");
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected,
    accept: {
      // PDF
      "application/pdf": [".pdf"],
      // Images
      "image/jpeg": [".jpg", ".jpeg"],
      "image/png": [".png"],
      "image/tiff": [".tiff", ".tif"],
      "image/bmp": [".bmp"],
      "image/webp": [".webp"],
      "image/heic": [".heic"],
      "image/heif": [".heif"],
      "image/gif": [".gif"],
      // Documents
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "application/msword": [".doc"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/vnd.ms-excel": [".xls"],
      "text/plain": [".txt"],
      "text/csv": [".csv"],
      "application/rtf": [".rtf"],
    },
    maxFiles: 1,
  });

  const handleSchemaSelect = (schema: Schema) => {
    setSelectedSchema(schema);
    setCurrentStep("config");
  };

  const handleStartExtraction = async () => {
    // Validate based on mode
    if (!file) return;

    if (enableSegmentation) {
      // Multi-doc mode: check all segments have schemas
      if (!segmentationResult || Object.keys(segmentSchemas).length !== segmentationResult.segments.length) {
        console.error("Not all segments have schemas assigned");
        return;
      }
    } else {
      // Single-doc mode: check selectedSchema
      if (!selectedSchema) return;
    }

    setPipelineStage("configuration");
    setCurrentStep("processing");

    const effectiveOcrModelConfig = getEffectiveOcrModelConfig();

    // Check if segmentation is enabled and we have analyzed segments
    if (enableSegmentation && segmentationResult && segmentationResult.segments.length > 0) {
      // Use segmented extraction API
      console.log("[Multi-doc] Starting segmented extraction with schemas:", segmentSchemas);
      console.log("[Multi-doc] Cache IDs - document:", segmentationResult.document_cache_id, "config:", segmentationResult.segmentation_config_hash);
      try {
        const job = await api.startSegmentedExtraction(
          file,
          segmentSchemas,
          segmentationMode,
          segmentationExpectedTypes,
          segmentationLlmFallback,
          segmentationConfidence,
          ocrProvider || availableOcrProviders[0]?.name,
          llmProvider || availableLlmProviders[0]?.name,
          useAgents,
          segmentationProfileId,
          segmentationResult.document_cache_id,  // Pass cached OCR ID
          segmentationResult.segmentation_config_hash,  // Pass cached segmentation config
          effectiveOcrModelConfig
        );
        console.log("[Multi-doc] Job created:", job.id);
        // Don't navigate immediately - start polling and wait for completion
        setSegmentedJobId(job.id);
        // Stay on processing step - the useEffect will navigate when job completes
      } catch (error) {
        console.error("[Multi-doc] Segmented extraction failed:", error);
        // Reset to config step on failure
        setCurrentStep("config");
        setPipelineStage("idle");
      }
    } else {
      // Use standard extraction
      await startExtraction(
        file,
        selectedSchema.doc_type,
        ocrProvider || availableOcrProviders[0]?.name,
        llmProvider || availableLlmProviders[0]?.name,
        selectedSchema.id,
        useAgents,
        effectiveOcrModelConfig
      );
      // Don't immediately go to results - wait for WebSocket completion
    }
  };

  // Watch for extraction completion and navigate to job detail page
  useEffect(() => {
    if (currentStep === "processing" && !isExtracting && job) {
      console.log(`[Navigation] Job ${job.id}: status=${job.status}, isExtracting=${isExtracting}`);
      if (job.status === "completed" || job.status === "failed") {
        // Extraction finished - navigate to job detail page
        console.log(`[Navigation] Navigating to /jobs/${job.id}`);
        router.push(`/jobs/${job.id}`);
      }
    }
  }, [isExtracting, job, currentStep, router]);

  // Convert JSON schema to SchemaField[] for the builder
  const jsonSchemaToFields = (schema: Record<string, unknown>): SchemaField[] => {
    const properties = schema.properties as Record<string, Record<string, unknown>> || {};
    const required = (schema.required as string[]) || [];

    return Object.entries(properties).map(([name, prop], index) => {
      const field: SchemaField = {
        id: `field-${index}-${Date.now()}-${Math.random()}`,
        name,
        type: (prop.type as SchemaField["type"]) || "string",
        required: required.includes(name),
        description: prop.description as string | undefined,
      };

      if (prop.type === "object" && prop.properties) {
        field.children = jsonSchemaToFields(prop as Record<string, unknown>);
      }

      if (prop.type === "array" && prop.items) {
        const items = prop.items as Record<string, unknown>;
        if (items.type === "object" && items.properties) {
          field.children = jsonSchemaToFields(items);
        }
      }

      return field;
    });
  };

  // Generate schema from document
  // Always uses user's document_classifier and fallback_ocr settings from the backend
  // (These are separate from extraction settings - default_ocr_provider and default_llm_provider)
  const handleGenerateSchema = async () => {
    if (!file) return;

    setIsInferringSchema(true);
    try {
      // Schema inference uses document_classifier and fallback_ocr settings, NOT extraction providers
      // Always pass undefined to let backend use the correct settings
      const result = await api.inferSchema(
        file,
        undefined,  // Let backend use fallback_ocr setting
        undefined   // Let backend use document_classifier setting
      );
      const fields = jsonSchemaToFields(result.json_schema);
      setInferredFields(fields);
      setInferredSchemaName(result.schema_name || "");
      setInferredDocType(result.document_type?.replace(/_/g, " ") || "");
    } catch (err) {
      console.error("Schema inference failed:", err);
    } finally {
      setIsInferringSchema(false);
    }
  };

  const handleReset = () => {
    userPickedOcrProviderRef.current = false;
    userPickedLlmProviderRef.current = false;
    setFile(null);
    setSelectedSchema(null);
    setOcrProvider("");
    setLlmProvider("");
    setCurrentStep("upload");
    setDetectedType(null);
    setIsDetecting(false);
    setSchemaSearch("");
    setEnableConsensus(false);
    setConsensusOcrProviders([]);
    setConsensusLlmProviders([]);
    setIsInferringSchema(false);
    setInferredFields([]);
    setInferredSchemaName("");
    setInferredDocType("");
    resetExtraction(); // This also clears agent events
  };

  // Get step order based on whether multi-doc is enabled
  const getStepOrder = (): Step[] => {
    if (enableSegmentation) {
      return ["upload", "segments", "config", "processing"];
    }
    return ["upload", "schema", "config", "processing"];
  };

  // Navigate to previous step
  const handleGoBack = () => {
    const stepOrder = getStepOrder();
    const currentIndex = stepOrder.indexOf(currentStep);
    if (currentIndex > 0) {
      // Don't go back from processing (extraction in progress)
      if (currentStep === "processing" && (isExtracting || segmentedJobId)) return;
      setCurrentStep(stepOrder[currentIndex - 1]);
    }
  };

  // Navigate to a specific step (only if it's a previous/completed step)
  const handleStepClick = (stepId: Step) => {
    const stepOrder = getStepOrder();
    const targetIndex = stepOrder.indexOf(stepId);
    const currentIndex = stepOrder.indexOf(currentStep);

    // Can only navigate to previous steps, not forward
    // Can't navigate while processing
    if (currentStep === "processing" && (isExtracting || segmentedJobId)) return;

    // Can navigate to completed steps or current step
    if (targetIndex < currentIndex) {
      // Reset downstream selections if going back
      if (stepId === "upload") {
        handleReset();
        return;
      }
      if (stepId === "schema") {
        setSelectedSchema(null);
      }
      if (stepId === "segments") {
        setSegmentSchemas({});
      }
      setCurrentStep(stepId);
    }
  };

  // Check if a step is clickable
  const isStepClickable = (stepIndex: number) => {
    if (currentStep === "processing" && (isExtracting || segmentedJobId)) return false;
    return stepIndex < currentStepIndex;
  };

  const copyResults = async () => {
    if (parts.length > 0) {
      const allData = parts.reduce((acc, part) => {
        if (part.extracted_data) {
          acc[part.part_name] = part.extracted_data;
        }
        return acc;
      }, {} as Record<string, unknown>);
      await navigator.clipboard.writeText(JSON.stringify(allData, null, 2));
    }
  };

  // Dynamic steps based on whether multi-doc mode is enabled
  const steps = enableSegmentation
    ? [
        { id: "upload", label: "Upload" },
        { id: "segments", label: "Select Schema" },
        { id: "config", label: "Configure" },
        { id: "processing", label: "Process" },
      ]
    : [
        { id: "upload", label: "Upload" },
        { id: "schema", label: isCreatingSchema ? "Create Schema" : "Select Schema" },
        { id: "config", label: "Configure" },
        { id: "processing", label: "Process" },
      ];

  const currentStepIndex = steps.findIndex(s => s.id === currentStep);

  // Fetch recent jobs for dashboard
  const { data: recentJobsData } = useQuery({
    queryKey: ["jobs", "recent"],
    queryFn: () => api.listJobs({ limit: 5 }),
  });
  const recentJobs = recentJobsData?.jobs || [];

  // Show dashboard-style upload page
  if (currentStep === "upload") {
    return (
      <div className="h-full p-6">
        <div className="max-w-6xl mx-auto">
          {/* Header */}
          <div className="mb-6">
            <h1 className="text-2xl font-semibold mb-1">Document Extraction</h1>
            <p className="text-muted-foreground">
              Upload documents to extract structured data using AI
            </p>
          </div>

          {/* Main Grid Layout */}
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
            {/* Upload Section - Takes 2 columns */}
            <div className="lg:col-span-2">
              <Card className="h-full">
                <CardHeader className="pb-3">
                  <CardTitle className="text-base font-medium">Upload Document</CardTitle>
                </CardHeader>
                <CardContent>
                  <div
                    {...getRootProps()}
                    className={cn(
                      "border-2 border-dashed rounded-xl p-8 text-center cursor-pointer transition-all",
                      isDragActive
                        ? "border-primary bg-primary/5"
                        : "border-border hover:border-primary/50 hover:bg-muted/30"
                    )}
                  >
                    <input {...getInputProps()} />
                    <div className={cn(
                      "w-14 h-14 mx-auto mb-4 rounded-xl flex items-center justify-center",
                      isDragActive ? "bg-primary text-primary-foreground" : "bg-muted"
                    )}>
                      <UploadIcon size={24} />
                    </div>
                    <h3 className="font-medium mb-1">
                      {isDragActive ? "Drop here" : "Drop your document here"}
                    </h3>
                    <p className="text-sm text-muted-foreground mb-4">
                      or click to browse from your computer
                    </p>
                    {/* Movie Credits Style Format Display with Random Highlighting */}
                    <RandomHighlightText
                      className="mt-6 max-w-md mx-auto"
                      highlightInterval={80}
                      highlightDuration={350}
                      maxConcurrentHighlights={4}
                      rows={[
                        {
                          words: ["PDF", "PNG", "JPG", "TIFF", "HEIC", "DOCX", "XLSX"],
                          className: "text-sm font-medium text-foreground/90 gap-2",
                          dotClassName: "w-1 h-1 bg-foreground/40",
                        },
                        {
                          words: ["BMP", "GIF", "WEBP", "DOC", "XLS", "TXT", "CSV"],
                          className: "text-xs font-medium text-foreground/70 gap-2",
                          dotClassName: "w-1 h-1 bg-foreground/30",
                        },
                        {
                          words: ["Invoices", "Receipts", "Contracts", "Purchase Orders", "Bill of Entry"],
                          className: "text-[11px] text-muted-foreground/90 gap-2",
                          dotClassName: "w-1 h-1 bg-muted-foreground/25",
                        },
                        {
                          words: ["Shipping Bills", "Customs Documents", "Trade Documents", "Bank Statements", "Tax Forms"],
                          className: "text-[10px] text-muted-foreground/75 gap-2",
                          dotClassName: "w-0.5 h-0.5 bg-muted-foreground/20",
                        },
                        {
                          words: ["Financial Statements", "Payslips", "Credit Reports", "Loan Documents", "Insurance Claims"],
                          className: "text-[9px] text-muted-foreground/60 gap-1.5",
                          dotClassName: "w-0.5 h-0.5 bg-muted-foreground/15",
                        },
                        {
                          words: ["Legal Filings", "NDAs", "Employment Contracts", "Lease Agreements", "Utility Bills"],
                          className: "text-[9px] text-muted-foreground/50 gap-1.5",
                          dotClassName: "w-0.5 h-0.5 bg-muted-foreground/10",
                        },
                        {
                          words: ["ID Documents", "Certificates", "Medical Records", "Lab Reports", "Research Papers"],
                          className: "text-[8px] text-muted-foreground/40 gap-1.5",
                          dotClassName: "w-0.5 h-0.5 bg-muted-foreground/10",
                        },
                        {
                          words: ["Passports", "Licenses", "Permits", "Visas", "Declarations", "Manifests", "Vouchers", "Tickets"],
                          className: "text-[7px] text-muted-foreground/30 gap-1",
                          dotClassName: "w-0.5 h-0.5 bg-muted-foreground/5",
                        },
                        {
                          words: ["Waivers", "Affidavits", "Deeds", "Transcripts", "Warranties", "Bonds", "Policies", "Reports", "Forms", "& more..."],
                          className: "text-[6px] text-muted-foreground/20 gap-1",
                          dotClassName: "w-px h-px bg-muted-foreground/5",
                        },
                      ]}
                    />
                  </div>

                  {uploadError && (
                    <div className="mt-4 flex items-center gap-2 rounded-md border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                      <AlertCircle className="h-4 w-4" />
                      <span>{uploadError}</span>
                    </div>
                  )}

                  {/* Quick Stats Row */}
                  <div className="grid grid-cols-3 gap-4 mt-6">
                    <div className="text-center p-3 bg-muted/30 rounded-lg">
                      <div className="text-2xl font-semibold">{schemas.length}</div>
                      <div className="text-xs text-muted-foreground">Schemas</div>
                    </div>
                    <div className="text-center p-3 bg-muted/30 rounded-lg">
                      <div className="text-2xl font-semibold">{availableOcrProviders.length}</div>
                      <div className="text-xs text-muted-foreground">OCR Providers</div>
                    </div>
                    <div className="text-center p-3 bg-muted/30 rounded-lg">
                      <div className="text-2xl font-semibold">{availableLlmProviders.length}</div>
                      <div className="text-xs text-muted-foreground">LLM Providers</div>
                    </div>
                  </div>
                </CardContent>
              </Card>
            </div>

            {/* Sidebar - Recent Jobs & Quick Actions */}
            <div className="space-y-6">
              {/* Multi-Document Mode */}
              <Card className={cn(enableSegmentation && "border-violet-500/30 bg-violet-500/5")}>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                      <LayersIcon size={16} />
                      Multi-Document Mode
                      <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400 border-violet-300 dark:border-violet-700">
                        Beta
                      </Badge>
                    </CardTitle>
                    <Switch
                      checked={enableSegmentation}
                      onCheckedChange={(checked) => {
                        if (checked) {
                          setShowSegmentationDialog(true);
                        } else {
                          setEnableSegmentation(false);
                          setSegmentationResult(null);
                          setSegmentSchemas({});
                          setSegmentationExpectedTypes([]);
                        }
                      }}
                    />
                  </div>
                  <CardDescription className="text-xs">
                    Extract from PDFs containing multiple documents
                  </CardDescription>
                </CardHeader>
                {enableSegmentation && (
                  <CardContent className="space-y-3 pt-0">
                    <Separator />
                    <div className="flex items-center justify-between text-xs">
                      <div className="flex items-center gap-2">
                        <Badge variant="secondary" className="bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400">
                          {segmentationMode === "heterogeneous"
                            ? "Mixed Types"
                            : segmentationProfileId !== "auto"
                              ? segmentationProfiles.find(p => p.name === segmentationProfileId)?.display_name || segmentationProfileId
                              : "Auto-detect"}
                        </Badge>
                        {segmentationMode === "heterogeneous" && segmentationExpectedTypes.length > 0 && (
                          <span className="text-muted-foreground truncate max-w-[120px]">
                            {segmentationExpectedTypes.join(", ")}
                          </span>
                        )}
                        {segmentationLlmFallback && (
                          <Badge variant="outline" className="text-xs">
                            AI
                          </Badge>
                        )}
                      </div>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-6 text-xs text-violet-600 hover:text-violet-700 hover:bg-violet-100 dark:text-violet-400 dark:hover:bg-violet-900/30"
                        onClick={() => setShowSegmentationDialog(true)}
                      >
                        Edit
                      </Button>
                    </div>
                  </CardContent>
                )}
              </Card>

              {/* Recent Jobs */}
              <Card>
                <CardHeader className="pb-3">
                  <div className="flex items-center justify-between">
                    <CardTitle className="text-base font-medium">Recent Jobs</CardTitle>
                    <Button variant="ghost" size="sm" asChild>
                      <a href="/jobs">View all</a>
                    </Button>
                  </div>
                </CardHeader>
                <CardContent className="p-0">
                  {recentJobs.length === 0 ? (
                    <div className="p-6 text-center text-muted-foreground">
                      <FileTextIcon size={32} className="mx-auto mb-2 opacity-50" />
                      <p className="text-sm">No recent jobs</p>
                    </div>
                  ) : (
                    <div className="divide-y">
                      {recentJobs.slice(0, 4).map((job) => (
                        <div key={job.id} className="px-4 py-3 hover:bg-muted/30 transition-colors">
                          <div className="flex items-center justify-between">
                            <div className="min-w-0 flex-1">
                              <p className="text-sm font-medium truncate">{job.document_name}</p>
                              <p className="text-xs text-muted-foreground">
                                {job.doc_type.replace(/_/g, " ")}
                              </p>
                            </div>
                            {job.status === "completed" ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-emerald-100 text-emerald-700 dark:bg-emerald-500/20 dark:text-emerald-400 ml-2">
                                <CheckCircle2 className="w-3 h-3" />
                                {job.status}
                              </span>
                            ) : job.status === "failed" ? (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-red-100 text-red-700 dark:bg-red-500/20 dark:text-red-400 ml-2">
                                <AlertCircle className="w-3 h-3" />
                                {job.status}
                              </span>
                            ) : (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400 ml-2">
                                <Timer className="w-3 h-3" />
                                {job.status}
                              </span>
                            )}
                          </div>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>

              {/* Quick Actions */}
              <Card>
                <CardHeader className="pb-3">
                  <CardTitle className="text-base font-medium">Quick Actions</CardTitle>
                </CardHeader>
                <CardContent className="space-y-2">
                  <Button variant="outline" className="w-full justify-start" asChild>
                    <a href="/schemas">
                      <FileTextIcon size={16} className="mr-2" />
                      Manage Schemas
                    </a>
                  </Button>
                  <Button variant="outline" className="w-full justify-start" asChild>
                    <a href="/providers">
                      <ZapIcon size={16} className="mr-2" />
                      Configure Providers
                    </a>
                  </Button>
                  <Button variant="outline" className="w-full justify-start" asChild>
                    <a href="/jobs">
                      <ClockIcon size={16} className="mr-2" />
                      View All Jobs
                    </a>
                  </Button>
                </CardContent>
              </Card>
            </div>
          </div>
        </div>

        {/* Segmentation Options Dialog */}
        <Dialog open={showSegmentationDialog} onOpenChange={setShowSegmentationDialog}>
          <DialogContent className="sm:max-w-[500px]">
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <LayersIcon size={20} className="text-primary" />
                Multi-Document Settings
              </DialogTitle>
              <DialogDescription>
                Configure extraction for PDFs with multiple documents
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-6 py-4">
              {/* Main Document Type Selection */}
              <div className="space-y-3">
                <Label className="text-sm font-medium">Document Type</Label>
                <Select
                  value={segmentationProfileId}
                  onValueChange={(value) => {
                    setSegmentationProfileId(value);
                    // When selecting a specific profile, auto-set to homogeneous mode
                    if (value !== "auto") {
                      setSegmentationMode("homogeneous");
                    }
                  }}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select document type" />
                  </SelectTrigger>
                  <SelectContent>
                    {segmentationProfiles.length > 0 && (
                      <>
                        <div className="px-2 py-1.5 text-xs font-medium text-muted-foreground">
                          Segmentation Profiles
                        </div>
                        {segmentationProfiles.map((profile) => (
                          <SelectItem key={profile.id} value={profile.name}>
                            {profile.display_name}
                          </SelectItem>
                        ))}
                        <Separator className="my-1" />
                      </>
                    )}
                    <SelectItem value="auto">Auto-detect</SelectItem>
                  </SelectContent>
                </Select>
                {segmentationProfileId === "auto" ? (
                  <div className="flex items-start gap-2 p-2 rounded-md bg-amber-50 dark:bg-amber-950/30 border border-amber-200 dark:border-amber-800">
                    <Info className="h-4 w-4 text-amber-600 dark:text-amber-500 mt-0.5 flex-shrink-0" />
                    <p className="text-xs text-amber-700 dark:text-amber-400">
                      For better results, specify expected document types in Advanced options.
                    </p>
                  </div>
                ) : (
                  <p className="text-xs text-muted-foreground">
                    Using profile settings from Segmentation Lab.
                  </p>
                )}
              </div>

              {/* Advanced Options - Collapsible */}
              <Collapsible open={advancedOptionsOpen} onOpenChange={setAdvancedOptionsOpen}>
                <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
                  <ChevronRight className={cn(
                    "h-4 w-4 transition-transform",
                    advancedOptionsOpen && "rotate-90"
                  )} />
                  Advanced options
                </CollapsibleTrigger>
                <CollapsibleContent className="mt-4 space-y-4">
                  <div className="rounded-lg border p-4 space-y-4">
                    {/* Document Mode Toggle */}
                    <div className="space-y-3">
                      <Label className="text-sm font-medium">Document Mode</Label>
                      <div className="grid grid-cols-2 gap-3">
                        <button
                          type="button"
                          onClick={() => setSegmentationMode("homogeneous")}
                          className={cn(
                            "p-3 rounded-lg border text-left transition-all",
                            segmentationMode === "homogeneous"
                              ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                              : "border-muted hover:border-muted-foreground/50"
                          )}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <LayersIcon size={14} className="text-primary" />
                            <span className="font-medium text-sm">Same Type</span>
                          </div>
                          <p className="text-xs text-muted-foreground">
                            All docs are {segmentationProfileId !== "auto" ? segmentationProfiles.find(p => p.name === segmentationProfileId)?.display_name?.toLowerCase() + "s" : "the same type"}
                          </p>
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setSegmentationMode("heterogeneous");
                            setSegmentationProfileId("auto");
                          }}
                          className={cn(
                            "p-3 rounded-lg border text-left transition-all",
                            segmentationMode === "heterogeneous"
                              ? "border-primary bg-primary/5 ring-1 ring-primary/20"
                              : "border-muted hover:border-muted-foreground/50"
                          )}
                        >
                          <div className="flex items-center gap-2 mb-1">
                            <ZapIcon size={14} className="text-primary" />
                            <span className="font-medium text-sm">Mixed Types</span>
                          </div>
                          <p className="text-xs text-muted-foreground">
                            Invoice + receipt + certificate...
                          </p>
                        </button>
                      </div>
                    </div>

                    {/* Expected Document Types - Only shown for Mixed Types mode */}
                    {segmentationMode === "heterogeneous" && (
                      <div className="space-y-3">
                        <Label className="text-sm font-medium">
                          Expected Document Types
                        </Label>
                        <p className="text-xs text-muted-foreground -mt-1">
                          Type and press Enter to add document types.
                        </p>
                        <div className="flex flex-wrap gap-2 mb-2">
                          {segmentationExpectedTypes.map((type) => (
                            <Badge
                              key={type}
                              variant="secondary"
                              className="text-xs cursor-pointer hover:bg-destructive/20 transition-colors"
                              onClick={() =>
                                setSegmentationExpectedTypes((prev) =>
                                  prev.filter((t) => t !== type)
                                )
                              }
                            >
                              {type}
                              <XIcon size={12} className="ml-1" />
                            </Badge>
                          ))}
                        </div>
                        <Input
                          placeholder="e.g., invoice, receipt, packing_list..."
                          value={segmentationTypeInput}
                          onChange={(e) => setSegmentationTypeInput(e.target.value)}
                          onKeyDown={(e) => {
                            if (e.key === "Enter" && segmentationTypeInput.trim()) {
                              e.preventDefault();
                              const newType = segmentationTypeInput.trim().toLowerCase().replace(/\s+/g, "_");
                              if (!segmentationExpectedTypes.includes(newType)) {
                                setSegmentationExpectedTypes((prev) => [...prev, newType]);
                              }
                              setSegmentationTypeInput("");
                            }
                          }}
                        />
                      </div>
                    )}

                    {/* LLM Fallback Toggle */}
                    <div className="flex items-center justify-between p-3 rounded-lg bg-muted/30">
                      <div className="space-y-0.5">
                        <span className="text-sm font-medium">Use AI for uncertain boundaries</span>
                        <p className="text-xs text-muted-foreground">
                          ~$0.001/doc
                        </p>
                      </div>
                      <Switch
                        checked={segmentationLlmFallback}
                        onCheckedChange={setSegmentationLlmFallback}
                      />
                    </div>
                  </div>
                </CollapsibleContent>
              </Collapsible>
            </div>

            <DialogFooter>
              <Button
                variant="outline"
                onClick={() => {
                  setShowSegmentationDialog(false);
                  if (!enableSegmentation) {
                    // User closed without confirming, reset
                    setSegmentationMode("homogeneous");
                    setSegmentationExpectedTypes([]);
                    setSegmentationLlmFallback(false);
                    setSegmentationProfileId("auto");
                    setAdvancedOptionsOpen(false);
                  }
                }}
              >
                Cancel
              </Button>
              <Button
                onClick={() => {
                  setEnableSegmentation(true);
                  setShowSegmentationDialog(false);
                }}
              >
                <CheckIcon size={16} className="mr-2" />
                Enable Multi-Doc
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    );
  }

  // Rest of the flow (schema, config, processing, results)
  return (
    <div className="h-full flex flex-col">
      {/* Page Header with Steps */}
      <div className="border-b border-border px-6 py-4 bg-card/50 backdrop-blur-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            {/* Back Button */}
            <Button
              variant="outline"
              size="icon"
              onClick={handleGoBack}
              disabled={currentStepIndex === 0 || (currentStep === "processing" && (isExtracting || !!segmentedJobId))}
              className="h-8 w-8"
            >
              <ChevronLeft className="w-4 h-4" />
            </Button>
            <div>
              <h1 className="text-xl font-semibold">Extract Document</h1>
              <p className="text-sm text-muted-foreground">
                {file?.name}
              </p>
            </div>
          </div>
          <Button variant="ghost" size="icon" onClick={handleReset} className="h-8 w-8">
            <XIcon size={16} />
          </Button>
        </div>

        {/* Step Indicator - Compact & Clickable */}
        <div className="flex items-center gap-1">
          {steps.map((step, index) => (
            <div key={step.id} className="flex items-center">
              <button
                type="button"
                onClick={() => handleStepClick(step.id as Step)}
                disabled={!isStepClickable(index)}
                className={cn(
                  "flex items-center justify-center w-7 h-7 rounded-full text-xs font-medium transition-all",
                  index < currentStepIndex
                    ? "bg-primary text-primary-foreground cursor-pointer hover:ring-2 hover:ring-primary/30"
                    : index === currentStepIndex
                    ? "bg-primary text-primary-foreground cursor-default"
                    : "bg-muted text-muted-foreground cursor-default",
                  isStepClickable(index) && "hover:scale-105"
                )}
              >
                {index < currentStepIndex ? (
                  <CheckIcon size={14} />
                ) : (
                  index + 1
                )}
              </button>
              <button
                type="button"
                onClick={() => handleStepClick(step.id as Step)}
                disabled={!isStepClickable(index)}
                className={cn(
                  "ml-1.5 text-xs hidden sm:inline transition-colors",
                  index === currentStepIndex
                    ? "text-foreground font-medium cursor-default"
                    : index < currentStepIndex
                    ? "text-muted-foreground cursor-pointer hover:text-foreground"
                    : "text-muted-foreground cursor-default"
                )}
              >
                {step.label}
              </button>
              {index < steps.length - 1 && (
                <ChevronRight className="w-3.5 h-3.5 mx-1 text-muted-foreground" />
              )}
            </div>
          ))}
        </div>
      </div>

      {/* Main Content */}
      <div className={cn(
        "flex-1 overflow-hidden",
        isCreatingSchema ? "" : currentStep === "segments" ? "p-6" : "overflow-auto p-6"
      )}>
        {/* Step 2a: Segments (Multi-doc mode) */}
        {currentStep === "segments" && (
          <div className="h-full flex flex-col overflow-hidden">
            {/* Header */}
            <div className="flex items-center justify-between mb-4 flex-shrink-0">
              <div>
                <h2 className="text-lg font-semibold mb-1">Document Segments</h2>
                <p className="text-sm text-muted-foreground">
                  {isAnalyzingSegments
                    ? "Analyzing document for multiple segments..."
                    : segmentationResult
                    ? `Found ${segmentationResult.segments.length} documents in this file`
                    : "Select a schema for each document segment"}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant={applyToAllEnabled ? "secondary" : "outline"}
                  size="sm"
                  onClick={() => setApplyToAllEnabled(!applyToAllEnabled)}
                  className={cn(
                    "gap-2",
                    applyToAllEnabled && "bg-primary/10 border-primary/30"
                  )}
                >
                  <LayersIcon size={14} />
                  Apply to All
                  {applyToAllEnabled && <CheckIcon size={14} className="text-primary" />}
                </Button>
                <Button onClick={() => {
                  setIsCreatingSchema(true);
                  setCurrentStep("schema");
                }}>
                  <PlusIcon size={16} className="mr-2" />
                  Create Schema
                </Button>
              </div>
            </div>

            {/* Loading State */}
            {isAnalyzingSegments && (
              <div className="flex-1 flex flex-col items-center justify-center">
                <div className="relative">
                  <div className="w-16 h-16 rounded-full border-4 border-primary/20 animate-pulse" />
                  <div className="absolute inset-0 flex items-center justify-center">
                    <Loader2 className="w-8 h-8 text-primary animate-spin" />
                  </div>
                </div>
                <p className="mt-4 text-sm text-muted-foreground animate-pulse">
                  Analyzing document segments...
                </p>
              </div>
            )}

            {/* Segments Display */}
            {!isAnalyzingSegments && segmentationResult && segmentationResult.success && (
              <div className="flex-1 grid grid-cols-1 lg:grid-cols-2 gap-4 min-h-0 overflow-hidden">
                {/* Left: Segment List */}
                <div className="flex flex-col min-h-0 overflow-hidden">
                  {/* Visual Timeline - Fixed at top */}
                  <Card className="flex-shrink-0 mb-4">
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm font-medium flex items-center gap-2">
                          <LayersIcon size={16} />
                          Page Distribution
                        </CardTitle>
                        <div className="flex items-center gap-2 text-xs text-muted-foreground">
                          <span>{segmentationResult.total_pages} pages</span>
                          <span>•</span>
                          <span>{segmentationResult.processing_time.toFixed(2)}s</span>
                          {segmentationResult.heuristic_only && (
                            <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-600">
                              Zero LLM Cost
                            </Badge>
                          )}
                        </div>
                      </div>
                    </CardHeader>
                    <CardContent>
                      <div className="h-8 rounded-md overflow-hidden border flex">
                        {segmentationResult.segments.map((segment, idx) => {
                          const width = (segment.page_count / segmentationResult.total_pages) * 100;
                          const colors = [
                            "bg-blue-500/40",
                            "bg-green-500/40",
                            "bg-purple-500/40",
                            "bg-orange-500/40",
                            "bg-pink-500/40",
                            "bg-cyan-500/40",
                          ];
                          const isSelected = segmentPreviewPage === segment.page_start ||
                            (segmentPreviewPage >= segment.page_start && segmentPreviewPage <= segment.page_end);
                          const borderColors = [
                            "border-y-2 border-blue-600 shadow-md shadow-blue-500/20",
                            "border-y-2 border-green-600 shadow-md shadow-green-500/20",
                            "border-y-2 border-purple-600 shadow-md shadow-purple-500/20",
                            "border-y-2 border-orange-600 shadow-md shadow-orange-500/20",
                            "border-y-2 border-pink-600 shadow-md shadow-pink-500/20",
                            "border-y-2 border-cyan-600 shadow-md shadow-cyan-500/20",
                          ];
                          return (
                            <div
                              key={segment.index}
                              className={cn(
                                "flex items-center justify-center text-xs font-medium cursor-pointer transition-all duration-300 ease-out",
                                colors[idx % colors.length],
                                isSelected
                                  ? cn(borderColors[idx % borderColors.length], "z-10 scale-105 rounded-sm")
                                  : "hover:brightness-95"
                              )}
                              style={{ width: `${width}%` }}
                              title={`Document ${segment.index + 1}: Pages ${segment.page_start}-${segment.page_end} (click to preview)`}
                              onClick={() => setSegmentPreviewPage(segment.page_start)}
                            >
                              {width > 8 && `${segment.page_start}-${segment.page_end}`}
                            </div>
                          );
                        })}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Apply to All - Quick Action (shown when toggle is enabled) */}
                  {applyToAllEnabled && (
                    <div className="flex-shrink-0 mb-3 flex items-center gap-3 p-3 rounded-lg border bg-primary/5 border-primary/20">
                      <div className="flex items-center gap-2 text-sm font-medium">
                        <LayersIcon size={14} className="text-primary" />
                        <span>Apply to all segments:</span>
                      </div>
                      <Select
                        value=""
                        onValueChange={(value) => {
                          if (value && segmentationResult) {
                            const allSchemas: Record<number, string> = {};
                            segmentationResult.segments.forEach((segment) => {
                              allSchemas[segment.index] = value;
                            });
                            setSegmentSchemas(allSchemas);
                          }
                        }}
                      >
                        <SelectTrigger className="w-[200px] h-8 text-sm">
                          <SelectValue placeholder="Select schema..." />
                        </SelectTrigger>
                        <SelectContent>
                          {schemas.map((schema) => (
                            <SelectItem key={schema.id} value={schema.id} className="text-sm">
                              {schema.name}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      {Object.keys(segmentSchemas).length > 0 && (
                        <Button
                          variant="ghost"
                          size="sm"
                          className="h-8 text-xs text-muted-foreground"
                          onClick={() => setSegmentSchemas({})}
                        >
                          Clear all
                        </Button>
                      )}
                    </div>
                  )}

                  {/* Segment Cards - Scrollable */}
                  <div className="flex-1 overflow-auto min-h-0 space-y-3 pr-2">
                    {segmentationResult.segments.map((segment, idx) => {
                      const colors = [
                        "border-l-blue-500",
                        "border-l-green-500",
                        "border-l-purple-500",
                        "border-l-orange-500",
                        "border-l-pink-500",
                        "border-l-cyan-500",
                      ];
                      const selectedSchema = schemas.find(s => s.id === segmentSchemas[segment.index]);

                      const isSelected = segmentPreviewPage === segment.page_start;
                      const bgColors = [
                        "bg-blue-500",
                        "bg-green-500",
                        "bg-purple-500",
                        "bg-orange-500",
                        "bg-pink-500",
                        "bg-cyan-500",
                      ];
                      return (
                        <Card
                          key={segment.index}
                          className={cn(
                            "border-l-4 transition-all cursor-pointer",
                            colors[idx % colors.length],
                            isSelected
                              ? "bg-blue-50 dark:bg-blue-950/30 shadow-md"
                              : "hover:bg-muted/50 hover:shadow-sm"
                          )}
                          onClick={() => setSegmentPreviewPage(segment.page_start)}
                        >
                          <CardContent className="py-4">
                            <div className="flex items-start gap-4">
                              {/* Segment Number */}
                              <div className={cn(
                                "flex items-center justify-center h-10 w-10 rounded-full font-semibold flex-shrink-0 transition-colors text-white",
                                isSelected
                                  ? bgColors[idx % bgColors.length]
                                  : "bg-muted text-muted-foreground"
                              )}>
                                {segment.index + 1}
                              </div>

                              {/* Segment Info */}
                              <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-2 mb-1">
                                  <span className="font-medium">
                                    Document {segment.index + 1}
                                  </span>
                                  <Badge variant="outline" className="text-xs">
                                    Pages {segment.page_start}-{segment.page_end}
                                  </Badge>
                                  <Badge variant="secondary" className="text-xs">
                                    {segment.page_count} {segment.page_count === 1 ? "page" : "pages"}
                                  </Badge>
                                </div>
                                {segment.detected_type && (
                                  <p className="text-sm text-muted-foreground">
                                    Detected as: <span className="font-medium text-foreground">{segment.detected_type.replace(/_/g, " ")}</span>
                                    <span className="ml-1 opacity-70">({Math.round(segment.type_confidence * 100)}% confidence)</span>
                                  </p>
                                )}
                              </div>

                              {/* Schema Selection */}
                              <div className="flex-shrink-0 w-[180px]">
                                <Select
                                  value={segmentSchemas[segment.index] || ""}
                                  onValueChange={(value) =>
                                    setSegmentSchemas((prev) => ({
                                      ...prev,
                                      [segment.index]: value,
                                    }))
                                  }
                                >
                                  <SelectTrigger className={cn(
                                    "h-9 text-sm",
                                    !segmentSchemas[segment.index] && "border-amber-500/50 bg-amber-500/5"
                                  )}>
                                    <SelectValue placeholder="Select schema...">
                                      {segmentSchemas[segment.index] && (
                                        <span className="truncate block">
                                          {schemas.find(s => s.id === segmentSchemas[segment.index])?.name || "Select..."}
                                        </span>
                                      )}
                                    </SelectValue>
                                  </SelectTrigger>
                                  <SelectContent className="max-w-[300px]">
                                    {schemas.map((schema) => (
                                      <SelectItem
                                        key={schema.id}
                                        value={schema.id}
                                        className="text-sm"
                                      >
                                        <span className="truncate">{schema.name}</span>
                                      </SelectItem>
                                    ))}
                                  </SelectContent>
                                </Select>
                              </div>
                            </div>
                          </CardContent>
                        </Card>
                      );
                    })}
                  </div>

                </div>

                {/* Right: Document Preview - Full Height */}
                <div className="hidden lg:flex lg:flex-col min-h-0 overflow-hidden rounded-lg border bg-neutral-100 dark:bg-neutral-900">
                  {/* Header */}
                  {(() => {
                    const selectedSegment = segmentationResult.segments.find(
                      s => s.page_start === segmentPreviewPage
                    ) || segmentationResult.segments.find(
                      s => segmentPreviewPage >= s.page_start && segmentPreviewPage <= s.page_end
                    );
                    const segmentIdx = selectedSegment?.index || 0;
                    const badgeColors = [
                      "bg-blue-100 text-blue-700 dark:bg-blue-900/30 dark:text-blue-300",
                      "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-300",
                      "bg-purple-100 text-purple-700 dark:bg-purple-900/30 dark:text-purple-300",
                      "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-300",
                      "bg-pink-100 text-pink-700 dark:bg-pink-900/30 dark:text-pink-300",
                      "bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-300",
                    ];
                    return (
                      <div className="flex items-center justify-between px-4 py-2.5 border-b bg-background">
                        <div className="flex items-center gap-2 min-w-0">
                          <FileTextIcon size={16} className="text-muted-foreground flex-shrink-0" />
                          <span className="font-medium truncate">{file?.name || "Document"}</span>
                        </div>
                        {selectedSegment && (
                          <span className={cn(
                            "flex-shrink-0 text-xs font-medium px-2.5 py-1 rounded-full",
                            badgeColors[segmentIdx % badgeColors.length]
                          )}>
                            Document {selectedSegment.index + 1} • Pages {selectedSegment.page_start}-{selectedSegment.page_end}
                          </span>
                        )}
                      </div>
                    );
                  })()}
                  {/* PDF Viewer */}
                  <div className="flex-1 min-h-0">
                    {file && (
                      <PDFViewer
                        file={file}
                        className="h-full w-full"
                        initialPage={segmentPreviewPage}
                      />
                    )}
                  </div>
                </div>
              </div>
            )}

            {/* Error State */}
            {!isAnalyzingSegments && segmentationResult && !segmentationResult.success && (
              <Card className="p-12 border-destructive/50">
                <div className="flex flex-col items-center justify-center text-center">
                  <div className="w-16 h-16 rounded-full bg-destructive/10 flex items-center justify-center mb-4">
                    <AlertCircle className="w-8 h-8 text-destructive" />
                  </div>
                  <h3 className="font-medium mb-1">Segmentation Failed</h3>
                  <p className="text-sm text-muted-foreground mb-4">
                    Could not detect document segments. Try with different settings.
                  </p>
                  <Button variant="outline" onClick={() => setCurrentStep("upload")}>
                    Go Back
                  </Button>
                </div>
              </Card>
            )}

            {/* Floating Continue Button */}
            {!isAnalyzingSegments && segmentationResult && segmentationResult.success && (
              <div className="fixed bottom-6 right-6 z-50">
                <Button
                  size="icon"
                  onClick={() => setCurrentStep("config")}
                  disabled={Object.keys(segmentSchemas).length !== segmentationResult.segments.length}
                  className="h-12 w-12 rounded-full shadow-lg"
                >
                  <ChevronRight className="w-5 h-5" />
                </Button>
              </div>
            )}
          </div>
        )}

        {/* Step 2b: Select Schema (Single-doc mode) */}
        {currentStep === "schema" && (
          <>
            {isCreatingSchema ? (
              /* Inline Schema Builder - Full Height Split View */
              <div className="h-full w-full">
                <SchemaBuilder
                  key={inferredFields.length > 0 ? `inferred-${inferredFields.length}` : "empty"}
                  initialFields={inferredFields.length > 0 ? inferredFields : undefined}
                  initialName={inferredSchemaName || (detectedType?.primary_type?.replace(/_/g, " ")) || undefined}
                  initialDocType={inferredDocType || (detectedType?.primary_type?.replace(/_/g, " ")) || undefined}
                  isLoading={isInferringSchema}
                  onGenerateSchema={handleGenerateSchema}
                  isGenerating={isInferringSchema}
                  documentPreview={
                    <div className="h-full flex flex-col">
                      {/* Header with filename and detection pills */}
                      <div className="px-4 py-3 border-b border-border bg-card">
                        <div className="flex items-center gap-2 flex-wrap">
                          <FileTextIcon size={16} className="text-muted-foreground flex-shrink-0" />
                          <span className="text-sm font-medium truncate max-w-[180px]">{file?.name}</span>

                          {/* Detection Pills - Inline */}
                          {isDetecting ? (
                            <div className="flex items-center gap-1.5 px-2 py-1 rounded-full bg-muted/50 border border-border">
                              <div className="relative w-3 h-3">
                                <div className="absolute inset-0 rounded-full border-2 border-primary/30 animate-ping" />
                                <ScanText className="w-3 h-3 text-primary animate-pulse" />
                              </div>
                              <span className="text-[10px] text-muted-foreground">Detecting...</span>
                            </div>
                          ) : detectedType && (
                            <div className="flex items-center gap-1.5 flex-wrap">
                              {/* Primary Type Pill */}
                              <span
                                className={cn(
                                  "inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium",
                                  detectedType.confidence >= 0.7
                                    ? "bg-green-100 text-green-700 dark:bg-green-900/30 dark:text-green-400"
                                    : detectedType.confidence >= 0.5
                                    ? "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/30 dark:text-yellow-400"
                                    : "bg-orange-100 text-orange-700 dark:bg-orange-900/30 dark:text-orange-400"
                                )}
                              >
                                {detectedType.primary_type.replace(/_/g, " ")}
                                <span className="opacity-70">{Math.round(detectedType.confidence * 100)}%</span>
                              </span>

                              {/* Alternative Type Pills */}
                              {detectedType.confidence < 0.8 && detectedType.alternative_types?.slice(0, 2).map((alt) => (
                                <span
                                  key={alt.type}
                                  className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-muted text-muted-foreground"
                                >
                                  {alt.type.replace(/_/g, " ")}
                                  <span className="opacity-70">{Math.round(alt.confidence * 100)}%</span>
                                </span>
                              ))}
                            </div>
                          )}
                        </div>
                      </div>
                      {/* Document Preview */}
                      <div className="flex-1 overflow-hidden">
                        {file && isPDF(file.name) ? (
                          <PDFViewer file={file} showToolbar={true} />
                        ) : file && imagePreviewUrl ? (
                          <div className="h-full flex flex-col items-center justify-center bg-muted/30 p-4 overflow-auto">
                            <div className="relative max-w-full max-h-full">
                              {/* eslint-disable-next-line @next/next/no-img-element */}
                              <img
                                src={imagePreviewUrl}
                                alt={file.name}
                                className="max-w-full max-h-[calc(100vh-300px)] object-contain rounded-lg shadow-lg"
                              />
                            </div>
                            <p className="mt-4 text-sm text-muted-foreground">
                              Image preview - Will be converted to PDF for processing
                            </p>
                          </div>
                        ) : file && isConverting ? (
                          <div className="h-full flex flex-col items-center justify-center bg-muted/30 p-4">
                            <Loader2 className="w-10 h-10 animate-spin text-muted-foreground mb-4" />
                            <p className="text-sm text-muted-foreground">Converting document for preview...</p>
                          </div>
                        ) : file && conversionError ? (
                          <div className="h-full flex flex-col items-center justify-center bg-muted/30 p-4">
                            <FileTextIcon className="w-16 h-16 text-muted-foreground mb-4" />
                            <p className="text-lg font-medium">{file.name}</p>
                            <p className="text-sm text-destructive mt-2">{conversionError}</p>
                          </div>
                        ) : file && convertedPdfBlob ? (
                          <PDFViewer file={convertedPdfBlob} showToolbar={true} />
                        ) : file ? (
                          <div className="h-full flex flex-col items-center justify-center bg-muted/30 p-4">
                            <FileTextIcon className="w-16 h-16 text-muted-foreground mb-4" />
                            <p className="text-lg font-medium">{file.name}</p>
                            <p className="text-sm text-muted-foreground mt-2">
                              Document preview not available
                            </p>
                          </div>
                        ) : null}
                      </div>
                    </div>
                  }
                  onSave={async (fields, schemaName, docType, description) => {
                    try {
                      // Convert fields to JSON schema
                      const fieldsToSchema = (fields: SchemaField[]): object => {
                        const properties: Record<string, object> = {};
                        const required: string[] = [];
                        fields.forEach((field) => {
                          if (!field.name) return;
                          let propDef: Record<string, unknown> = { type: field.type };
                          if (field.type === "object" && field.children) {
                            propDef = { ...propDef, ...fieldsToSchema(field.children) };
                          }
                          if (field.type === "array" && field.children?.length) {
                            propDef.items = { type: "object", ...fieldsToSchema(field.children) };
                          }
                          properties[field.name] = propDef;
                          if (field.required) required.push(field.name);
                        });
                        return { type: "object", properties, ...(required.length ? { required } : {}) };
                      };

                      // Convert docType to snake_case for the API
                      const formattedDocType = docType.toLowerCase().replace(/\s+/g, '_');

                      const schema = await api.createSchema(
                        schemaName,
                        formattedDocType,
                        fieldsToSchema(fields) as Record<string, unknown>,
                        description || "Custom extraction schema"
                      );

                      // Refetch schemas and select the new one
                      await queryClient.invalidateQueries({ queryKey: ["schemas"] });
                      setSelectedSchema(schema);
                      setIsCreatingSchema(false);
                      setCurrentStep("config");
                    } catch (error) {
                      console.error("Failed to create schema:", error);
                    }
                  }}
                  onCancel={() => setIsCreatingSchema(false)}
                />
              </div>
            ) : (
              /* Schema Selection Grid */
              <div className="max-w-5xl mx-auto">
                {/* Header with Search and Create Button */}
                <div className="flex items-center justify-between mb-6">
                  <div>
                    <h2 className="text-lg font-semibold mb-1">Select Extraction Schema</h2>
                    <p className="text-sm text-muted-foreground">
                      Choose a template or create a custom schema for your document
                    </p>
                  </div>
                  <Button onClick={() => setIsCreatingSchema(true)}>
                    <PlusIcon size={16} className="mr-2" />
                    Create Schema
                  </Button>
                </div>

                {/* Document Type Detection - Compact Pills */}
                <div className="mb-6 flex items-center gap-3 flex-wrap">
                  <div className="flex items-center gap-2 text-sm text-muted-foreground">
                    <FileTextIcon size={16} />
                    <span className="font-medium text-foreground truncate max-w-[200px]">{file?.name}</span>
                  </div>

                  {isDetecting ? (
                    /* Scanning Animation */
                    <div className="flex items-center gap-2 px-3 py-1.5 rounded-full bg-muted/50 border border-border">
                      <div className="relative w-4 h-4">
                        <div className="absolute inset-0 rounded-full border-2 border-primary/30 animate-ping" />
                        <ScanText className="w-4 h-4 text-primary animate-pulse" />
                      </div>
                      <span className="text-xs text-muted-foreground">
                        Detecting with {classifier === "pere-custom-classifier" ? "Custom" : (classifier === "gpt-5.5" || classifier === "gpt-4o") ? "GPT-5.5" : classifier.charAt(0).toUpperCase() + classifier.slice(1)}...
                      </span>
                    </div>
                  ) : detectedType && (
                    /* Detection Result Pills */
                    <div className="flex items-center gap-2 flex-wrap">
                      {/* Primary Type Pill */}
                      <button
                        type="button"
                        onClick={() => {
                          if (schemaSearch === detectedType.primary_type.replace(/_/g, " ")) {
                            setSchemaSearch("");
                          } else {
                            setSchemaSearch(detectedType.primary_type.replace(/_/g, " "));
                          }
                        }}
                        className={cn(
                          "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all cursor-pointer",
                          detectedType.confidence >= 0.7
                            ? "bg-green-100 text-green-700 hover:bg-green-200 dark:bg-green-900/30 dark:text-green-400"
                            : detectedType.confidence >= 0.5
                            ? "bg-yellow-100 text-yellow-700 hover:bg-yellow-200 dark:bg-yellow-900/30 dark:text-yellow-400"
                            : "bg-orange-100 text-orange-700 hover:bg-orange-200 dark:bg-orange-900/30 dark:text-orange-400",
                          schemaSearch === detectedType.primary_type.replace(/_/g, " ") && "ring-2 ring-offset-1 ring-primary"
                        )}
                      >
                        <span>{detectedType.primary_type.replace(/_/g, " ")}</span>
                        <span className="opacity-70">{Math.round(detectedType.confidence * 100)}%</span>
                      </button>

                      {/* Alternative Type Pills (show when confidence < 80% or alternatives exist) */}
                      {detectedType.confidence < 0.8 && detectedType.alternative_types?.slice(0, 2).map((alt) => (
                        <button
                          key={alt.type}
                          type="button"
                          onClick={() => {
                            if (schemaSearch === alt.type.replace(/_/g, " ")) {
                              setSchemaSearch("");
                            } else {
                              setSchemaSearch(alt.type.replace(/_/g, " "));
                            }
                          }}
                          className={cn(
                            "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium transition-all cursor-pointer",
                            "bg-muted text-muted-foreground hover:bg-muted/80",
                            schemaSearch === alt.type.replace(/_/g, " ") && "ring-2 ring-offset-1 ring-primary bg-primary/10 text-foreground"
                          )}
                        >
                          <span>{alt.type.replace(/_/g, " ")}</span>
                          <span className="opacity-70">{Math.round(alt.confidence * 100)}%</span>
                        </button>
                      ))}

                      {/* Clear filter button */}
                      {schemaSearch && (
                        <button
                          type="button"
                          onClick={() => setSchemaSearch("")}
                          className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-xs text-muted-foreground hover:text-foreground hover:bg-muted transition-all"
                        >
                          <XIcon size={12} />
                          <span>Clear</span>
                        </button>
                      )}

                      {/* Classifier info pill */}
                      {detectedType.classifier_used && detectedType.classifier_used !== "pattern" && (
                        <span className="inline-flex items-center gap-1 px-2 py-1 rounded-full text-[10px] font-medium bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400">
                          <Brain className="w-3 h-3" />
                          {detectedType.classifier_used}
                        </span>
                      )}

                      {/* Provider Recommendations - inline badges */}
                      {detectedType?.suggested_ocr?.provider && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-cyan-50 text-cyan-700 border border-cyan-200 dark:bg-cyan-900/30 dark:text-cyan-400 dark:border-cyan-800">
                          <ScanText className="w-3 h-3" />
                          {detectedType.suggested_ocr.display_name || detectedType.suggested_ocr.provider.replace(/_/g, " ")}
                        </span>
                      )}
                      {detectedType?.suggested_llm?.provider && (
                        <span className="inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium bg-purple-50 text-purple-700 border border-purple-200 dark:bg-purple-900/30 dark:text-purple-400 dark:border-purple-800">
                          <Cpu className="w-3 h-3" />
                          {detectedType.suggested_llm.display_name || detectedType.suggested_llm.provider.replace(/_/g, " ")}
                        </span>
                      )}
                    </div>
                  )}
                </div>

                {/* Search Bar */}
                <div className="relative mb-6">
                  <SearchIcon size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    placeholder="Search schemas by name or type..."
                    value={schemaSearch}
                    onChange={(e) => setSchemaSearch(e.target.value)}
                    className="pl-9 h-10"
                  />
                </div>

                {/* Schema Grid */}
                <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                  {schemas
                    .filter((s) =>
                      schemaSearch
                        ? s.name.toLowerCase().includes(schemaSearch.toLowerCase()) ||
                          s.doc_type.toLowerCase().includes(schemaSearch.toLowerCase())
                        : true
                    )
                    .map((schema) => (
                      <Card
                        key={schema.id}
                        className={cn(
                          "cursor-pointer transition-all hover:border-primary/50 hover:shadow-sm group",
                          selectedSchema?.id === schema.id && "border-primary ring-1 ring-primary/20 bg-primary/5"
                        )}
                        onClick={() => handleSchemaSelect(schema)}
                      >
                        <CardContent className="py-4 px-4">
                          <div className="flex items-start justify-between mb-3">
                            <div className="w-9 h-9 rounded-md bg-muted flex items-center justify-center group-hover:bg-primary/10 transition-colors">
                              <FileTextIcon size={16} className="text-muted-foreground group-hover:text-primary transition-colors" />
                            </div>
                            <div className="flex items-center gap-1.5">
                              {schema.is_default && (
                                <Badge variant="outline" className="text-[10px] font-normal">Default</Badge>
                              )}
                            </div>
                          </div>
                          <h3 className="font-medium text-sm mb-1">{schema.name}</h3>
                          <Badge variant="secondary" className="mb-2 text-[10px] font-normal">
                            {schema.doc_type.replace(/_/g, " ")}
                          </Badge>
                          <p className="text-xs text-muted-foreground line-clamp-2">
                            {schema.description || "No description available"}
                          </p>
                        </CardContent>
                      </Card>
                    ))}

                  {/* Create New Schema Card - Always visible */}
                  <Card
                    className="cursor-pointer border-dashed border-2 hover:border-primary/50 hover:bg-primary/5 transition-all group"
                    onClick={() => setIsCreatingSchema(true)}
                  >
                    <CardContent className="py-6 px-4 text-center flex flex-col items-center justify-center h-full min-h-[140px]">
                      <div className="w-10 h-10 rounded-full bg-muted flex items-center justify-center mb-3 group-hover:bg-primary/10 transition-colors">
                        <PlusIcon size={20} className="text-muted-foreground group-hover:text-primary transition-colors" />
                      </div>
                      <p className="font-medium text-sm mb-1">Create Custom Schema</p>
                      <p className="text-xs text-muted-foreground">
                        Define your own extraction fields
                      </p>
                    </CardContent>
                  </Card>
                </div>

                {/* No Results */}
                {schemas.filter((s) =>
                  schemaSearch
                    ? s.name.toLowerCase().includes(schemaSearch.toLowerCase()) ||
                      s.doc_type.toLowerCase().includes(schemaSearch.toLowerCase())
                    : true
                ).length === 0 && (
                  <div className="text-center py-12 text-muted-foreground">
                    <FileTextIcon size={40} className="mx-auto mb-3 opacity-50" />
                    <p className="text-sm">No schemas found matching "{schemaSearch}"</p>
                    <Button
                      variant="link"
                      className="mt-2"
                      onClick={() => setSchemaSearch("")}
                    >
                      Clear search
                    </Button>
                  </div>
                )}

              </div>
            )}
          </>
        )}

        {/* Step 3: Configure Pipeline */}
        {currentStep === "config" && (
          <TooltipProvider>
            <div className="max-w-5xl mx-auto">
              <div className="mb-6">
                <h2 className="text-lg font-semibold mb-1">Configure Extraction Pipeline</h2>
                <p className="text-sm text-muted-foreground">
                  Customize AI providers and processing settings for optimal results
                </p>
              </div>

              <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Left Column - Main Configuration */}
                <div className="lg:col-span-2 space-y-6">
                  {/* Document & Schema Summary */}
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm font-medium flex items-center gap-2">
                        <FileTextIcon size={16} />
                        Document Configuration
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="grid grid-cols-2 gap-4 items-start">
                        <div className="p-3 bg-muted/50 rounded-lg">
                          <p className="text-xs text-muted-foreground mb-1">Document</p>
                          <p className="font-medium text-sm truncate">{file?.name}</p>
                          <p className="text-xs text-muted-foreground mt-1">
                            {file && (file.size / 1024).toFixed(1)} KB
                          </p>
                        </div>
                        <div className="p-3 bg-muted/50 rounded-lg max-h-[200px] overflow-hidden">
                          <div className="flex items-center justify-between mb-1">
                            <p className="text-xs text-muted-foreground">Schema</p>
                            <Button
                              variant="ghost"
                              size="sm"
                              className="h-5 text-xs px-2"
                              onClick={() => setCurrentStep(enableSegmentation ? "segments" : "schema")}
                            >
                              Change
                            </Button>
                          </div>
                          {enableSegmentation ? (
                            // Multi-doc mode: show grouped schema summary
                            (() => {
                              // Group segments by schema
                              const schemaGroups = (segmentationResult?.segments || []).reduce((acc, segment) => {
                                const schemaId = segmentSchemas[segment.index];
                                const schema = schemas.find(s => s.id === schemaId);
                                const schemaName = schema?.name || "Not selected";
                                if (!acc[schemaName]) {
                                  acc[schemaName] = { schema, segments: [] };
                                }
                                acc[schemaName].segments.push(segment.index + 1);
                                return acc;
                              }, {} as Record<string, { schema: typeof schemas[0] | undefined; segments: number[] }>);

                              const totalDocs = segmentationResult?.segments.length || 0;
                              const groupEntries = Object.entries(schemaGroups);

                              return (
                                <div className="space-y-2">
                                  {/* Summary header */}
                                  <div className="flex items-center gap-2 mb-2">
                                    <Badge variant="secondary" className="text-[10px] font-medium">
                                      {totalDocs} {totalDocs === 1 ? 'document' : 'documents'}
                                    </Badge>
                                    <span className="text-[10px] text-muted-foreground">
                                      {groupEntries.length} {groupEntries.length === 1 ? 'schema' : 'schemas'}
                                    </span>
                                  </div>

                                  {/* Grouped schema list */}
                                  <div className="space-y-1.5 max-h-[120px] overflow-y-auto pr-1">
                                    {groupEntries.map(([schemaName, group]) => {
                                      const isUnassigned = schemaName === "Not selected";
                                      return (
                                        <Collapsible key={schemaName}>
                                          <CollapsibleTrigger className="w-full">
                                            <div className={cn(
                                              "flex items-center justify-between p-1.5 rounded text-left hover:bg-muted/50 transition-colors",
                                              isUnassigned && "bg-amber-500/10"
                                            )}>
                                              <div className="flex items-center gap-2 min-w-0 flex-1">
                                                <Badge
                                                  variant={isUnassigned ? "outline" : "secondary"}
                                                  className={cn(
                                                    "text-[10px] shrink-0",
                                                    isUnassigned && "border-amber-500/50 text-amber-600"
                                                  )}
                                                >
                                                  {group.segments.length}
                                                </Badge>
                                                <span className={cn(
                                                  "text-xs truncate",
                                                  isUnassigned ? "text-amber-600 italic" : "font-medium"
                                                )}>
                                                  {schemaName}
                                                </span>
                                              </div>
                                              <ChevronRight className="w-3 h-3 text-muted-foreground shrink-0 transition-transform group-data-[state=open]:rotate-90" />
                                            </div>
                                          </CollapsibleTrigger>
                                          <CollapsibleContent>
                                            <div className="pl-6 py-1 text-[10px] text-muted-foreground">
                                              Docs: {group.segments.length <= 10
                                                ? group.segments.join(", ")
                                                : `${group.segments.slice(0, 8).join(", ")}... +${group.segments.length - 8} more`
                                              }
                                            </div>
                                          </CollapsibleContent>
                                        </Collapsible>
                                      );
                                    })}
                                  </div>
                                </div>
                              );
                            })()
                          ) : (
                            // Single-doc mode: show selected schema
                            <>
                              <p className="font-medium text-sm">{selectedSchema?.name}</p>
                              <Badge variant="outline" className="text-[10px] mt-1">
                                {selectedSchema?.doc_type?.replace(/_/g, " ")}
                              </Badge>
                            </>
                          )}
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Provider Selection */}
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm font-medium flex items-center gap-2">
                        <WorkflowIcon size={16} />
                        AI Provider Configuration
                      </CardTitle>
                      <CardDescription className="text-xs">
                        Choose your OCR and extraction models
                      </CardDescription>
                    </CardHeader>
                    <CardContent className="space-y-6">
                      {/* OCR Provider Selection */}
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <label className="text-sm font-medium flex items-center gap-2">
                            <ScanText className="w-4 h-4 text-muted-foreground" />
                            OCR Provider
                            {detectedType?.suggested_ocr?.provider && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400">
                                Recommended: {detectedType.suggested_ocr.display_name || detectedType.suggested_ocr.provider.replace(/_/g, " ")}
                              </span>
                            )}
                          </label>
                          <Tooltip>
                            <TooltipTrigger>
                              <Info className="w-3.5 h-3.5 text-muted-foreground" />
                            </TooltipTrigger>
                            <TooltipContent side="left" className="max-w-xs">
                              <p className="text-xs">OCR converts document images to text. Local providers are free but may be slower.</p>
                            </TooltipContent>
                          </Tooltip>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          {providers?.ocr_providers?.map((p) => {
                            const isSelected = (ocrProvider || availableOcrProviders[0]?.name) === p.name;
                            const isRecommended = detectedType?.suggested_ocr?.provider === p.name;
                            return (
                              <div
                                key={p.name}
                                onClick={() => {
                                  if (!p.is_available) return;
                                  userPickedOcrProviderRef.current = true;
                                  setOcrProvider(p.name);
                                }}
                                className={cn(
                                  "p-3 rounded-lg border-2 cursor-pointer transition-all relative",
                                  isSelected
                                    ? "border-primary bg-primary/5"
                                    : p.is_available
                                    ? "border-border hover:border-primary/50"
                                    : "border-border opacity-50 cursor-not-allowed",
                                  isRecommended && !isSelected && "ring-2 ring-cyan-300 dark:ring-cyan-700"
                                )}
                              >
                                {isRecommended && (
                                  <div className="absolute -top-2 -right-2 px-1.5 py-0.5 rounded-full text-[9px] font-medium bg-cyan-600 text-white">
                                    Recommended
                                  </div>
                                )}
                                <div className="flex items-start justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    {p.cost_tier === "free" ? (
                                      <HardDrive className="w-4 h-4 text-green-600" />
                                    ) : (
                                      <Cloud className="w-4 h-4 text-blue-600" />
                                    )}
                                    <span className="font-medium text-sm">{p.display_name}</span>
                                  </div>
                                  {isSelected && <CheckCircle2 className="w-4 h-4 text-primary" />}
                                </div>
                                <div className="flex items-center gap-2 mb-2">
                                  {p.cost_tier === "free" ? (
                                    <Badge variant="secondary" className="text-[10px] bg-green-100 text-green-700">FREE</Badge>
                                  ) : (
                                    <Badge variant="secondary" className="text-[10px] bg-blue-100 text-blue-700">CLOUD</Badge>
                                  )}
                                  {!p.is_available && (
                                    <Badge variant="destructive" className="text-[10px]">Unavailable</Badge>
                                  )}
                                </div>
                                <p className="text-xs text-muted-foreground line-clamp-2">
                                  {p.description || "No description available"}
                                </p>
                                {isRecommended && detectedType?.suggested_ocr?.reasoning && (
                                  <p className="text-[10px] text-cyan-600 dark:text-cyan-400 mt-2 italic">
                                    "{detectedType.suggested_ocr.reasoning}"
                                  </p>
                                )}
                                
                                {/* Model Selector - Shows only when provider is selected and has model options */}
                                {isSelected && (() => {
                                  const modelConfig = p.config_options?.model as any;
                                  const modelOptions = modelConfig?.options;
                                  if (!modelOptions || !Array.isArray(modelOptions) || modelOptions.length === 0) return null;
                                  
                                  return (
                                    <div className="mt-3 pt-3 border-t border-border/50" onClick={(e) => e.stopPropagation()}>
                                      <Label className="text-xs mb-2 block">Model</Label>
                                      <Select
                                        value={ocrModelConfig.model || modelConfig?.default}
                                        onValueChange={(value) => setOcrModelConfig({ ...ocrModelConfig, model: value })}
                                      >
                                        <SelectTrigger className="h-8 text-xs">
                                          <SelectValue />
                                        </SelectTrigger>
                                        <SelectContent>
                                          {modelOptions.map((opt: any) => (
                                            <SelectItem key={opt.value} value={opt.value} className="text-xs">
                                              <div className="flex flex-col py-1">
                                                <span className="font-medium">{opt.label}</span>
                                                {opt.description && (
                                                  <span className="text-[10px] text-muted-foreground">
                                                    {opt.description}
                                                  </span>
                                                )}
                                              </div>
                                            </SelectItem>
                                          ))}
                                        </SelectContent>
                                      </Select>
                                    </div>
                                  );
                                })()}
                              </div>
                            );
                          })}
                        </div>
                      </div>

                      <Separator />

                      {/* LLM Extractor Selection */}
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <label className="text-sm font-medium flex items-center gap-2">
                            <Brain className="w-4 h-4 text-muted-foreground" />
                            LLM Extractor
                            {detectedType?.suggested_llm?.provider && (
                              <span className="inline-flex items-center gap-1 px-2 py-0.5 rounded-full text-[10px] font-medium bg-cyan-100 text-cyan-700 dark:bg-cyan-900/30 dark:text-cyan-400">
                                Recommended: {detectedType.suggested_llm.display_name}
                              </span>
                            )}
                          </label>
                          <Tooltip>
                            <TooltipTrigger>
                              <Info className="w-3.5 h-3.5 text-muted-foreground" />
                            </TooltipTrigger>
                            <TooltipContent side="left" className="max-w-xs">
                              <p className="text-xs">LLM extracts structured data from text. Local models are free and private.</p>
                            </TooltipContent>
                          </Tooltip>
                        </div>
                        <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                          {providers?.llm_providers?.map((p) => {
                            const isSelected = (llmProvider || availableLlmProviders[0]?.name) === p.name;
                            const isRecommended = detectedType?.suggested_llm?.provider === p.name;
                            return (
                              <div
                                key={p.name}
                                onClick={() => {
                                  if (!p.is_available) return;
                                  userPickedLlmProviderRef.current = true;
                                  setLlmProvider(p.name);
                                }}
                                className={cn(
                                  "p-3 rounded-lg border-2 cursor-pointer transition-all relative",
                                  isSelected
                                    ? "border-primary bg-primary/5"
                                    : p.is_available
                                    ? "border-border hover:border-primary/50"
                                    : "border-border opacity-50 cursor-not-allowed",
                                  isRecommended && !isSelected && "ring-2 ring-cyan-300 dark:ring-cyan-700"
                                )}
                              >
                                {isRecommended && (
                                  <div className="absolute -top-2 -right-2 px-1.5 py-0.5 rounded-full text-[9px] font-medium bg-cyan-600 text-white">
                                    Recommended
                                  </div>
                                )}
                                <div className="flex items-start justify-between mb-2">
                                  <div className="flex items-center gap-2">
                                    {p.cost_tier === "free" ? (
                                      <CpuIcon size={16} className=" text-green-600" />
                                    ) : (
                                      <Cloud className="w-4 h-4 text-blue-600" />
                                    )}
                                    <span className="font-medium text-sm">{p.display_name}</span>
                                  </div>
                                  {isSelected && <CheckCircle2 className="w-4 h-4 text-primary" />}
                                </div>
                                <div className="flex items-center gap-2 mb-2">
                                  {p.cost_tier === "free" ? (
                                    <Badge variant="secondary" className="text-[10px] bg-green-100 text-green-700">FREE</Badge>
                                  ) : (
                                    <Badge variant="secondary" className="text-[10px] bg-blue-100 text-blue-700">CLOUD</Badge>
                                  )}
                                  {!p.is_available && (
                                    <Badge variant="destructive" className="text-[10px]">Unavailable</Badge>
                                  )}
                                </div>
                                <p className="text-xs text-muted-foreground line-clamp-2">
                                  {p.description || "No description available"}
                                </p>
                                {isRecommended && detectedType?.suggested_llm?.reasoning && (
                                  <p className="text-[10px] text-cyan-600 dark:text-cyan-400 mt-2 italic">
                                    "{detectedType.suggested_llm.reasoning}"
                                  </p>
                                )}
                                
                              </div>
                            );
                          })}
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Consensus Extraction - Multi-Provider Validation */}
                  <Card className={cn(enableConsensus && "border-primary/30 bg-primary/5")}>
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm font-medium flex items-center gap-2">
                          <ShieldCheckIcon size={16} />
                          Multi-Provider Validation
                        </CardTitle>
                        <Switch
                          checked={enableConsensus}
                          onCheckedChange={setEnableConsensus}
                        />
                      </div>
                      <CardDescription className="text-xs">
                        Use multiple providers and compare results for higher accuracy
                      </CardDescription>
                    </CardHeader>
                    {enableConsensus && (
                      <CardContent className="space-y-4 pt-0">
                        <Separator />
                        <div className="space-y-3">
                          <label className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                            <UsersIcon size={14} />
                            Select additional OCR providers for comparison
                          </label>
                          <div className="flex flex-wrap gap-2">
                            {providers?.ocr_providers?.filter(p => p.is_available && p.name !== ocrProvider).map((p) => {
                              const isSelected = consensusOcrProviders.includes(p.name);
                              return (
                                <Badge
                                  key={p.name}
                                  variant={isSelected ? "default" : "outline"}
                                  className={cn(
                                    "cursor-pointer transition-all",
                                    isSelected ? "bg-primary" : "hover:bg-primary/10"
                                  )}
                                  onClick={() => {
                                    if (isSelected) {
                                      setConsensusOcrProviders(prev => prev.filter(n => n !== p.name));
                                    } else {
                                      setConsensusOcrProviders(prev => [...prev, p.name]);
                                    }
                                  }}
                                >
                                  {isSelected && <CheckCircle2 className="w-3 h-3 mr-1" />}
                                  {p.display_name}
                                </Badge>
                              );
                            })}
                          </div>
                        </div>
                        <div className="space-y-3">
                          <label className="text-xs font-medium text-muted-foreground flex items-center gap-2">
                            <UsersIcon size={14} />
                            Select additional LLM providers for comparison
                          </label>
                          <div className="flex flex-wrap gap-2">
                            {providers?.llm_providers?.filter(p => p.is_available && p.name !== llmProvider).map((p) => {
                              const isSelected = consensusLlmProviders.includes(p.name);
                              return (
                                <Badge
                                  key={p.name}
                                  variant={isSelected ? "default" : "outline"}
                                  className={cn(
                                    "cursor-pointer transition-all",
                                    isSelected ? "bg-primary" : "hover:bg-primary/10"
                                  )}
                                  onClick={() => {
                                    if (isSelected) {
                                      setConsensusLlmProviders(prev => prev.filter(n => n !== p.name));
                                    } else {
                                      setConsensusLlmProviders(prev => [...prev, p.name]);
                                    }
                                  }}
                                >
                                  {isSelected && <CheckCircle2 className="w-3 h-3 mr-1" />}
                                  {p.display_name}
                                </Badge>
                              );
                            })}
                          </div>
                        </div>
                        {(consensusOcrProviders.length > 0 || consensusLlmProviders.length > 0) && (
                          <div className="p-3 rounded-lg bg-muted/50 text-xs text-muted-foreground">
                            <div className="flex items-center gap-2 mb-1">
                              <FileCheckIcon size={14} className="text-primary" />
                              <span className="font-medium text-foreground">Validation Summary</span>
                            </div>
                            Results will be compared across {1 + consensusOcrProviders.length} OCR and {1 + consensusLlmProviders.length} LLM providers.
                            Conflicts will be flagged for review.
                          </div>
                        )}
                      </CardContent>
                    )}
                  </Card>

                  {/* Advanced Options */}
                  <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
                    <Card>
                      <CollapsibleTrigger asChild>
                        <CardHeader className="pb-3 cursor-pointer hover:bg-muted/30 transition-colors">
                          <div className="flex items-center justify-between">
                            <CardTitle className="text-sm font-medium flex items-center gap-2">
                              <Settings2 className="w-4 h-4" />
                              Advanced Options
                            </CardTitle>
                            <ChevronDownIcon size={16} className={cn(
                              "text-muted-foreground transition-transform",
                              showAdvanced && "rotate-180"
                            )} />
                          </div>
                          <CardDescription className="text-xs">
                            Fine-tune extraction behavior and quality settings
                          </CardDescription>
                        </CardHeader>
                      </CollapsibleTrigger>
                      <CollapsibleContent>
                        <CardContent className="space-y-6 pt-0">
                          <Separator />

                          {/* Confidence Threshold */}
                          <div className="space-y-3">
                            <div className="flex items-center justify-between">
                              <label className="text-sm font-medium flex items-center gap-2">
                                <GaugeIcon size={16} className=" text-muted-foreground" />
                                Confidence Threshold
                              </label>
                              <span className="text-sm font-medium text-primary">{confidenceThreshold[0]}%</span>
                            </div>
                            <Slider
                              value={confidenceThreshold}
                              onValueChange={setConfidenceThreshold}
                              max={100}
                              min={0}
                              step={5}
                              className="w-full"
                            />
                            <p className="text-xs text-muted-foreground">
                              Fields below this confidence will be flagged for review
                            </p>
                          </div>

                          <Separator />

                          {/* Processing Options */}
                          <div className="space-y-4">
                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <LayersIcon size={16} className=" text-muted-foreground" />
                                <div>
                                  <p className="text-sm font-medium">Parallel Processing</p>
                                  <p className="text-xs text-muted-foreground">Process multiple parts simultaneously</p>
                                </div>
                              </div>
                              <Switch
                                checked={parallelProcessing}
                                onCheckedChange={setParallelProcessing}
                              />
                            </div>

                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <Bolt className="w-4 h-4 text-muted-foreground" />
                                <div>
                                  <p className="text-sm font-medium">Streaming Mode</p>
                                  <p className="text-xs text-muted-foreground">See results in real-time as they arrive</p>
                                </div>
                              </div>
                              <Switch
                                checked={streamingMode}
                                onCheckedChange={setStreamingMode}
                              />
                            </div>

                            <div className="flex items-center justify-between">
                              <div className="flex items-center gap-2">
                                <Shield className="w-4 h-4 text-muted-foreground" />
                                <div>
                                  <p className="text-sm font-medium">Fallback Extraction</p>
                                  <p className="text-xs text-muted-foreground">Use regex patterns if AI fails</p>
                                </div>
                              </div>
                              <Switch
                                checked={enableFallback}
                                onCheckedChange={setEnableFallback}
                              />
                            </div>
                          </div>
                        </CardContent>
                      </CollapsibleContent>
                    </Card>
                  </Collapsible>
                </div>

                {/* Right Column - Summary & Actions */}
                <div className="space-y-6">
                  {/* Configuration Summary */}
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm font-medium">Configuration Summary</CardTitle>
                    </CardHeader>
                    <CardContent className="space-y-4">
                      <div className="space-y-3">
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-muted-foreground">OCR Provider</span>
                          <span className="font-medium">
                            {providers?.ocr_providers?.find(p => p.name === (ocrProvider || availableOcrProviders[0]?.name))?.display_name || "-"}
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-muted-foreground">LLM Extractor</span>
                          <span className="font-medium">
                            {providers?.llm_providers?.find(p => p.name === (llmProvider || availableLlmProviders[0]?.name))?.display_name || "-"}
                          </span>
                        </div>
                        <Separator />
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-muted-foreground">
                            {enableSegmentation ? "Documents" : "Schema Parts"}
                          </span>
                          <span className="font-medium">
                            {enableSegmentation
                              ? `${segmentationResult?.segments.length || 0} segments`
                              : selectedSchema?.doc_type === "bill_of_entry" ? "7 parts" : selectedSchema?.doc_type === "shipping_bill" ? "6 parts" : "Custom"
                            }
                          </span>
                        </div>
                        <div className="flex items-center justify-between text-sm">
                          <span className="text-muted-foreground">Confidence</span>
                          <span className="font-medium">{confidenceThreshold[0]}%</span>
                        </div>
                      </div>
                    </CardContent>
                  </Card>

                  {/* Multi-Agent Extraction */}
                  <Card className={cn(useAgents && "border-violet-500/30 bg-violet-500/5")}>
                    <CardHeader className="pb-3">
                      <div className="flex items-center justify-between">
                        <CardTitle className="text-sm font-medium flex items-center gap-2">
                          <Cpu className="w-4 h-4" />
                          Multi-Agent Extraction
                          <Badge variant="outline" className="text-[10px] px-1.5 py-0 font-normal bg-violet-100 text-violet-700 dark:bg-violet-900/30 dark:text-violet-400 border-violet-300 dark:border-violet-700">
                            Beta
                          </Badge>
                        </CardTitle>
                        <Switch
                          checked={useAgents}
                          onCheckedChange={setUseAgents}
                        />
                      </div>
                      <CardDescription className="text-xs">
                        Use specialized AI agents for better table/line item extraction
                      </CardDescription>
                    </CardHeader>
                    {useAgents && (
                      <CardContent className="space-y-3 pt-0">
                        <Separator />
                        <div className="text-xs text-muted-foreground space-y-1.5">
                          <div className="flex items-start gap-2">
                            <CheckCircle2 className="w-3.5 h-3.5 text-green-500 mt-0.5 shrink-0" />
                            <span>Specialized tools for tables & line items</span>
                          </div>
                          <div className="flex items-start gap-2">
                            <CheckCircle2 className="w-3.5 h-3.5 text-green-500 mt-0.5 shrink-0" />
                            <span>Real-time agent activity visibility</span>
                          </div>
                        </div>
                      </CardContent>
                    )}
                  </Card>

                  {/* Cost Estimation */}
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm font-medium flex items-center gap-2">
                        <DollarSignIcon size={16} />
                        Cost Estimation
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      {(() => {
                        const ocrCost = providers?.ocr_providers?.find(p => p.name === (ocrProvider || availableOcrProviders[0]?.name))?.cost_tier;
                        const llmCost = providers?.llm_providers?.find(p => p.name === (llmProvider || availableLlmProviders[0]?.name))?.cost_tier;
                        const isFree = ocrCost === "free" && llmCost === "free";

                        return (
                          <div className="space-y-3">
                            <div className={cn(
                              "text-center p-4 rounded-lg",
                              isFree ? "bg-green-50 dark:bg-green-950" : "bg-blue-50 dark:bg-blue-950"
                            )}>
                              <p className={cn(
                                "text-2xl font-bold",
                                isFree ? "text-green-600" : "text-blue-600"
                              )}>
                                {isFree ? "FREE" : "~$0.01-0.05"}
                              </p>
                              <p className="text-xs text-muted-foreground mt-1">
                                {isFree ? "Using local models only" : "Estimated per document"}
                              </p>
                            </div>
                            {!isFree && (
                              <p className="text-xs text-muted-foreground text-center">
                                Actual cost depends on document size and complexity
                              </p>
                            )}
                          </div>
                        );
                      })()}
                    </CardContent>
                  </Card>

                  {/* Quick Tips - Dynamic based on AI recommendations */}
                  <Card>
                    <CardHeader className="pb-3">
                      <CardTitle className="text-sm font-medium flex items-center gap-2">
                        <SparklesIcon size={16} />
                        Quick Tips
                      </CardTitle>
                    </CardHeader>
                    <CardContent>
                      <div className="space-y-3 text-xs text-muted-foreground">
                        {detectedType?.suggested_ocr?.provider && detectedType?.suggested_llm?.provider ? (
                          <>
                            <div className="flex items-start gap-2">
                              <CircleCheckIcon size={14} className="text-cyan-500 mt-0.5 flex-shrink-0" />
                              <p>AI recommends <strong>{detectedType.suggested_ocr.display_name || detectedType.suggested_ocr.provider.replace(/_/g, " ")} + {detectedType.suggested_llm.display_name || detectedType.suggested_llm.provider.replace(/_/g, " ")}</strong> for this {detectedType.primary_type.replace(/_/g, " ")}</p>
                            </div>
                            {detectedType.suggested_ocr.reasoning && (
                              <div className="flex items-start gap-2">
                                <CircleCheckIcon size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
                                <p>{detectedType.suggested_ocr.reasoning}</p>
                              </div>
                            )}
                            {detectedType.suggested_llm.reasoning && (
                              <div className="flex items-start gap-2">
                                <CircleCheckIcon size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
                                <p>{detectedType.suggested_llm.reasoning}</p>
                              </div>
                            )}
                          </>
                        ) : (
                          <>
                            <div className="flex items-start gap-2">
                              <CircleCheckIcon size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
                              <p>Use <strong>PaddleOCR + NuExtract</strong> for free, offline extraction</p>
                            </div>
                            <div className="flex items-start gap-2">
                              <CircleCheckIcon size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
                              <p>Enable <strong>Multi-Provider Validation</strong> for higher accuracy</p>
                            </div>
                            <div className="flex items-start gap-2">
                              <CircleCheckIcon size={14} className="text-green-500 mt-0.5 flex-shrink-0" />
                              <p><strong>Mistral OCR</strong> works best with tables and complex layouts</p>
                            </div>
                          </>
                        )}
                      </div>
                    </CardContent>
                  </Card>

                  {/* Start Extraction Button */}
                  <Button
                    className="w-full"
                    size="lg"
                    onClick={handleStartExtraction}
                  >
                    <PlayIcon size={16} className="mr-2" />
                    Start Extraction
                    <ArrowRightIcon size={16} className="ml-2" />
                  </Button>

                  <p className="text-xs text-center text-muted-foreground">
                    Processing typically takes 30-60 seconds per document
                  </p>
                </div>
              </div>
            </div>
          </TooltipProvider>
        )}

        {/* Step 4: Processing - Full Screen Pipeline Canvas */}
        {currentStep === "processing" && (() => {
          // Compute effective values for both standard and segmented extraction
          const isSegmented = !!segmentedJobId;
          const effectiveProgress = isSegmented
            ? ((segmentedJob?.progress ?? 0) * 100)
            : progress;
          const effectiveParts = isSegmented
            ? (segmentedJob?.parts ?? [])
            : parts;
          const effectiveStage: PipelineStage = isSegmented
            ? (segmentedJob?.status === "completed" ? "completed"
               : segmentedJob?.status === "failed" ? "failed"
               : "llm")  // Use "llm" stage for in-progress segmented extraction
            : pipelineStage;
          const effectiveStep = isSegmented
            ? (segmentedJob?.current_step || `Processing ${effectiveParts.filter(p => p.status === "completed").length}/${segmentationResult?.segments.length || 0} segments`)
            : processingStep;

          return (
          <div className="h-full w-full relative bg-background">
            {/* Full Screen Pipeline Flow Canvas */}
            <PipelineFlow
              currentStage={effectiveStage}
              isConsensusMode={enableConsensus}
              ocrProviders={
                (enableConsensus
                  ? [ocrProvider, ...consensusOcrProviders]
                  : [ocrProvider]
                ).filter(Boolean) as string[]
              }
              llmProviders={
                (enableConsensus
                  ? [llmProvider, ...consensusLlmProviders]
                  : [llmProvider]
                ).filter(Boolean) as string[]
              }
              progress={effectiveProgress}
              confidenceThreshold={confidenceThreshold[0]}
              currentConfidence={effectiveParts.length > 0 ? effectiveParts.reduce((acc, p) => acc + (p.confidence || 0), 0) / effectiveParts.length : undefined}
              className="absolute inset-0"
            />

            {/* Top Left: Document Info */}
            <div className="absolute top-4 left-4 z-10">
              <div className="bg-card border border-border rounded-lg px-3 py-2 shadow-sm">
                <div className="flex items-center gap-2">
                  <FileTextIcon size={14} className="text-muted-foreground" />
                  <div>
                    <p className="text-xs font-medium truncate max-w-[200px]">{file?.name}</p>
                    <p className="text-[10px] text-muted-foreground">{selectedSchema?.name}</p>
                  </div>
                </div>
              </div>
            </div>

            {/* Bottom Right: Status Panel */}
            <div className="absolute bottom-4 right-4 z-10">
              <div className="bg-card border border-border rounded-lg p-4 shadow-sm min-w-[280px]">
                {/* Status Header */}
                <div className="flex items-center gap-3 mb-3">
                  {effectiveStage === "completed" ? (
                    <div className="w-9 h-9 rounded-lg bg-green-500 flex items-center justify-center">
                      <CheckIcon size={18} className="text-white" />
                    </div>
                  ) : effectiveStage === "failed" ? (
                    <div className="w-9 h-9 rounded-lg bg-red-500 flex items-center justify-center">
                      <XIcon size={18} className="text-white" />
                    </div>
                  ) : (
                    <div className="w-9 h-9 rounded-lg bg-primary flex items-center justify-center">
                      <Loader2 className="w-4 h-4 text-white animate-spin" />
                    </div>
                  )}
                  <div className="flex-1">
                    <p className="font-semibold text-sm">
                      {effectiveStage === "completed" ? "Extraction Complete" :
                       effectiveStage === "failed" ? "Extraction Failed" :
                       effectiveStep || "Processing..."}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      {isSegmented ? "Multi-document mode" : enableConsensus ? "Multi-provider mode" : "Single provider"}
                    </p>
                  </div>
                </div>

                {/* Progress bar */}
                <div className="mb-3">
                  <div className="flex items-center justify-between text-xs mb-1">
                    <span className="text-muted-foreground">Progress</span>
                    <span className="font-medium">{Math.min(Math.round(effectiveProgress), 100)}%</span>
                  </div>
                  <Progress value={Math.min(effectiveProgress, 100)} className="h-1.5" />
                </div>

                {/* Agent Activity Log - Compact scrolling view */}
                {useAgents && agentEvents.length > 0 && (
                  <div className="mb-3 border-t border-border pt-3">
                    <div className="flex items-center justify-between mb-2">
                      <span className="text-xs text-muted-foreground flex items-center gap-1.5">
                        <Cpu className="w-3 h-3" />
                        Agent Activity
                      </span>
                      {isAgentActive && (
                        <span className="text-[10px] text-green-600 dark:text-green-400 flex items-center gap-1">
                          <span className="w-1.5 h-1.5 rounded-full bg-green-500 animate-pulse" />
                          Live
                        </span>
                      )}
                    </div>
                    <div className="h-[100px] overflow-y-auto bg-muted/30 rounded-md p-2 text-[10px] font-mono space-y-1">
                      {agentEvents.slice(-20).map((event, idx) => {
                        const payload = event.payload || {};
                        const isCompleted = event.type.includes("completed");
                        const isStarted = event.type.includes("started");
                        const isTool = event.type.includes("tool");
                        const confidence = typeof payload.confidence === "number" ? payload.confidence : null;

                        // Build display text based on event type
                        let displayText = "";
                        let statusText = "";

                        if (isTool) {
                          const field = String(payload.field_name || payload.field || "");
                          const tool = String(payload.tool_type || payload.tool || "");
                          displayText = field || tool || "extracting...";
                          statusText = isCompleted ? (confidence ? `${Math.round(confidence * 100)}%` : "done") : "running";
                        } else if (event.type === "agent_started" || event.type === "agent_completed") {
                          const agent = String(payload.agent || "");
                          const agentLabels: Record<string, string> = {
                            "content_analyzer": "Content Analysis",
                            "mapping": "Field Mapping",
                            "extraction": "Extraction",
                            "validation": "Validation",
                          };
                          displayText = agentLabels[agent] || agent || event.type.replace(/_/g, " ");
                          statusText = isCompleted ? "done" : "started";
                        } else if (event.type === "extraction_progress") {
                          displayText = `${String(payload.current_field || "field")} (${payload.completed || 0}/${payload.total || 0})`;
                        } else if (event.type === "content_analysis") {
                          displayText = `${payload.regions || 0} regions, ${payload.pages || 0} pages`;
                        } else if (event.type === "extraction_plan") {
                          displayText = `${payload.total_fields || 0} fields mapped`;
                        } else {
                          displayText = event.type.replace(/_/g, " ");
                        }

                        return (
                          <div key={idx} className="flex items-center gap-1.5 text-muted-foreground">
                            <span className={cn(
                              "w-1.5 h-1.5 rounded-full shrink-0",
                              isCompleted ? "bg-green-500" : isStarted ? "bg-blue-500" : "bg-gray-400"
                            )} />
                            <span className="truncate flex-1 text-foreground">{displayText}</span>
                            {statusText && (
                              <span className={cn(
                                "text-[9px] shrink-0",
                                isCompleted ? "text-green-600" : "text-muted-foreground"
                              )}>
                                {statusText}
                              </span>
                            )}
                          </div>
                        );
                      })}
                    </div>
                  </div>
                )}

                {/* Providers */}
                <div className="flex items-center gap-3 py-2 border-t border-border">
                  <div className="flex items-center gap-2 flex-1">
                    <div className="w-6 h-6 rounded bg-cyan-100 dark:bg-cyan-500/20 flex items-center justify-center">
                      <ScanText className="w-3 h-3 text-cyan-600 dark:text-cyan-400" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground">OCR</p>
                      <p className="text-xs font-medium">
                        {providers?.ocr_providers?.find(p => p.name === ocrProvider)?.display_name || ocrProvider}
                      </p>
                    </div>
                  </div>
                  <div className="flex items-center gap-2 flex-1">
                    <div className="w-6 h-6 rounded bg-rose-100 dark:bg-rose-500/20 flex items-center justify-center">
                      <Cpu className="w-3 h-3 text-rose-600 dark:text-rose-400" />
                    </div>
                    <div>
                      <p className="text-[10px] text-muted-foreground">LLM</p>
                      <p className="text-xs font-medium">
                        {providers?.llm_providers?.find(p => p.name === llmProvider)?.display_name || llmProvider}
                      </p>
                    </div>
                  </div>
                </div>

                {/* View Results Button (merged) */}
                {(pipelineStage === "completed" || (!isExtracting && progress >= 100)) && job && (
                  <Button
                    className="w-full mt-3"
                    onClick={() => router.push(`/jobs/${job.id}`)}
                  >
                    <CheckIcon size={16} className="mr-2" />
                    View Results
                    <ArrowRightIcon size={16} className="ml-2" />
                  </Button>
                )}

                {/* Error retry buttons */}
                {pipelineStage === "failed" && (
                  <div className="flex gap-2 mt-3">
                    <Button variant="outline" className="flex-1" onClick={handleReset}>
                      <RefreshCWIcon size={14} className="mr-1" />
                      Retry
                    </Button>
                    {job && (
                      <Button className="flex-1" onClick={() => router.push(`/jobs/${job.id}`)}>
                        Details
                        <ArrowRightIcon size={14} className="ml-1" />
                      </Button>
                    )}
                  </div>
                )}
              </div>
            </div>
          </div>
          );
        })()}
      </div>
    </div>
  );
}