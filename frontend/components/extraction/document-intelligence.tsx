"use client";

import * as React from "react";
import { useState, useCallback } from "react";
import {
  Brain,
  FileSearch,
  Sparkles,
  Table2,
  FormInput,
  Layers,
  ChevronDown,
  ChevronUp,
  CheckCircle2,
  AlertCircle,
  Loader2,
  FileText,
  Globe,
  Lightbulb,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
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
import { cn } from "@/lib/utils";
import {
  api,
  type DocumentTypeResult,
  type StructureAnalysisResult,
  type SchemaInferenceResult,
} from "@/lib/api";

interface DocumentIntelligenceProps {
  file: File | null;
  ocrProvider?: string;
  llmProvider?: string;
  onTypeDetected?: (result: DocumentTypeResult) => void;
  onStructureAnalyzed?: (result: StructureAnalysisResult) => void;
  onSchemaInferred?: (result: SchemaInferenceResult) => void;
  className?: string;
}

type AnalysisStep = "idle" | "detecting" | "analyzing" | "inferring" | "complete" | "error";

export function DocumentIntelligence({
  file,
  ocrProvider,  // No default - uses user settings from backend
  llmProvider,  // No default - uses user settings from backend
  onTypeDetected,
  onStructureAnalyzed,
  onSchemaInferred,
  className,
}: DocumentIntelligenceProps) {
  const [step, setStep] = useState<AnalysisStep>("idle");
  const [error, setError] = useState<string | null>(null);

  const [typeResult, setTypeResult] = useState<DocumentTypeResult | null>(null);
  const [structureResult, setStructureResult] = useState<StructureAnalysisResult | null>(null);
  const [schemaResult, setSchemaResult] = useState<SchemaInferenceResult | null>(null);

  const [expandedSections, setExpandedSections] = useState({
    type: true,
    structure: false,
    schema: false,
  });

  const runAnalysis = useCallback(async () => {
    if (!file) return;

    setError(null);
    setTypeResult(null);
    setStructureResult(null);
    setSchemaResult(null);

    try {
      // Step 1: Detect document type
      setStep("detecting");
      const typeRes = await api.detectDocumentType(file, ocrProvider);
      setTypeResult(typeRes);
      onTypeDetected?.(typeRes);
      setExpandedSections((prev) => ({ ...prev, type: true }));

      // Step 2: Analyze structure
      setStep("analyzing");
      const structRes = await api.analyzeStructure(file, ocrProvider);
      setStructureResult(structRes);
      onStructureAnalyzed?.(structRes);
      setExpandedSections((prev) => ({ ...prev, structure: true }));

      // Step 3: Infer schema (optional, can be slow)
      setStep("inferring");
      const schemaRes = await api.inferSchema(file, ocrProvider, llmProvider);
      setSchemaResult(schemaRes);
      onSchemaInferred?.(schemaRes);
      setExpandedSections((prev) => ({ ...prev, schema: true }));

      setStep("complete");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
      setStep("error");
    }
  }, [file, ocrProvider, llmProvider, onTypeDetected, onStructureAnalyzed, onSchemaInferred]);

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.8) return "text-green-600 dark:text-green-400";
    if (confidence >= 0.6) return "text-yellow-600 dark:text-yellow-400";
    return "text-red-600 dark:text-red-400";
  };

  const getConfidenceBadge = (confidence: number) => {
    if (confidence >= 0.8) return "default";
    if (confidence >= 0.6) return "secondary";
    return "destructive";
  };

  const formatDocType = (type: string) => {
    return type
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Brain className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">Document Intelligence</CardTitle>
          </div>
          <Button
            onClick={runAnalysis}
            disabled={!file || step === "detecting" || step === "analyzing" || step === "inferring"}
            size="sm"
          >
            {step === "detecting" || step === "analyzing" || step === "inferring" ? (
              <>
                <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                Analyzing...
              </>
            ) : (
              <>
                <Sparkles className="mr-2 h-4 w-4" />
                Analyze Document
              </>
            )}
          </Button>
        </div>
        <CardDescription>
          Auto-detect document type, analyze structure, and infer extraction schema
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-4">
        {/* Progress indicator */}
        {step !== "idle" && step !== "complete" && step !== "error" && (
          <div className="space-y-2">
            <div className="flex items-center justify-between text-sm">
              <span className="text-muted-foreground">
                {step === "detecting" && "Detecting document type..."}
                {step === "analyzing" && "Analyzing structure..."}
                {step === "inferring" && "Inferring schema..."}
              </span>
              <span className="text-muted-foreground">
                {step === "detecting" && "1/3"}
                {step === "analyzing" && "2/3"}
                {step === "inferring" && "3/3"}
              </span>
            </div>
            <Progress
              value={
                step === "detecting"
                  ? 33
                  : step === "analyzing"
                    ? 66
                    : step === "inferring"
                      ? 90
                      : 100
              }
            />
          </div>
        )}

        {/* Error display */}
        {error && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 text-destructive">
            <AlertCircle className="h-4 w-4" />
            <span className="text-sm">{error}</span>
          </div>
        )}

        {/* Document Type Result */}
        {typeResult && (
          <Collapsible
            open={expandedSections.type}
            onOpenChange={(open) =>
              setExpandedSections((prev) => ({ ...prev, type: open }))
            }
          >
            <CollapsibleTrigger className="flex items-center justify-between w-full p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
              <div className="flex items-center gap-2">
                <FileSearch className="h-4 w-4 text-primary" />
                <span className="font-medium">Document Type</span>
                <Badge variant={getConfidenceBadge(typeResult.confidence)}>
                  {Math.round(typeResult.confidence * 100)}% confident
                </Badge>
              </div>
              {expandedSections.type ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3 px-3">
              <div className="space-y-3">
                <div className="flex items-center gap-3">
                  <FileText className="h-8 w-8 text-primary" />
                  <div>
                    <div className="text-lg font-semibold">
                      {formatDocType(typeResult.primary_type)}
                    </div>
                    <div className="flex items-center gap-2 text-sm text-muted-foreground">
                      <Globe className="h-3 w-3" />
                      Language: {typeResult.language.toUpperCase()}
                    </div>
                  </div>
                </div>

                {typeResult.alternative_types.length > 0 && (
                  <div>
                    <div className="text-sm font-medium mb-2">Alternative Types:</div>
                    <div className="flex flex-wrap gap-2">
                      {typeResult.alternative_types.map((alt, idx) => (
                        <Badge key={idx} variant="outline">
                          {formatDocType(alt.type)} ({Math.round(alt.confidence * 100)}%)
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}

                {typeResult.signals.length > 0 && (
                  <div>
                    <div className="text-sm font-medium mb-2">Detection Signals:</div>
                    <div className="flex flex-wrap gap-1">
                      {typeResult.signals.slice(0, 8).map((signal, idx) => (
                        <Badge key={idx} variant="secondary" className="text-xs">
                          {signal}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Structure Analysis Result */}
        {structureResult && (
          <Collapsible
            open={expandedSections.structure}
            onOpenChange={(open) =>
              setExpandedSections((prev) => ({ ...prev, structure: open }))
            }
          >
            <CollapsibleTrigger className="flex items-center justify-between w-full p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
              <div className="flex items-center gap-2">
                <Layers className="h-4 w-4 text-primary" />
                <span className="font-medium">Document Structure</span>
                <Badge variant="secondary">
                  {structureResult.total_pages} pages
                </Badge>
                <Badge variant="outline">{structureResult.layout_type}</Badge>
              </div>
              {expandedSections.structure ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3 px-3">
              <div className="space-y-4">
                {/* Suggested Parts */}
                {structureResult.suggested_parts.length > 0 && (
                  <div>
                    <div className="text-sm font-medium mb-2">
                      Suggested Extraction Parts:
                    </div>
                    <div className="grid gap-2">
                      {structureResult.suggested_parts.map((part, idx) => (
                        <div
                          key={idx}
                          className="flex items-center justify-between p-2 rounded border bg-card"
                        >
                          <div className="flex items-center gap-2">
                            <Badge variant="outline" className="font-mono">
                              {part.name}
                            </Badge>
                            <span className="text-sm font-medium">{part.label}</span>
                          </div>
                          <span className="text-xs text-muted-foreground">
                            Pages {part.page_range[0]}-{part.page_range[1]}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Tables */}
                {structureResult.tables.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 text-sm font-medium mb-2">
                      <Table2 className="h-4 w-4" />
                      Tables Detected: {structureResult.tables.length}
                    </div>
                    <div className="grid gap-2">
                      {structureResult.tables.map((table, idx) => (
                        <div
                          key={idx}
                          className="p-2 rounded border bg-card text-sm"
                        >
                          <div className="flex items-center justify-between mb-1">
                            <span className="font-medium">
                              Page {table.page}
                            </span>
                            <span className="text-muted-foreground">
                              {table.row_count} rows
                            </span>
                          </div>
                          <div className="flex flex-wrap gap-1">
                            {table.columns.map((col, colIdx) => (
                              <Badge key={colIdx} variant="secondary" className="text-xs">
                                {col}
                              </Badge>
                            ))}
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>
                )}

                {/* Form Fields */}
                {structureResult.form_fields.length > 0 && (
                  <div>
                    <div className="flex items-center gap-2 text-sm font-medium mb-2">
                      <FormInput className="h-4 w-4" />
                      Form Fields: {structureResult.form_fields.length}
                    </div>
                    <div className="flex flex-wrap gap-2">
                      {structureResult.form_fields.slice(0, 10).map((field, idx) => (
                        <TooltipProvider key={idx}>
                          <Tooltip>
                            <TooltipTrigger>
                              <Badge
                                variant={field.required ? "default" : "outline"}
                                className="text-xs"
                              >
                                {field.label}
                              </Badge>
                            </TooltipTrigger>
                            <TooltipContent>
                              <p>
                                Type: {field.type} | Page: {field.page}
                                {field.required && " | Required"}
                              </p>
                            </TooltipContent>
                          </Tooltip>
                        </TooltipProvider>
                      ))}
                      {structureResult.form_fields.length > 10 && (
                        <Badge variant="outline" className="text-xs">
                          +{structureResult.form_fields.length - 10} more
                        </Badge>
                      )}
                    </div>
                  </div>
                )}

                {/* Sections */}
                {structureResult.detected_sections.length > 0 && (
                  <div>
                    <div className="text-sm font-medium mb-2">
                      Detected Sections:
                    </div>
                    <div className="space-y-1">
                      {structureResult.detected_sections.slice(0, 5).map((section, idx) => (
                        <div
                          key={idx}
                          className="flex items-center gap-2 text-sm"
                          style={{ paddingLeft: `${(section.level - 1) * 12}px` }}
                        >
                          <ChevronDown className="h-3 w-3 text-muted-foreground" />
                          <span className="font-medium">{section.title}</span>
                          <span className="text-xs text-muted-foreground">
                            (p.{section.start_page}-{section.end_page})
                          </span>
                        </div>
                      ))}
                      {structureResult.detected_sections.length > 5 && (
                        <div className="text-xs text-muted-foreground pl-4">
                          +{structureResult.detected_sections.length - 5} more sections
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Schema Inference Result */}
        {schemaResult && (
          <Collapsible
            open={expandedSections.schema}
            onOpenChange={(open) =>
              setExpandedSections((prev) => ({ ...prev, schema: open }))
            }
          >
            <CollapsibleTrigger className="flex items-center justify-between w-full p-3 rounded-lg bg-muted/50 hover:bg-muted transition-colors">
              <div className="flex items-center gap-2">
                <Lightbulb className="h-4 w-4 text-primary" />
                <span className="font-medium">Inferred Schema</span>
                <Badge variant={getConfidenceBadge(schemaResult.confidence)}>
                  {Math.round(schemaResult.confidence * 100)}% confident
                </Badge>
              </div>
              {expandedSections.schema ? (
                <ChevronUp className="h-4 w-4" />
              ) : (
                <ChevronDown className="h-4 w-4" />
              )}
            </CollapsibleTrigger>
            <CollapsibleContent className="pt-3 px-3">
              <div className="space-y-4">
                <div>
                  <div className="font-medium">{schemaResult.schema_name}</div>
                  <div className="text-sm text-muted-foreground">
                    {schemaResult.fields.length} fields detected
                  </div>
                </div>

                {/* Fields */}
                <div>
                  <div className="text-sm font-medium mb-2">Detected Fields:</div>
                  <div className="grid gap-2 max-h-64 overflow-y-auto">
                    {schemaResult.fields.map((field, idx) => (
                      <div
                        key={idx}
                        className="flex items-center justify-between p-2 rounded border bg-card"
                      >
                        <div className="flex items-center gap-2">
                          <Badge variant="outline" className="font-mono text-xs">
                            {field.type}
                          </Badge>
                          <div>
                            <div className="text-sm font-medium">
                              {field.display_name}
                            </div>
                            {field.description && (
                              <div className="text-xs text-muted-foreground">
                                {field.description}
                              </div>
                            )}
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          {field.required && (
                            <Badge variant="destructive" className="text-xs">
                              Required
                            </Badge>
                          )}
                          <span
                            className={cn(
                              "text-xs",
                              getConfidenceColor(field.confidence)
                            )}
                          >
                            {Math.round(field.confidence * 100)}%
                          </span>
                        </div>
                      </div>
                    ))}
                  </div>
                </div>

                {/* Suggestions */}
                {schemaResult.suggestions.length > 0 && (
                  <div>
                    <div className="text-sm font-medium mb-2">Suggestions:</div>
                    <ul className="list-disc list-inside text-sm text-muted-foreground space-y-1">
                      {schemaResult.suggestions.map((suggestion, idx) => (
                        <li key={idx}>{suggestion}</li>
                      ))}
                    </ul>
                  </div>
                )}
              </div>
            </CollapsibleContent>
          </Collapsible>
        )}

        {/* Idle state prompt */}
        {step === "idle" && !typeResult && (
          <div className="text-center py-6 text-muted-foreground">
            <Brain className="h-12 w-12 mx-auto mb-3 opacity-50" />
            <p className="text-sm">
              {file
                ? "Click 'Analyze Document' to auto-detect type, structure, and schema"
                : "Upload a document to begin intelligent analysis"}
            </p>
          </div>
        )}

        {/* Complete state */}
        {step === "complete" && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-green-500/10 text-green-600 dark:text-green-400">
            <CheckCircle2 className="h-4 w-4" />
            <span className="text-sm">Analysis complete! Review the results above.</span>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
