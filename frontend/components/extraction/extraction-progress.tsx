"use client";

import { Circle, Loader2, XCircle } from "lucide-react";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { cn } from "@/lib/utils";
import type { JobPart } from "@/lib/api";

interface ExtractionProgressProps {
  progress: number;
  currentStep: string;
  parts: JobPart[];
}

export function ExtractionProgress({
  progress,
  currentStep,
  parts,
}: ExtractionProgressProps) {
  const getPartIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CircleCheckIcon size={16} className="text-green-500" />;
      case "processing":
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
      case "failed":
        return <XCircle className="h-4 w-4 text-red-500" />;
      default:
        return <Circle className="h-4 w-4 text-muted-foreground" />;
    }
  };

  return (
    <Card className="mt-4">
      <CardHeader className="py-3 px-4">
        <CardTitle className="text-lg flex items-center gap-2">
          <Loader2 className="h-5 w-5 animate-spin" />
          Extracting...
        </CardTitle>
      </CardHeader>
      <CardContent className="p-4 pt-0 space-y-4">
        {/* Overall progress */}
        <div className="space-y-2">
          <div className="flex items-center justify-between text-sm">
            <span className="text-muted-foreground">{currentStep}</span>
            <span className="font-medium">{Math.round(progress)}%</span>
          </div>
          <Progress value={progress} className="h-2" />
        </div>

        {/* Part progress */}
        {parts.length > 0 && (
          <div className="space-y-2">
            <div className="text-sm font-medium">Parts</div>
            <div className="grid grid-cols-2 gap-2">
              {parts.map((part) => (
                <div
                  key={part.part_name}
                  className={cn(
                    "flex items-center gap-2 text-sm p-2 rounded-md",
                    part.status === "completed" && "bg-green-50 dark:bg-green-950/20",
                    part.status === "processing" && "bg-blue-50 dark:bg-blue-950/20",
                    part.status === "failed" && "bg-red-50 dark:bg-red-950/20",
                    part.status === "pending" && "bg-muted/50"
                  )}
                >
                  {getPartIcon(part.status)}
                  <span className="capitalize">
                    {part.part_name.replace("-", " ")}
                  </span>
                </div>
              ))}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
