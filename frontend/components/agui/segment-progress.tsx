"use client";

import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { ScrollArea } from "@/components/ui/scroll-area";
import {
  CheckCircle2,
  Circle,
  Clock,
  FileText,
  Loader2,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";

export interface Segment {
  index: number;
  page_start: number;
  page_end: number;
  page_count: number;
  detected_type?: string;
  type_confidence: number;
  extraction_status: "pending" | "in_progress" | "completed" | "failed";
  fields_extracted?: number;
  error?: string;
  time_ms?: number;
}

export interface SegmentBoundary {
  page_after: number;
  confidence: number;
  signals: string[];
  detection_method: string;
}

interface SegmentProgressProps {
  segments: Segment[];
  boundaries: SegmentBoundary[];
  totalPages: number;
  detectionMethod: string;
  isLive?: boolean;
}

export function SegmentProgress({
  segments,
  boundaries,
  totalPages,
  detectionMethod,
  isLive = false,
}: SegmentProgressProps) {
  const completedCount = segments.filter(
    (s) => s.extraction_status === "completed"
  ).length;
  const failedCount = segments.filter(
    (s) => s.extraction_status === "failed"
  ).length;
  const inProgressCount = segments.filter(
    (s) => s.extraction_status === "in_progress"
  ).length;
  const progress = segments.length > 0
    ? ((completedCount + failedCount) / segments.length) * 100
    : 0;

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-medium flex items-center gap-2">
            <FileText className="h-4 w-4" />
            Document Segmentation
            {isLive && (
              <Badge variant="outline" className="ml-2 text-xs">
                <span className="relative flex h-2 w-2 mr-1">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-green-400 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-green-500"></span>
                </span>
                Live
              </Badge>
            )}
          </CardTitle>
          <Badge variant="secondary" className="text-xs">
            {detectionMethod}
          </Badge>
        </div>
        <div className="flex items-center gap-4 text-xs text-muted-foreground mt-2">
          <span>{segments.length} segments</span>
          <span>{totalPages} pages</span>
          <span>{boundaries.length} boundaries</span>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Progress bar */}
        <div className="space-y-1">
          <div className="flex justify-between text-xs">
            <span>
              {completedCount} of {segments.length} segments extracted
            </span>
            <span>{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2" />
        </div>

        {/* Status summary */}
        <div className="flex gap-4 text-xs">
          <div className="flex items-center gap-1">
            <CheckCircle2 className="h-3 w-3 text-green-500" />
            <span>{completedCount} completed</span>
          </div>
          {inProgressCount > 0 && (
            <div className="flex items-center gap-1">
              <Loader2 className="h-3 w-3 text-blue-500 animate-spin" />
              <span>{inProgressCount} in progress</span>
            </div>
          )}
          {failedCount > 0 && (
            <div className="flex items-center gap-1">
              <XCircle className="h-3 w-3 text-red-500" />
              <span>{failedCount} failed</span>
            </div>
          )}
        </div>

        {/* Segment timeline */}
        <ScrollArea className="h-[200px]">
          <div className="space-y-2">
            {segments.map((segment) => (
              <SegmentItem
                key={segment.index}
                segment={segment}
                boundary={boundaries.find(
                  (b) => b.page_after === segment.page_end
                )}
              />
            ))}
          </div>
        </ScrollArea>
      </CardContent>
    </Card>
  );
}

interface SegmentItemProps {
  segment: Segment;
  boundary?: SegmentBoundary;
}

function SegmentItem({ segment, boundary }: SegmentItemProps) {
  const statusIcon = {
    pending: <Circle className="h-4 w-4 text-muted-foreground" />,
    in_progress: <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />,
    completed: <CheckCircle2 className="h-4 w-4 text-green-500" />,
    failed: <XCircle className="h-4 w-4 text-red-500" />,
  };

  return (
    <div
      className={cn(
        "flex items-center gap-3 p-2 rounded-md border",
        segment.extraction_status === "in_progress" && "border-blue-500/50 bg-blue-500/5",
        segment.extraction_status === "completed" && "border-green-500/30 bg-green-500/5",
        segment.extraction_status === "failed" && "border-red-500/30 bg-red-500/5"
      )}
    >
      {statusIcon[segment.extraction_status]}

      <div className="flex-1 min-w-0">
        <div className="flex items-center gap-2">
          <span className="text-sm font-medium">
            Segment {segment.index + 1}
          </span>
          <Badge variant="outline" className="text-xs">
            Pages {segment.page_start}-{segment.page_end}
          </Badge>
          {segment.detected_type && (
            <Badge variant="secondary" className="text-xs">
              {segment.detected_type}
            </Badge>
          )}
        </div>

        <div className="flex items-center gap-2 text-xs text-muted-foreground mt-1">
          {segment.extraction_status === "completed" && (
            <>
              {segment.fields_extracted !== undefined && (
                <span>{segment.fields_extracted} fields</span>
              )}
              {segment.time_ms !== undefined && (
                <span className="flex items-center gap-1">
                  <Clock className="h-3 w-3" />
                  {segment.time_ms}ms
                </span>
              )}
              {segment.type_confidence > 0 && (
                <span>{Math.round(segment.type_confidence * 100)}% confidence</span>
              )}
            </>
          )}
          {segment.extraction_status === "failed" && segment.error && (
            <span className="text-red-500 truncate">{segment.error}</span>
          )}
          {segment.extraction_status === "in_progress" && (
            <span className="text-blue-500">Extracting...</span>
          )}
          {segment.extraction_status === "pending" && (
            <span>Waiting...</span>
          )}
        </div>
      </div>

      {boundary && (
        <div className="text-xs text-muted-foreground">
          <span className="opacity-50">
            {boundary.signals.join(", ")}
          </span>
        </div>
      )}
    </div>
  );
}
