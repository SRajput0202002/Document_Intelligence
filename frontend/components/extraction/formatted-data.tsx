"use client";

import { useState } from "react";
import {
  FileJson,
  XCircle,
  AlertCircle,
  ChevronRight,
} from "lucide-react";
import { CopyIcon } from "@/components/ui/copy";
import { DownloadIcon } from "@/components/ui/download";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { ChevronDownIcon } from "@/components/ui/chevron-down";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { toast } from "@/components/ui/toast";
import { cn, formatCost, formatDuration } from "@/lib/utils";
import type { Job, JobPart } from "@/lib/api";

interface ExtractionResultsProps {
  job: Job | null;
  parts: JobPart[];
  error: string | null;
  isExtracting: boolean;
}

export function ExtractionResults({
  job,
  parts,
  error,
  isExtracting,
}: ExtractionResultsProps) {
  const [selectedPart, setSelectedPart] = useState<string>("part-0");

  const activeParts = parts.filter((p) => p.status === "completed" || p.extracted_data);
  const selectedPartData = parts.find((p) => p.part_name === selectedPart);

  const handleCopy = async (data: unknown) => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(data, null, 2));
      toast({
        title: "Copied",
        description: "JSON copied to clipboard",
      });
    } catch {
      toast({
        title: "Failed to copy",
        description: "Could not copy to clipboard",
        variant: "destructive",
      });
    }
  };

  const handleDownload = (data: unknown, filename: string) => {
    const blob = new Blob([JSON.stringify(data, null, 2)], {
      type: "application/json",
    });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
  };

  const downloadAllParts = () => {
    const allData = parts.reduce((acc, part) => {
      if (part.extracted_data) {
        acc[part.part_name] = part.extracted_data;
      }
      return acc;
    }, {} as Record<string, unknown>);

    handleDownload(
      { metadata: { job_id: job?.id, doc_type: job?.doc_type }, parts: allData },
      `extraction_${job?.id || "result"}.json`
    );
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return (
          <Badge variant="success" className="gap-1">
            <CircleCheckIcon size={12} />
            Completed
          </Badge>
        );
      case "failed":
        return (
          <Badge variant="destructive" className="gap-1">
            <XCircle className="h-3 w-3" />
            Failed
          </Badge>
        );
      default:
        return (
          <Badge variant="secondary" className="gap-1">
            <AlertCircle className="h-3 w-3" />
            {status}
          </Badge>
        );
    }
  };

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="flex-none py-3 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <FileJson className="h-5 w-5" />
            Results
          </CardTitle>
          {activeParts.length > 0 && (
            <Button variant="outline" size="sm" onClick={downloadAllParts}>
              <DownloadIcon size={16} className="mr-1" />
              Download All
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 p-4 pt-0 min-h-0">
        {error ? (
          <div className="flex flex-col items-center justify-center h-full text-destructive">
            <XCircle className="h-12 w-12 mb-4" />
            <p className="text-lg font-medium">Extraction Failed</p>
            <p className="text-sm text-center mt-2">{error}</p>
          </div>
        ) : !job && !isExtracting ? (
          <div className="flex flex-col items-center justify-center h-full text-muted-foreground">
            <FileJson className="h-12 w-12 mb-4" />
            <p className="text-lg font-medium">No Results Yet</p>
            <p className="text-sm text-center mt-2">
              Upload a document and start extraction to see results
            </p>
          </div>
        ) : (
          <div className="flex flex-col h-full">
            {/* Job Summary */}
            {job && job.status === "completed" && (
              <div className="flex-none grid grid-cols-3 gap-2 mb-4 text-sm">
                <div className="p-2 rounded-md bg-muted/50">
                  <div className="text-muted-foreground">Time</div>
                  <div className="font-medium">
                    {job.completed_at && job.started_at
                      ? formatDuration(
                          (new Date(job.completed_at).getTime() -
                            new Date(job.started_at).getTime()) /
                            1000
                        )
                      : "-"}
                  </div>
                </div>
                <div className="p-2 rounded-md bg-muted/50">
                  <div className="text-muted-foreground">Tokens</div>
                  <div className="font-medium">
                    {(job.input_tokens + job.output_tokens).toLocaleString()}
                  </div>
                </div>
                <div className="p-2 rounded-md bg-muted/50">
                  <div className="text-muted-foreground">Cost</div>
                  <div className="font-medium">{formatCost(job.estimated_cost)}</div>
                </div>
              </div>
            )}

            {/* Part Tabs */}
            {parts.length > 0 && (
              <Tabs
                value={selectedPart}
                onValueChange={setSelectedPart}
                className="flex flex-col flex-1 min-h-0"
              >
                <TabsList className="flex-none flex-wrap h-auto gap-1 p-1">
                  {parts.map((part) => (
                    <TabsTrigger
                      key={part.part_name}
                      value={part.part_name}
                      className={cn(
                        "text-xs",
                        part.status === "completed" && "data-[state=active]:bg-green-100 dark:data-[state=active]:bg-green-900/20",
                        part.status === "failed" && "data-[state=active]:bg-red-100 dark:data-[state=active]:bg-red-900/20"
                      )}
                    >
                      {part.part_name.replace("-", " ").toUpperCase()}
                      {part.status === "completed" && (
                        <CircleCheckIcon size={12} className="ml-1 text-green-500" />
                      )}
                      {part.status === "failed" && (
                        <XCircle className="h-3 w-3 ml-1 text-red-500" />
                      )}
                    </TabsTrigger>
                  ))}
                </TabsList>

                {parts.map((part) => (
                  <TabsContent
                    key={part.part_name}
                    value={part.part_name}
                    className="flex-1 mt-2 min-h-0"
                  >
                    <div className="flex flex-col h-full">
                      {/* Part header */}
                      <div className="flex-none flex items-center justify-between mb-2">
                        <div className="flex items-center gap-2">
                          {getStatusBadge(part.status)}
                          {part.confidence > 0 && (
                            <Badge variant="outline">
                              {Math.round(part.confidence * 100)}% confidence
                            </Badge>
                          )}
                        </div>
                        {part.extracted_data && (
                          <div className="flex items-center gap-1">
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() => handleCopy(part.extracted_data)}
                            >
                              <CopyIcon size={16} />
                            </Button>
                            <Button
                              variant="ghost"
                              size="icon"
                              onClick={() =>
                                handleDownload(
                                  part.extracted_data,
                                  `${part.part_name}.json`
                                )
                              }
                            >
                              <DownloadIcon size={16} />
                            </Button>
                          </div>
                        )}
                      </div>

                      {/* Part content */}
                      <ScrollArea className="flex-1 border rounded-md">
                        <div className="p-4">
                          {part.error ? (
                            <div className="text-sm text-destructive">{part.error}</div>
                          ) : part.extracted_data ? (
                            <JsonTree data={part.extracted_data} />
                          ) : (
                            <div className="text-sm text-muted-foreground">
                              {part.status === "processing"
                                ? "Extracting..."
                                : "No data available"}
                            </div>
                          )}
                        </div>
                      </ScrollArea>
                    </div>
                  </TabsContent>
                ))}
              </Tabs>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// JSON Tree Component
interface JsonTreeProps {
  data: unknown;
  level?: number;
}

function JsonTree({ data, level = 0 }: JsonTreeProps) {
  if (data === null) return <span className="text-muted-foreground">null</span>;
  if (data === undefined) return <span className="text-muted-foreground">undefined</span>;

  if (typeof data !== "object") {
    if (typeof data === "string") {
      // Signature / image payloads — show thumbnail instead of huge base64
      if (data.startsWith("data:image/")) {
        return (
          <span className="inline-flex flex-col gap-1 align-middle">
            {/* eslint-disable-next-line @next/next/no-img-element */}
            <img
              src={data}
              alt="Extracted feature"
              className="max-h-24 max-w-[200px] rounded border bg-white object-contain"
            />
            <span className="text-xs text-muted-foreground">image ({Math.round(data.length / 1024)} KB)</span>
          </span>
        );
      }
      const display = data.length > 120 ? `${data.slice(0, 117)}...` : data;
      return <span className="text-green-600 dark:text-green-400">"{display}"</span>;
    }
    if (typeof data === "number") {
      return <span className="text-blue-600 dark:text-blue-400">{data}</span>;
    }
    if (typeof data === "boolean") {
      return (
        <span className="text-purple-600 dark:text-purple-400">
          {data.toString()}
        </span>
      );
    }
    return <span>{String(data)}</span>;
  }

  if (Array.isArray(data)) {
    if (data.length === 0) return <span className="text-muted-foreground">[]</span>;
    // Compact barcode chips when items look like barcode hits
    const looksLikeBarcodes = data.every(
      (item) =>
        item &&
        typeof item === "object" &&
        !Array.isArray(item) &&
        "kind" in (item as object) &&
        "value" in (item as object)
    );
    if (looksLikeBarcodes) {
      return (
        <div className="inline-flex flex-wrap gap-1.5 py-1">
          {data.map((item, i) => {
            const bc = item as { kind?: string; value?: string; page?: number };
            return (
              <span
                key={i}
                className="inline-flex items-center gap-1 rounded-full border border-indigo-200 bg-indigo-50 px-2 py-0.5 text-xs text-indigo-800"
                title={bc.page != null ? `page ${bc.page}` : undefined}
              >
                <span className="font-medium">{bc.kind || "Code"}</span>
                <span className="max-w-[180px] truncate">{bc.value || ""}</span>
              </span>
            );
          })}
        </div>
      );
    }
    return <JsonArray data={data} level={level} />;
  }

  // Signature object preview
  if (
    data &&
    typeof data === "object" &&
    "present" in data &&
    ("image_base64" in data || "signature_type" in data)
  ) {
    const sig = data as {
      present?: boolean;
      signature_type?: string;
      page?: number | null;
      image_base64?: string | null;
      confidence?: number | null;
    };
    return (
      <div className="inline-flex flex-col gap-1 rounded border border-fuchsia-200 bg-fuchsia-50/50 p-2 text-xs">
        <div className="flex items-center gap-2 text-fuchsia-900">
          <span className="font-medium">{sig.present ? "Signed" : "Not signed"}</span>
          {sig.signature_type ? <span>({sig.signature_type})</span> : null}
          {sig.page != null ? <span>· page {sig.page}</span> : null}
          {sig.confidence != null ? (
            <span>· conf {Number(sig.confidence).toFixed(2)}</span>
          ) : null}
        </div>
        {sig.image_base64 ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={sig.image_base64}
            alt="Signature crop"
            className="max-h-28 max-w-[240px] rounded border bg-white object-contain"
          />
        ) : null}
      </div>
    );
  }

  const entries = Object.entries(data);
  if (entries.length === 0) return <span className="text-muted-foreground">{"{}"}</span>;

  return <JsonObject data={data as Record<string, unknown>} level={level} />;
}

function JsonObject({
  data,
  level,
}: {
  data: Record<string, unknown>;
  level: number;
}) {
  const [expanded, setExpanded] = useState(level < 2);
  const entries = Object.entries(data);

  return (
    <div className="json-tree">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-left hover:bg-muted/50 rounded px-1 -ml-1"
      >
        {expanded ? (
          <ChevronDownIcon size={12} />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span className="text-muted-foreground">
          {expanded ? "{" : `{ ${entries.length} keys }`}
        </span>
      </button>
      {expanded && (
        <div className="ml-4 border-l pl-2">
          {entries.map(([key, value]) => (
            <div key={key} className="py-0.5">
              <span className="text-cyan-600 dark:text-cyan-400">{key}</span>
              <span className="text-muted-foreground">: </span>
              <JsonTree data={value} level={level + 1} />
            </div>
          ))}
        </div>
      )}
      {expanded && <span className="text-muted-foreground">{"}"}</span>}
    </div>
  );
}

function JsonArray({ data, level }: { data: unknown[]; level: number }) {
  const [expanded, setExpanded] = useState(level < 2);

  return (
    <div className="json-tree">
      <button
        onClick={() => setExpanded(!expanded)}
        className="flex items-center gap-1 text-left hover:bg-muted/50 rounded px-1 -ml-1"
      >
        {expanded ? (
          <ChevronDownIcon size={12} />
        ) : (
          <ChevronRight className="h-3 w-3" />
        )}
        <span className="text-muted-foreground">
          {expanded ? "[" : `[ ${data.length} items ]`}
        </span>
      </button>
      {expanded && (
        <div className="ml-4 border-l pl-2">
          {data.map((item, idx) => (
            <div key={idx} className="py-0.5">
              <span className="text-muted-foreground mr-2">{idx}:</span>
              <JsonTree data={item} level={level + 1} />
            </div>
          ))}
        </div>
      )}
      {expanded && <span className="text-muted-foreground">]</span>}
    </div>
  );
}
