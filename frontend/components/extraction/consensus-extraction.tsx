"use client";

import * as React from "react";
import { useState, useCallback } from "react";
import {
  Users,
  CheckCircle2,
  AlertTriangle,
  XCircle,
  Clock,
  Loader2,
  ChevronDown,
  ChevronUp,
  Shield,
  Eye,
  Sparkles,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Checkbox } from "@/components/ui/checkbox";
import { Slider } from "@/components/ui/slider";
import { Label } from "@/components/ui/label";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { cn } from "@/lib/utils";
import { api, type ConsensusResult, type Provider } from "@/lib/api";

interface ConsensusExtractionProps {
  file: File | null;
  availableOcrProviders: Provider[];
  availableLlmProviders: Provider[];
  schemaId?: string;
  onComplete?: (result: ConsensusResult) => void;
  className?: string;
}

export function ConsensusExtraction({
  file,
  availableOcrProviders,
  availableLlmProviders,
  schemaId,
  onComplete,
  className,
}: ConsensusExtractionProps) {
  const [isRunning, setIsRunning] = useState(false);
  const [result, setResult] = useState<ConsensusResult | null>(null);
  const [error, setError] = useState<string | null>(null);

  // Provider selection
  const [selectedOcr, setSelectedOcr] = useState<string[]>(
    availableOcrProviders
      .filter((p) => p.is_available)
      .slice(0, 2)
      .map((p) => p.name)
  );
  const [selectedLlm, setSelectedLlm] = useState<string[]>(
    availableLlmProviders
      .filter((p) => p.is_available)
      .slice(0, 2)
      .map((p) => p.name)
  );

  const [consensusThreshold, setConsensusThreshold] = useState(0.6);
  const [showAdvanced, setShowAdvanced] = useState(false);

  const runConsensus = useCallback(async () => {
    if (!file || selectedOcr.length === 0 || selectedLlm.length === 0) return;

    setIsRunning(true);
    setError(null);
    setResult(null);

    try {
      const res = await api.extractWithConsensus(
        file,
        selectedOcr,
        selectedLlm,
        schemaId,
        consensusThreshold
      );
      setResult(res);
      onComplete?.(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Consensus extraction failed");
    } finally {
      setIsRunning(false);
    }
  }, [file, selectedOcr, selectedLlm, schemaId, consensusThreshold, onComplete]);

  const toggleOcrProvider = (name: string) => {
    setSelectedOcr((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name]
    );
  };

  const toggleLlmProvider = (name: string) => {
    setSelectedLlm((prev) =>
      prev.includes(name) ? prev.filter((p) => p !== name) : [...prev, name]
    );
  };

  const totalCombinations = selectedOcr.length * selectedLlm.length;

  return (
    <Card className={cn("w-full", className)}>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Shield className="h-5 w-5 text-primary" />
            <CardTitle className="text-lg">Consensus Extraction</CardTitle>
          </div>
          <Badge variant="outline" className="font-mono">
            {totalCombinations} combinations
          </Badge>
        </div>
        <CardDescription>
          Run extraction with multiple providers for higher accuracy through cross-validation
        </CardDescription>
      </CardHeader>

      <CardContent className="space-y-6">
        {/* Provider Selection */}
        <div className="grid md:grid-cols-2 gap-4">
          {/* OCR Providers */}
          <div>
            <Label className="text-sm font-medium mb-2 block">OCR Providers</Label>
            <div className="space-y-2 p-3 rounded-lg border bg-muted/30">
              {availableOcrProviders.map((provider) => (
                <label
                  key={provider.name}
                  className={cn(
                    "flex items-center gap-3 p-2 rounded cursor-pointer transition-colors",
                    provider.is_available
                      ? "hover:bg-muted"
                      : "opacity-50 cursor-not-allowed"
                  )}
                >
                  <Checkbox
                    checked={selectedOcr.includes(provider.name)}
                    onCheckedChange={() => toggleOcrProvider(provider.name)}
                    disabled={!provider.is_available}
                  />
                  <div className="flex-1">
                    <div className="font-medium text-sm">{provider.display_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {provider.provider_type} | {provider.cost_tier}
                    </div>
                  </div>
                  {!provider.is_available && (
                    <Badge variant="outline" className="text-xs">
                      Unavailable
                    </Badge>
                  )}
                </label>
              ))}
            </div>
          </div>

          {/* LLM Providers */}
          <div>
            <Label className="text-sm font-medium mb-2 block">LLM Providers</Label>
            <div className="space-y-2 p-3 rounded-lg border bg-muted/30">
              {availableLlmProviders.map((provider) => (
                <label
                  key={provider.name}
                  className={cn(
                    "flex items-center gap-3 p-2 rounded cursor-pointer transition-colors",
                    provider.is_available
                      ? "hover:bg-muted"
                      : "opacity-50 cursor-not-allowed"
                  )}
                >
                  <Checkbox
                    checked={selectedLlm.includes(provider.name)}
                    onCheckedChange={() => toggleLlmProvider(provider.name)}
                    disabled={!provider.is_available}
                  />
                  <div className="flex-1">
                    <div className="font-medium text-sm">{provider.display_name}</div>
                    <div className="text-xs text-muted-foreground">
                      {provider.provider_type} | {provider.cost_tier}
                    </div>
                  </div>
                  {!provider.is_available && (
                    <Badge variant="outline" className="text-xs">
                      Unavailable
                    </Badge>
                  )}
                </label>
              ))}
            </div>
          </div>
        </div>

        {/* Advanced Options */}
        <Collapsible open={showAdvanced} onOpenChange={setShowAdvanced}>
          <CollapsibleTrigger className="flex items-center gap-2 text-sm text-muted-foreground hover:text-foreground transition-colors">
            {showAdvanced ? (
              <ChevronUp className="h-4 w-4" />
            ) : (
              <ChevronDown className="h-4 w-4" />
            )}
            Advanced Options
          </CollapsibleTrigger>
          <CollapsibleContent className="pt-4">
            <div className="space-y-4 p-4 rounded-lg border bg-muted/30">
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <Label className="text-sm">Consensus Threshold</Label>
                  <span className="text-sm font-mono">
                    {Math.round(consensusThreshold * 100)}%
                  </span>
                </div>
                <Slider
                  value={[consensusThreshold]}
                  onValueChange={([v]) => setConsensusThreshold(v)}
                  min={0.4}
                  max={0.9}
                  step={0.1}
                />
                <p className="text-xs text-muted-foreground">
                  Minimum agreement ratio required for consensus. Higher = stricter.
                </p>
              </div>
            </div>
          </CollapsibleContent>
        </Collapsible>

        {/* Run Button */}
        <Button
          onClick={runConsensus}
          disabled={
            !file ||
            isRunning ||
            selectedOcr.length === 0 ||
            selectedLlm.length === 0
          }
          className="w-full"
          size="lg"
        >
          {isRunning ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Running {totalCombinations} provider combinations...
            </>
          ) : (
            <>
              <Sparkles className="mr-2 h-4 w-4" />
              Run Consensus Extraction
            </>
          )}
        </Button>

        {/* Error */}
        {error && (
          <div className="flex items-center gap-2 p-3 rounded-lg bg-destructive/10 text-destructive">
            <XCircle className="h-4 w-4" />
            <span className="text-sm">{error}</span>
          </div>
        )}

        {/* Results */}
        {result && (
          <div className="space-y-4">
            {/* Summary */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="p-3 rounded-lg border bg-card text-center">
                <div className="text-2xl font-bold">
                  {Math.round(result.overall_confidence * 100)}%
                </div>
                <div className="text-xs text-muted-foreground">Confidence</div>
              </div>
              <div className="p-3 rounded-lg border bg-card text-center">
                <div className="text-2xl font-bold">
                  {Math.round(result.overall_agreement * 100)}%
                </div>
                <div className="text-xs text-muted-foreground">Agreement</div>
              </div>
              <div className="p-3 rounded-lg border bg-card text-center">
                <div className="text-2xl font-bold">{result.conflicts.length}</div>
                <div className="text-xs text-muted-foreground">Conflicts</div>
              </div>
              <div className="p-3 rounded-lg border bg-card text-center">
                <div className="text-2xl font-bold">
                  {result.processing_time.toFixed(1)}s
                </div>
                <div className="text-xs text-muted-foreground">Time</div>
              </div>
            </div>

            {/* Status Badges */}
            <div className="flex flex-wrap gap-2">
              {result.success ? (
                <Badge className="bg-green-500/10 text-green-600 dark:text-green-400">
                  <CheckCircle2 className="mr-1 h-3 w-3" />
                  Extraction Successful
                </Badge>
              ) : (
                <Badge variant="destructive">
                  <XCircle className="mr-1 h-3 w-3" />
                  Extraction Failed
                </Badge>
              )}
              {result.providers_used.map((provider) => (
                <Badge key={provider} variant="outline" className="text-xs">
                  {provider}
                </Badge>
              ))}
            </div>

            {/* Conflicts & Review Items */}
            {(result.conflicts.length > 0 || result.needs_review.length > 0) && (
              <Accordion type="multiple" className="w-full">
                {result.conflicts.length > 0 && (
                  <AccordionItem value="conflicts">
                    <AccordionTrigger className="hover:no-underline">
                      <div className="flex items-center gap-2">
                        <AlertTriangle className="h-4 w-4 text-yellow-500" />
                        <span>Conflicts ({result.conflicts.length})</span>
                      </div>
                    </AccordionTrigger>
                    <AccordionContent>
                      <div className="space-y-2">
                        {result.conflicts.map((field, idx) => (
                          <div
                            key={idx}
                            className="flex items-center gap-2 p-2 rounded bg-yellow-500/10"
                          >
                            <AlertTriangle className="h-4 w-4 text-yellow-500" />
                            <code className="text-sm">{field}</code>
                          </div>
                        ))}
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                )}

                {result.needs_review.length > 0 && (
                  <AccordionItem value="review">
                    <AccordionTrigger className="hover:no-underline">
                      <div className="flex items-center gap-2">
                        <Eye className="h-4 w-4 text-blue-500" />
                        <span>Needs Review ({result.needs_review.length})</span>
                      </div>
                    </AccordionTrigger>
                    <AccordionContent>
                      <div className="space-y-2">
                        {result.needs_review.map((field, idx) => (
                          <div
                            key={idx}
                            className="flex items-center gap-2 p-2 rounded bg-blue-500/10"
                          >
                            <Eye className="h-4 w-4 text-blue-500" />
                            <code className="text-sm">{field}</code>
                          </div>
                        ))}
                      </div>
                    </AccordionContent>
                  </AccordionItem>
                )}
              </Accordion>
            )}

            {/* Extracted Data Preview */}
            {result.data && Object.keys(result.data).length > 0 && (
              <div>
                <div className="text-sm font-medium mb-2">Extracted Data Preview:</div>
                <div className="p-3 rounded-lg border bg-muted/30 max-h-64 overflow-auto">
                  <pre className="text-xs font-mono">
                    {JSON.stringify(result.data, null, 2)}
                  </pre>
                </div>
              </div>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
