/**
 * AGUI (Agent GUI) Components
 *
 * Real-time visualization components for multi-agent extraction.
 * These components display agent activity, tool executions, and progress
 * via WebSocket events.
 */

export { AgentActivity, type AgentEvent } from "./agent-activity";
export { AgentStep, type AgentStepData } from "./agent-step";
export { ToolExecution, type ToolExecutionData } from "./tool-execution";

// Segmentation components
export { SegmentationConfig } from "./segmentation-config";
export type { SegmentationConfigValues } from "./segmentation-config";

export { SegmentPreview } from "./segment-preview";
export type { PreviewSegment, PreviewBoundary } from "./segment-preview";

export { SegmentProgress } from "./segment-progress";
export type { Segment, SegmentBoundary } from "./segment-progress";
