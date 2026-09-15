"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  AlertCircle,
  Check,
  FileText,
  Layers,
  Scissors,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface PreviewSegment {
  index: number;
  page_start: number;
  page_end: number;
  page_count: number;
  detected_type?: string;
  type_confidence: number;
}

export interface PreviewBoundary {
  page_after: number;
  confidence: number;
  signals: string[];
  detection_method: string;
}

interface SegmentPreviewProps {
  segments: PreviewSegment[];
  boundaries: PreviewBoundary[];
  totalPages: number;
  detectionMethod: string;
  processingTime: number;
  llmTokensUsed: number;
  heuristicOnly: boolean;
  availableSchemas?: { id: string; name: string; doc_type: string }[];
  onSchemaChange?: (segmentIndex: number, schemaId: string) => void;
  onStartExtraction?: () => void;
  isLoading?: boolean;
}

export function SegmentPreview({
  segments,
  boundaries,
  totalPages,
  detectionMethod,
  processingTime,
  llmTokensUsed,
  heuristicOnly,
  availableSchemas = [],
  onSchemaChange,
  onStartExtraction,
  isLoading = false,
}: SegmentPreviewProps) {
  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <Scissors className="h-4 w-4" />
            Segmentation Preview
          </CardTitle>
          <div className="flex items-center gap-2">
            {heuristicOnly && (
              <Badge variant="outline" className="text-xs bg-green-500/10 text-green-600">
                <Sparkles className="h-3 w-3 mr-1" />
                Zero LLM Cost
              </Badge>
            )}
            <Badge variant="secondary" className="text-xs">
              {detectionMethod}
            </Badge>
          </div>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground mt-2">
          <span>{segments.length} segments detected</span>
          <span>{totalPages} total pages</span>
          <span>{processingTime.toFixed(2)}s</span>
          {llmTokensUsed > 0 && <span>{llmTokensUsed} tokens</span>}
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Visual page timeline */}
        <div className="relative">
          <div className="flex h-8 rounded-md overflow-hidden border">
            {segments.map((segment, idx) => {
              const width = (segment.page_count / totalPages) * 100;
              const colors = [
                "bg-blue-500/30",
                "bg-green-500/30",
                "bg-purple-500/30",
                "bg-orange-500/30",
                "bg-pink-500/30",
                "bg-cyan-500/30",
              ];
              return (
                <div
                  key={segment.index}
                  className={cn(
                    "relative flex items-center justify-center text-xs font-medium border-r last:border-r-0",
                    colors[idx % colors.length]
                  )}
                  style={{ width: `${width}%` }}
                  title={`Segment ${segment.index + 1}: Pages ${segment.page_start}-${segment.page_end}`}
                >
                  {width > 8 && (
                    <span className="truncate px-1">
                      {segment.page_start}-{segment.page_end}
                    </span>
                  )}
                </div>
              );
            })}
          </div>
          {/* Boundary markers */}
          {boundaries.map((boundary) => {
            const position = (boundary.page_after / totalPages) * 100;
            return (
              <div
                key={boundary.page_after}
                className="absolute top-0 h-full flex flex-col items-center"
                style={{ left: `${position}%` }}
              >
                <div className="w-0.5 h-full bg-red-500/50" />
                <div className="absolute -bottom-5 text-[10px] text-muted-foreground whitespace-nowrap">
                  {Math.round(boundary.confidence * 100)}%
                </div>
              </div>
            );
          })}
        </div>

        {/* Segment list */}
        <ScrollArea className="h-[250px]">
          <div className="space-y-2">
            {segments.map((segment) => (
              <SegmentPreviewItem
                key={segment.index}
                segment={segment}
                boundary={boundaries.find(
                  (b) => b.page_after === segment.page_end
                )}
                availableSchemas={availableSchemas}
                onSchemaChange={onSchemaChange}
              />
            ))}
          </div>
        </ScrollArea>

        {/* Start extraction button */}
        {onStartExtraction && (
          <Button
            onClick={onStartExtraction}
            disabled={isLoading || segments.length === 0}
            className="w-full"
          >
            {isLoading ? (
              <>
                <Layers className="h-4 w-4 mr-2 animate-spin" />
                Starting extraction...
              </>
            ) : (
              <>
                <Check className="h-4 w-4 mr-2" />
                Start Extraction ({segments.length} segments)
              </>
            )}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

interface SegmentPreviewItemProps {
  segment: PreviewSegment;
  boundary?: PreviewBoundary;
  availableSchemas?: { id: string; name: string; doc_type: string }[];
  onSchemaChange?: (segmentIndex: number, schemaId: string) => void;
}

function SegmentPreviewItem({
  segment,
  boundary,
  availableSchemas = [],
  onSchemaChange,
}: SegmentPreviewItemProps) {
  return (
    <div className="flex items-center gap-3 p-3 rounded-md border bg-muted/30">
      <div className="flex items-center justify-center h-8 w-8 rounded-full bg-primary/10 text-primary text-sm font-medium">
        {segment.index + 1}
      </div>

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">
            Pages {segment.page_start} - {segment.page_end}
          </span>
          <Badge variant="outline" className="text-xs">
            {segment.page_count} {segment.page_count === 1 ? "page" : "pages"}
          </Badge>
        </div>

        <div className="flex items-center gap-2 mt-1">
          {segment.detected_type ? (
            <Badge variant="secondary" className="text-xs">
              <FileText className="h-3 w-3 mr-1" />
              {segment.detected_type}
              {segment.type_confidence > 0 && (
                <span className="ml-1 opacity-70">
                  ({Math.round(segment.type_confidence * 100)}%)
                </span>
              )}
            </Badge>
          ) : (
            <Badge variant="outline" className="text-xs text-muted-foreground">
              <AlertCircle className="h-3 w-3 mr-1" />
              Unknown type
            </Badge>
          )}

          {boundary && (
            <span className="text-xs text-muted-foreground">
              Boundary: {boundary.signals.slice(0, 2).join(", ")}
            </span>
          )}
        </div>
      </div>

      {/* Schema selector for heterogeneous mode */}
      {availableSchemas.length > 0 && onSchemaChange && (
        <Select
          defaultValue={
            availableSchemas.find((s) => s.doc_type === segment.detected_type)
              ?.id
          }
          onValueChange={(value) => onSchemaChange(segment.index, value)}
        >
          <SelectTrigger className="w-[140px] h-8 text-xs">
            <SelectValue placeholder="Select schema" />
          </SelectTrigger>
          <SelectContent>
            {availableSchemas.map((schema) => (
              <SelectItem key={schema.id} value={schema.id} className="text-xs">
                {schema.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}
