"use client";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  HelpCircle,
  Layers,
  Scissors,
  Sparkles,
  Zap,
} from "lucide-react";
import { useState } from "react";

export interface SegmentationConfigValues {
  mode: "homogeneous" | "heterogeneous";
  expectedTypes: string[];
  enableLlmFallback: boolean;
  confidenceThreshold: number;
  minPagesPerSegment: number;
  maxSegments: number;
}

interface SegmentationConfigProps {
  initialConfig?: Partial<SegmentationConfigValues>;
  onConfigChange?: (config: SegmentationConfigValues) => void;
  onAnalyze?: (config: SegmentationConfigValues) => void;
  isAnalyzing?: boolean;
  availableDocTypes?: string[];
}

const DEFAULT_CONFIG: SegmentationConfigValues = {
  mode: "homogeneous",
  expectedTypes: [],
  enableLlmFallback: false,
  confidenceThreshold: 0.6,
  minPagesPerSegment: 1,
  maxSegments: 50,
};

export function SegmentationConfig({
  initialConfig,
  onConfigChange,
  onAnalyze,
  isAnalyzing = false,
  availableDocTypes = [
    "invoice",
    "receipt",
    "contract",
    "resume",
    "certificate",
    "bill_of_entry",
    "shipping_bill",
    "purchase_order",
    "bank_statement",
  ],
}: SegmentationConfigProps) {
  const [config, setConfig] = useState<SegmentationConfigValues>({
    ...DEFAULT_CONFIG,
    ...initialConfig,
  });
  const [typeInput, setTypeInput] = useState("");

  const updateConfig = (updates: Partial<SegmentationConfigValues>) => {
    const newConfig = { ...config, ...updates };
    setConfig(newConfig);
    onConfigChange?.(newConfig);
  };

  const addExpectedType = (type: string) => {
    if (type && !config.expectedTypes.includes(type)) {
      updateConfig({
        expectedTypes: [...config.expectedTypes, type],
      });
    }
    setTypeInput("");
  };

  const removeExpectedType = (type: string) => {
    updateConfig({
      expectedTypes: config.expectedTypes.filter((t) => t !== type),
    });
  };

  return (
    <Card className="w-full">
      <CardHeader className="pb-3">
        <CardTitle className="text-sm font-medium flex items-center gap-2">
          <Scissors className="h-4 w-4" />
          Segmentation Settings
        </CardTitle>
        <CardDescription className="text-xs">
          Configure how multi-document PDFs are split into individual documents
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        {/* Mode selection */}
        <div className="space-y-3">
          <Label className="text-xs font-medium">Segmentation Mode</Label>
          <div className="grid grid-cols-2 gap-3">
            <button
              type="button"
              onClick={() => updateConfig({ mode: "homogeneous" })}
              className={`p-3 rounded-md border text-left transition-all ${
                config.mode === "homogeneous"
                  ? "border-primary bg-primary/5"
                  : "border-muted hover:border-muted-foreground/50"
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <Layers className="h-4 w-4" />
                <span className="font-medium text-sm">Homogeneous</span>
              </div>
              <p className="text-xs text-muted-foreground">
                All segments are the same document type (e.g., 5 invoices)
              </p>
            </button>
            <button
              type="button"
              onClick={() => updateConfig({ mode: "heterogeneous" })}
              className={`p-3 rounded-md border text-left transition-all ${
                config.mode === "heterogeneous"
                  ? "border-primary bg-primary/5"
                  : "border-muted hover:border-muted-foreground/50"
              }`}
            >
              <div className="flex items-center gap-2 mb-1">
                <Zap className="h-4 w-4" />
                <span className="font-medium text-sm">Heterogeneous</span>
              </div>
              <p className="text-xs text-muted-foreground">
                Mixed document types (e.g., invoice + resume + certificate)
              </p>
            </button>
          </div>
        </div>

        {/* Expected document types */}
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <Label className="text-xs font-medium">Expected Document Types</Label>
            <TooltipProvider>
              <Tooltip>
                <TooltipTrigger>
                  <HelpCircle className="h-3 w-3 text-muted-foreground" />
                </TooltipTrigger>
                <TooltipContent side="right" className="max-w-[200px]">
                  <p className="text-xs">
                    Specify expected document types to improve detection accuracy
                  </p>
                </TooltipContent>
              </Tooltip>
            </TooltipProvider>
          </div>

          <div className="flex flex-wrap gap-2">
            {config.expectedTypes.map((type) => (
              <Badge
                key={type}
                variant="secondary"
                className="text-xs cursor-pointer hover:bg-destructive/20"
                onClick={() => removeExpectedType(type)}
              >
                {type}
                <span className="ml-1 opacity-70">x</span>
              </Badge>
            ))}
          </div>

          <div className="flex gap-2">
            <Select value="" onValueChange={addExpectedType}>
              <SelectTrigger className="flex-1 h-8 text-xs">
                <SelectValue placeholder="Add document type..." />
              </SelectTrigger>
              <SelectContent>
                {availableDocTypes
                  .filter((t) => !config.expectedTypes.includes(t))
                  .map((type) => (
                    <SelectItem key={type} value={type} className="text-xs">
                      {type.replace(/_/g, " ")}
                    </SelectItem>
                  ))}
              </SelectContent>
            </Select>
            <Input
              value={typeInput}
              onChange={(e) => setTypeInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter") {
                  addExpectedType(typeInput);
                }
              }}
              placeholder="Custom type..."
              className="flex-1 h-8 text-xs"
            />
          </div>
        </div>

        {/* Confidence threshold */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <Label className="text-xs font-medium">Confidence Threshold</Label>
              <TooltipProvider>
                <Tooltip>
                  <TooltipTrigger>
                    <HelpCircle className="h-3 w-3 text-muted-foreground" />
                  </TooltipTrigger>
                  <TooltipContent side="right" className="max-w-[200px]">
                    <p className="text-xs">
                      Minimum confidence required for boundary detection.
                      Lower = more segments, higher = fewer false positives.
                    </p>
                  </TooltipContent>
                </Tooltip>
              </TooltipProvider>
            </div>
            <span className="text-xs text-muted-foreground">
              {Math.round(config.confidenceThreshold * 100)}%
            </span>
          </div>
          <Slider
            value={[config.confidenceThreshold]}
            onValueChange={([value]) =>
              updateConfig({ confidenceThreshold: value })
            }
            min={0.3}
            max={0.95}
            step={0.05}
            className="w-full"
          />
        </div>

        {/* LLM fallback toggle */}
        <div className="flex items-center justify-between">
          <div className="space-y-1">
            <div className="flex items-center gap-2">
              <Label className="text-xs font-medium">LLM Fallback</Label>
              {!config.enableLlmFallback && (
                <Badge variant="outline" className="text-[10px] bg-green-500/10 text-green-600">
                  <Sparkles className="h-2 w-2 mr-1" />
                  Free
                </Badge>
              )}
            </div>
            <p className="text-xs text-muted-foreground">
              Use LLM when heuristics are uncertain (~$0.001/doc)
            </p>
          </div>
          <Switch
            checked={config.enableLlmFallback}
            onCheckedChange={(checked) =>
              updateConfig({ enableLlmFallback: checked })
            }
          />
        </div>

        {/* Advanced settings collapsed by default */}
        <details className="group">
          <summary className="text-xs font-medium cursor-pointer text-muted-foreground hover:text-foreground">
            Advanced Settings
          </summary>
          <div className="mt-3 space-y-4 pl-2 border-l-2">
            <div className="space-y-2">
              <Label className="text-xs">Min pages per segment</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={config.minPagesPerSegment}
                onChange={(e) =>
                  updateConfig({
                    minPagesPerSegment: parseInt(e.target.value) || 1,
                  })
                }
                className="h-8 text-xs"
              />
            </div>
            <div className="space-y-2">
              <Label className="text-xs">Max segments</Label>
              <Input
                type="number"
                min={1}
                max={100}
                value={config.maxSegments}
                onChange={(e) =>
                  updateConfig({
                    maxSegments: parseInt(e.target.value) || 50,
                  })
                }
                className="h-8 text-xs"
              />
            </div>
          </div>
        </details>

        {/* Analyze button */}
        {onAnalyze && (
          <Button
            onClick={() => onAnalyze(config)}
            disabled={isAnalyzing}
            className="w-full"
          >
            {isAnalyzing ? (
              <>
                <Scissors className="h-4 w-4 mr-2 animate-spin" />
                Analyzing segments...
              </>
            ) : (
              <>
                <Scissors className="h-4 w-4 mr-2" />
                Analyze Segments
              </>
            )}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}
