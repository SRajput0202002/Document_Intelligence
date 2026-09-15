"use client";

import { Settings2, Cloud, Loader2 } from "lucide-react";
import { CpuIcon } from "@/components/ui/cpu";
import { PlayIcon } from "@/components/ui/play";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import {
  useProviders,
  getCostTierLabel,
  getCostTierColor,
  getProviderTypeColor,
} from "@/hooks/use-providers";
import { cn } from "@/lib/utils";

interface ProviderSelectorProps {
  docType: "bill_of_entry" | "shipping_bill";
  onDocTypeChange: (type: "bill_of_entry" | "shipping_bill") => void;
  ocrProvider: string;
  onOcrProviderChange: (provider: string) => void;
  llmProvider: string;
  onLlmProviderChange: (provider: string) => void;
  onExtract: () => void;
  isExtracting: boolean;
  hasFile: boolean;
}

export function ProviderSelector({
  docType,
  onDocTypeChange,
  ocrProvider,
  onOcrProviderChange,
  llmProvider,
  onLlmProviderChange,
  onExtract,
  isExtracting,
  hasFile,
}: ProviderSelectorProps) {
  const { data: providers, isLoading } = useProviders();

  const ocrProviders = providers?.ocr_providers ?? [];
  const llmProviders = providers?.llm_providers ?? [];

  const selectedOcr = ocrProviders.find((p) => p.name === ocrProvider);
  const selectedLlm = llmProviders.find((p) => p.name === llmProvider);

  return (
    <Card className="flex flex-col">
      <CardHeader className="flex-none py-3 px-4">
        <CardTitle className="text-lg flex items-center gap-2">
          <Settings2 className="h-5 w-5" />
          Configuration
        </CardTitle>
      </CardHeader>
      <CardContent className="flex-1 p-4 pt-0 space-y-4">
        {/* Document Type */}
        <div className="space-y-2">
          <Label>Document Type</Label>
          <div className="grid grid-cols-2 gap-2">
            <Button
              variant={docType === "bill_of_entry" ? "default" : "outline"}
              className="w-full"
              onClick={() => onDocTypeChange("bill_of_entry")}
              disabled={isExtracting}
            >
              Bill of Entry
            </Button>
            <Button
              variant={docType === "shipping_bill" ? "default" : "outline"}
              className="w-full"
              onClick={() => onDocTypeChange("shipping_bill")}
              disabled={isExtracting}
            >
              Shipping Bill
            </Button>
          </div>
        </div>

        <Separator />

        {/* OCR Provider */}
        <div className="space-y-2">
          <Label className="flex items-center gap-2">
            OCR Provider
            {selectedOcr && (
              <Badge
                variant="outline"
                className={cn("text-xs", getCostTierColor(selectedOcr.cost_tier))}
              >
                {getCostTierLabel(selectedOcr.cost_tier)}
              </Badge>
            )}
          </Label>
          <Select
            value={ocrProvider}
            onValueChange={onOcrProviderChange}
            disabled={isExtracting || isLoading}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select OCR provider" />
            </SelectTrigger>
            <SelectContent>
              {ocrProviders.map((provider) => (
                <SelectItem
                  key={provider.name}
                  value={provider.name}
                  disabled={!provider.is_available}
                >
                  <div className="flex items-center gap-2">
                    {provider.provider_type === "local" ? (
                      <CpuIcon size={16} />
                    ) : (
                      <Cloud className="h-4 w-4" />
                    )}
                    <span>{provider.display_name}</span>
                    <Badge
                      variant="outline"
                      className={cn("text-xs ml-auto", getCostTierColor(provider.cost_tier))}
                    >
                      {getCostTierLabel(provider.cost_tier)}
                    </Badge>
                    {!provider.is_available && (
                      <Badge variant="destructive" className="text-xs">
                        Unavailable
                      </Badge>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedOcr && (
            <p className="text-xs text-muted-foreground">{selectedOcr.description}</p>
          )}
        </div>

        {/* LLM Provider */}
        <div className="space-y-2">
          <Label className="flex items-center gap-2">
            LLM Extractor
            {selectedLlm && (
              <Badge
                variant="outline"
                className={cn("text-xs", getCostTierColor(selectedLlm.cost_tier))}
              >
                {getCostTierLabel(selectedLlm.cost_tier)}
              </Badge>
            )}
          </Label>
          <Select
            value={llmProvider}
            onValueChange={onLlmProviderChange}
            disabled={isExtracting || isLoading}
          >
            <SelectTrigger>
              <SelectValue placeholder="Select LLM extractor" />
            </SelectTrigger>
            <SelectContent>
              {llmProviders.map((provider) => (
                <SelectItem
                  key={provider.name}
                  value={provider.name}
                  disabled={!provider.is_available}
                >
                  <div className="flex items-center gap-2">
                    {provider.provider_type === "local" ? (
                      <CpuIcon size={16} />
                    ) : (
                      <Cloud className="h-4 w-4" />
                    )}
                    <span>{provider.display_name}</span>
                    <Badge
                      variant="outline"
                      className={cn("text-xs ml-auto", getCostTierColor(provider.cost_tier))}
                    >
                      {getCostTierLabel(provider.cost_tier)}
                    </Badge>
                    {!provider.is_available && (
                      <Badge variant="destructive" className="text-xs">
                        Unavailable
                      </Badge>
                    )}
                  </div>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {selectedLlm && (
            <p className="text-xs text-muted-foreground">{selectedLlm.description}</p>
          )}
        </div>

        <Separator />

        {/* Extract Button */}
        <Button
          className="w-full"
          size="lg"
          onClick={onExtract}
          disabled={!hasFile || isExtracting}
        >
          {isExtracting ? (
            <>
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              Extracting...
            </>
          ) : (
            <>
              <PlayIcon size={16} className="mr-2" />
              Start Extraction
            </>
          )}
        </Button>

        {!hasFile && (
          <p className="text-xs text-muted-foreground text-center">
            Upload a PDF document to start extraction
          </p>
        )}
      </CardContent>
    </Card>
  );
}
