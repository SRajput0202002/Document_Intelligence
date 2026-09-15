"use client";

import { useMemo, useCallback, useRef, useEffect } from "react";
import ReactFlow, {
  Node,
  Edge,
  Position,
  Handle,
  Controls,
  ControlButton,
  Background,
  BackgroundVariant,
  useNodesState,
  useEdgesState,
  Connection,
  addEdge,
  ReactFlowProvider,
  useReactFlow,
} from "reactflow";
import "reactflow/dist/style.css";
import { cn } from "@/lib/utils";
import { LayoutGrid } from "lucide-react";

// Icons
import { Play, ScanText, Cpu, Gauge, Sparkles, X, Loader2, Settings } from "lucide-react";

export type PipelineStage =
  | "idle"
  | "configuration"
  | "ocr"
  | "ocr_consensus"
  | "llm"
  | "llm_consensus"
  | "validation"
  | "comparison"
  | "preparing"
  | "completed"
  | "failed";

interface PipelineFlowProps {
  currentStage: PipelineStage;
  isConsensusMode: boolean;
  ocrProviders: string[];
  llmProviders: string[];
  progress: number;
  confidenceThreshold: number;
  currentConfidence?: number;
  className?: string;
  /** When true, initial view is zoomed in more (workflow test dialog only; keep default elsewhere). */
  embedInDialog?: boolean;
}

// Subtle, professional colors (no gradients)
const stageColors = {
  configuration: {
    bg: "bg-emerald-50",
    border: "border-emerald-200",
    iconBg: "bg-emerald-500",
    text: "text-emerald-700",
    line: "#10b981",
  },
  ocr: {
    bg: "bg-violet-50",
    border: "border-violet-200",
    iconBg: "bg-violet-500",
    text: "text-violet-700",
    line: "#8b5cf6",
  },
  llm: {
    bg: "bg-rose-50",
    border: "border-rose-200",
    iconBg: "bg-rose-500",
    text: "text-rose-700",
    line: "#f43f5e",
  },
  validation: {
    bg: "bg-amber-50",
    border: "border-amber-200",
    iconBg: "bg-amber-500",
    text: "text-amber-700",
    line: "#f59e0b",
  },
  preparing: {
    bg: "bg-teal-50",
    border: "border-teal-200",
    iconBg: "bg-teal-500",
    text: "text-teal-700",
    line: "#14b8a6",
  },
};

// Custom node component - clean, subtle design
function PipelineNode({ data }: { data: {
  label: string;
  icon: "play" | "scan" | "cpu" | "gauge" | "sparkles";
  status: "pending" | "active" | "completed" | "failed";
  subtitle?: string;
  colorKey: keyof typeof stageColors;
  isFirst?: boolean;
  isLast?: boolean;
  showSettings?: boolean;
  onSettingsClick?: () => void;
  /** Larger cards + type (workflow test dialog only). */
  embedLarge?: boolean;
} }) {
  const { label, icon, status, subtitle, colorKey, isFirst, isLast, showSettings, onSettingsClick, embedLarge } = data;
  const colors = stageColors[colorKey] || stageColors.configuration;

  const IconComponent = {
    play: Play,
    scan: ScanText,
    cpu: Cpu,
    gauge: Gauge,
    sparkles: Sparkles,
  }[icon] || Play;

  return (
    <div className="relative">
      {/* Card */}
      <div
        className={cn(
          "rounded-xl border-2 shadow-sm overflow-hidden transition-all duration-200",
          embedLarge ? "min-w-[248px]" : "min-w-[180px]",
          status === "pending" && "bg-gray-50 border-gray-200 opacity-50",
          status === "active" && `${colors.bg} ${colors.border} shadow-md`,
          status === "completed" && `${colors.bg} ${colors.border}`,
          status === "failed" && "bg-red-50 border-red-300"
        )}
      >
        {/* Header row */}
        <div className={cn("flex items-center", embedLarge ? "px-4 py-3 gap-3" : "px-3 py-2.5 gap-2.5")}>
          {/* Icon */}
          <div
            className={cn(
              "rounded-lg flex items-center justify-center",
              embedLarge ? "w-10 h-10" : "w-8 h-8",
              status === "pending" ? "bg-gray-300" : colors.iconBg
            )}
          >
            {status === "active" ? (
              <Loader2 className={cn("text-white animate-spin", embedLarge ? "w-5 h-5" : "w-4 h-4")} />
            ) : status === "failed" ? (
              <X className={cn("text-white", embedLarge ? "w-5 h-5" : "w-4 h-4")} />
            ) : (
              <IconComponent className={cn("text-white", embedLarge ? "w-5 h-5" : "w-4 h-4")} />
            )}
          </div>

          {/* Title */}
          <span className={cn(
            "font-medium flex-1",
            embedLarge ? "text-base" : "text-sm",
            status === "pending" ? "text-gray-400" : "text-gray-800"
          )}>
            {label}
          </span>

          {/* Settings button */}
          {showSettings && (
            <button
              onClick={(e) => {
                e.stopPropagation();
                onSettingsClick?.();
              }}
              className={cn(
                "flex items-center justify-center rounded hover:bg-black/5 transition-colors",
                embedLarge ? "w-7 h-7" : "w-6 h-6"
              )}
            >
              <Settings className={cn("text-gray-400", embedLarge ? "w-4 h-4" : "w-3.5 h-3.5")} />
            </button>
          )}
        </div>

        {/* Subtitle */}
        <div className={cn(embedLarge ? "px-4 pb-3" : "px-3 pb-2.5")}>
          <p className={cn(
            embedLarge ? "text-sm" : "text-xs",
            status === "pending" ? "text-gray-400" : "text-gray-500"
          )}>
            {subtitle}
          </p>
        </div>
      </div>

      {/* Left handle */}
      {!isFirst && (
        <Handle
          type="target"
          position={Position.Left}
          className="!w-2.5 !h-2.5 !rounded-full !bg-gray-400 !border-2 !border-white"
          style={{ left: -5 }}
        />
      )}

      {/* Right handle */}
      {!isLast && (
        <Handle
          type="source"
          position={Position.Right}
          className="!w-2.5 !h-2.5 !rounded-full !bg-gray-400 !border-2 !border-white"
          style={{ right: -5 }}
        />
      )}
    </div>
  );
}

const nodeTypes = {
  pipeline: PipelineNode,
};

// Inner component that uses ReactFlow hooks
function PipelineFlowInner({
  currentStage,
  isConsensusMode,
  ocrProviders,
  llmProviders,
  confidenceThreshold,
  className,
  embedInDialog = false,
}: PipelineFlowProps) {
  const reactFlowWrapper = useRef<HTMLDivElement>(null);
  const { fitView } = useReactFlow();

  const fitViewOptions = useMemo(
    () =>
      embedInDialog
        ? { padding: 0.06, minZoom: 0.25, maxZoom: 2.75 }
        : { padding: 0.3, minZoom: 0.4, maxZoom: 1.5 },
    [embedInDialog]
  );

  const applyDialogFit = useCallback(() => {
    fitView({ ...fitViewOptions, duration: 0 });
  }, [fitView, fitViewOptions]);

  useEffect(() => {
    if (!embedInDialog) return;
    const t = window.setTimeout(applyDialogFit, 0);
    const t2 = window.setTimeout(applyDialogFit, 120);
    return () => {
      window.clearTimeout(t);
      window.clearTimeout(t2);
    };
  }, [embedInDialog, applyDialogFit]);

  const getNodeStatus = useCallback(
    (nodeStage: PipelineStage): "pending" | "active" | "completed" | "failed" => {
      const stageOrder: PipelineStage[] = isConsensusMode
        ? ["configuration", "ocr_consensus", "llm_consensus", "comparison", "preparing", "completed"]
        : ["configuration", "ocr", "llm", "validation", "preparing", "completed"];

      const currentIndex = stageOrder.indexOf(currentStage);
      const nodeIndex = stageOrder.indexOf(nodeStage);

      if (currentStage === "failed") {
        if (nodeIndex < currentIndex) return "completed";
        if (nodeIndex === currentIndex) return "failed";
        return "pending";
      }

      if (currentStage === "completed") {
        return "completed";
      }

      if (nodeIndex < currentIndex) return "completed";
      if (nodeIndex === currentIndex) return "active";
      return "pending";
    },
    [currentStage, isConsensusMode]
  );

  const initialNodes: Node[] = useMemo(() => {
    const yPos = embedInDialog ? 72 : 100;
    const spacing = embedInDialog ? 300 : 240;
    const startX = embedInDialog ? 36 : 80;
    const large = embedInDialog;

    return [
      {
        id: "start",
        type: "pipeline",
        position: { x: startX, y: yPos },
        data: {
          label: "Start",
          icon: "play",
          status: getNodeStatus("configuration"),
          subtitle: "Entry point",
          colorKey: "configuration",
          isFirst: true,
          isLast: false,
          embedLarge: large,
        },
      },
      {
        id: "ocr",
        type: "pipeline",
        position: { x: startX + spacing, y: yPos },
        data: {
          label: "OCR Extraction",
          icon: "scan",
          status: getNodeStatus(isConsensusMode ? "ocr_consensus" : "ocr"),
          subtitle: ocrProviders[0] || "Using settings",
          colorKey: "ocr",
          isFirst: false,
          isLast: false,
          showSettings: true,
          embedLarge: large,
        },
      },
      {
        id: "llm",
        type: "pipeline",
        position: { x: startX + spacing * 2, y: yPos },
        data: {
          label: "LLM Extraction",
          icon: "cpu",
          status: getNodeStatus(isConsensusMode ? "llm_consensus" : "llm"),
          subtitle: llmProviders[0] || "ollama",
          colorKey: "llm",
          isFirst: false,
          isLast: false,
          showSettings: true,
          embedLarge: large,
        },
      },
      {
        id: "validation",
        type: "pipeline",
        position: { x: startX + spacing * 3, y: yPos },
        data: {
          label: "Validation",
          icon: "gauge",
          status: getNodeStatus(isConsensusMode ? "comparison" : "validation"),
          subtitle: `Threshold: ${confidenceThreshold}%`,
          colorKey: "validation",
          isFirst: false,
          isLast: false,
          showSettings: true,
          embedLarge: large,
        },
      },
      {
        id: "finalize",
        type: "pipeline",
        position: { x: startX + spacing * 4, y: yPos },
        data: {
          label: "Finalize",
          icon: "sparkles",
          status: getNodeStatus("preparing"),
          subtitle: "Prepare results",
          colorKey: "preparing",
          isFirst: false,
          isLast: true,
          embedLarge: large,
        },
      },
    ];
  }, [getNodeStatus, isConsensusMode, ocrProviders, llmProviders, confidenceThreshold, embedInDialog]);

  const initialEdges: Edge[] = useMemo(() => {
    const edges: Edge[] = [
      {
        id: "e-start-ocr",
        source: "start",
        target: "ocr",
        type: "default",
        animated: true,
        style: { stroke: stageColors.ocr.line, strokeWidth: 2 },
      },
      {
        id: "e-ocr-llm",
        source: "ocr",
        target: "llm",
        type: "default",
        animated: true,
        style: { stroke: stageColors.llm.line, strokeWidth: 2 },
      },
      {
        id: "e-llm-validation",
        source: "llm",
        target: "validation",
        type: "default",
        animated: true,
        style: { stroke: stageColors.validation.line, strokeWidth: 2 },
      },
      {
        id: "e-validation-finalize",
        source: "validation",
        target: "finalize",
        type: "default",
        animated: true,
        style: { stroke: stageColors.preparing.line, strokeWidth: 2 },
      },
    ];
    return edges;
  }, []);

  const [nodes, setNodes, onNodesChange] = useNodesState(initialNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState(initialEdges);

  // Allow connecting nodes
  const onConnect = useCallback(
    (params: Connection) => setEdges((eds) => addEdge({
      ...params,
      animated: true,
      style: { stroke: "#94a3b8", strokeWidth: 2 },
    }, eds)),
    [setEdges]
  );

  // Auto-organize nodes in a horizontal line
  const onAutoOrganize = useCallback(() => {
    const yPos = embedInDialog ? 72 : 100;
    const spacing = embedInDialog ? 300 : 240;
    const startX = embedInDialog ? 36 : 80;

    setNodes((nds) =>
      nds.map((node, index) => ({
        ...node,
        position: { x: startX + spacing * index, y: yPos },
      }))
    );

    setTimeout(() => fitView(fitViewOptions), 50);
  }, [setNodes, fitView, fitViewOptions, embedInDialog]);

  // Update nodes when props change
  useMemo(() => {
    setNodes(initialNodes);
  }, [initialNodes, setNodes]);

  return (
    <div ref={reactFlowWrapper} className={cn("w-full h-full", className)}>
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        nodeTypes={nodeTypes}
        fitView
        fitViewOptions={fitViewOptions}
        onInit={embedInDialog ? () => applyDialogFit() : undefined}
        nodesDraggable={true}
        nodesConnectable={true}
        elementsSelectable={true}
        selectNodesOnDrag={false}
        panOnDrag={true}
        zoomOnScroll={true}
        zoomOnPinch={true}
        zoomOnDoubleClick={false}
        proOptions={{ hideAttribution: true }}
        className="bg-background"
      >
        {/* Built-in Controls with auto-organize */}
        <Controls
          showZoom={true}
          showFitView={true}
          showInteractive={false}
          position="bottom-left"
          className="!bg-card !border !border-border !rounded-lg !shadow-sm"
        >
          <ControlButton onClick={onAutoOrganize} title="Auto-organize">
            <LayoutGrid className="w-3 h-3" />
          </ControlButton>
        </Controls>

        {/* Subtle dot background matching theme */}
        <Background
          variant={BackgroundVariant.Dots}
          gap={20}
          size={1}
          color="hsl(var(--muted-foreground))"
          className="opacity-20"
        />
      </ReactFlow>
    </div>
  );
}

// Wrapper with ReactFlowProvider
export function PipelineFlow(props: PipelineFlowProps) {
  return (
    <ReactFlowProvider>
      <PipelineFlowInner {...props} />
    </ReactFlowProvider>
  );
}
