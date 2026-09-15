"use client";

import { useState, useEffect } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { api, Job, WorkflowResponseMode } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Accordion,
  AccordionContent,
  AccordionItem,
  AccordionTrigger,
} from "@/components/ui/accordion";
import { toast } from "@/components/ui/toast";
import { cn } from "@/lib/utils";
import { Zap, Loader2, CheckCircle2, Copy, ExternalLink } from "lucide-react";

interface SaveAsWorkflowModalProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  job: Job;
}

function jobIsSegmented(j: Job): boolean {
  return (j.parts || []).some((p) => p.part_name.startsWith("segment-"));
}

function workflowSegmentationMode(
  raw: string | undefined,
): "homogeneous" | "heterogeneous" {
  return raw === "heterogeneous" ? "heterogeneous" : "homogeneous";
}

export function SaveAsWorkflowModal({
  open,
  onOpenChange,
  job,
}: SaveAsWorkflowModalProps) {
  const router = useRouter();
  const queryClient = useQueryClient();
  const isSegmentedJob = jobIsSegmented(job);

  const [name, setName] = useState("");
  const [slug, setSlug] = useState("");
  const [slugManuallyEdited, setSlugManuallyEdited] = useState(false);
  const [description, setDescription] = useState("");
  const [responseMode, setResponseMode] = useState<WorkflowResponseMode>("sync");
  const [rateLimitPerMinute, setRateLimitPerMinute] = useState(60);
  const [rateLimitPerDay, setRateLimitPerDay] = useState(1000);
  const [webhookEnabled, setWebhookEnabled] = useState(false);
  const [webhookUrl, setWebhookUrl] = useState("");
  const [createdWorkflow, setCreatedWorkflow] = useState<{ id: string; slug: string } | null>(null);

  // Generate slug from name (only if not manually edited)
  useEffect(() => {
    if (name && !slugManuallyEdited) {
      const generated = name
        .toLowerCase()
        .replace(/[^a-z0-9]+/g, "-")
        .replace(/^-|-$/g, "");
      setSlug(generated);
    }
  }, [name, slugManuallyEdited]);

  // Reset form when modal opens
  useEffect(() => {
    if (open) {
      setName("");
      setSlug("");
      setSlugManuallyEdited(false);
      setDescription("");
      setResponseMode("sync");
      setRateLimitPerMinute(60);
      setRateLimitPerDay(1000);
      setWebhookEnabled(false);
      setWebhookUrl("");
      setCreatedWorkflow(null);
    }
  }, [open]);

  const createMutation = useMutation({
    mutationFn: () =>
      api.createWorkflow({
        name,
        slug,
        description: description || undefined,
        schema_id: job.schema_id!,
        ocr_provider: job.ocr_provider,
        llm_provider: job.llm_provider,
        ocr_model_config: job.ocr_model_config ?? undefined,
        response_mode: responseMode,
        rate_limit_per_minute: rateLimitPerMinute,
        rate_limit_per_day: rateLimitPerDay,
        webhook_url: webhookEnabled && webhookUrl ? webhookUrl : undefined,
        is_multidoc: isSegmentedJob && !!job.schema_id,
        segmentation_settings:
          isSegmentedJob && job.schema_id
            ? {
                // Prefer exact segmentation settings from the run/cache.
                mode: workflowSegmentationMode(job.segmentation_settings?.mode),
                ...(job.segmentation_settings?.expected_types?.length
                  ? { expected_types: job.segmentation_settings.expected_types }
                  : job.doc_type && job.doc_type !== "unknown"
                    ? { expected_types: [job.doc_type] }
                    : {}),
                ...(job.segmentation_settings?.profile
                  ? { profile: job.segmentation_settings.profile }
                  : job.segmentation_profile
                    ? { profile: job.segmentation_profile }
                    : {}),
              }
            : undefined,
      }),
    onSuccess: (workflow) => {
      setCreatedWorkflow({ id: workflow.id, slug: workflow.slug });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      toast.success("Workflow created successfully!");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to create workflow");
    },
  });

  const handleCreate = () => {
    if (!name.trim()) {
      toast.error("Please enter a workflow name");
      return;
    }
    if (!slug.trim()) {
      toast.error("Please enter a URL slug");
      return;
    }
    if (!job.schema_id) {
      toast.error(
        isSegmentedJob
          ? "Cannot save as workflow: use the same custom schema on every segment, or this job predates schema-on-job support (re-run extraction). Different schemas per segment are not supported as one workflow."
          : "No schema associated with this job",
      );
      return;
    }
    createMutation.mutate();
  };

  const copyEndpoint = () => {
    if (createdWorkflow) {
      const endpoint = `${window.location.origin}/api/v1/workflows/${createdWorkflow.slug}/extract`;
      navigator.clipboard.writeText(endpoint);
      toast.success("API endpoint copied to clipboard");
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent
        className={cn(
          "sm:max-w-lg",
          "flex max-h-[85vh] flex-col overflow-hidden gap-4"
        )}
      >
        {createdWorkflow ? (
          <>
            <DialogHeader className="shrink-0">
              <div className="flex items-center gap-3">
                <div className="w-10 h-10 rounded-full bg-emerald-100 dark:bg-emerald-900/30 flex items-center justify-center">
                  <CheckCircle2 className="w-5 h-5 text-emerald-600" />
                </div>
                <div>
                  <DialogTitle>Workflow Created!</DialogTitle>
                  <DialogDescription>
                    Your extraction workflow is ready to use as an API
                  </DialogDescription>
                </div>
              </div>
            </DialogHeader>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
              <div className="space-y-4 py-4">
                <div className="p-4 bg-muted rounded-lg space-y-3">
                  <div className="overflow-hidden">
                    <Label className="text-xs text-muted-foreground">API Endpoint</Label>
                    <div className="flex items-center gap-2 mt-1 overflow-hidden">
                      <div className="flex-1 min-w-0 overflow-hidden">
                        <code className="text-sm bg-background px-3 py-2 rounded border block truncate">
                          /api/v1/workflows/{createdWorkflow.slug}/extract
                        </code>
                      </div>
                      <Button variant="outline" size="icon" className="flex-shrink-0" onClick={copyEndpoint}>
                        <Copy className="w-4 h-4" />
                      </Button>
                    </div>
                  </div>
                  <p className="text-xs text-muted-foreground">
                    Create an API key to start making requests to this endpoint.
                  </p>
                </div>
              </div>
            </div>

            <DialogFooter className="shrink-0 gap-2 sm:gap-0">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Close
              </Button>
              <Button onClick={() => router.push(`/workflows/${createdWorkflow.id}/keys`)}>
                <Zap className="w-4 h-4 mr-2" />
                Create API Key
              </Button>
            </DialogFooter>
          </>
        ) : (
          <>
            <DialogHeader className="shrink-0">
              <DialogTitle className="flex items-center gap-2">
                <Zap className="w-5 h-5 text-amber-500" />
                Save as Workflow
              </DialogTitle>
              <DialogDescription>
                Expose this extraction configuration as an API endpoint
              </DialogDescription>
            </DialogHeader>

            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
              <div className="space-y-4 py-4">
              {/* Pre-filled configuration summary */}
              <div className="p-3 bg-muted/50 rounded-lg text-sm space-y-1">
                <div className="flex justify-between">
                  <span className="text-muted-foreground">Document Type:</span>
                  <span className="font-medium">{job.doc_type}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">OCR Provider:</span>
                  <span className="font-medium">{job.ocr_provider}</span>
                </div>
                <div className="flex justify-between">
                  <span className="text-muted-foreground">LLM Provider:</span>
                  <span className="font-medium">{job.llm_provider}</span>
                </div>
                {isSegmentedJob && job.schema_id && (
                  <div className="flex justify-between">
                    <span className="text-muted-foreground">Multi-document API:</span>
                    <span className="font-medium text-emerald-600 dark:text-emerald-400">Enabled</span>
                  </div>
                )}
              </div>

              {/* Basic info */}
              <div className="space-y-3">
                <div className="space-y-2">
                  <Label htmlFor="name">
                    Workflow Name <span className="text-destructive">*</span>
                  </Label>
                  <Input
                    id="name"
                    placeholder="e.g., Invoice Extractor"
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                  />
                </div>

                <div className="space-y-2">
                  <Label htmlFor="slug">
                    URL Slug <span className="text-destructive">*</span>
                  </Label>
                  <div className="flex items-center gap-1">
                    <span className="text-sm text-muted-foreground whitespace-nowrap">
                      /api/v1/workflows/
                    </span>
                    <Input
                      id="slug"
                      placeholder="invoice-extractor"
                      value={slug}
                      onChange={(e) => {
                        setSlug(e.target.value.toLowerCase().replace(/[^a-z0-9-]/g, ""));
                        setSlugManuallyEdited(true);
                      }}
                      className="flex-1"
                    />
                    <span className="text-sm text-muted-foreground">/extract</span>
                  </div>
                </div>

                <div className="space-y-2">
                  <Label htmlFor="description">Description</Label>
                  <Textarea
                    id="description"
                    placeholder="What does this workflow extract?"
                    value={description}
                    onChange={(e) => setDescription(e.target.value)}
                    rows={2}
                  />
                </div>
              </div>

              {/* Advanced settings */}
              <Accordion type="single" collapsible className="w-full">
                <AccordionItem value="api-settings" className="border rounded-lg px-3">
                  <AccordionTrigger className="text-sm py-3 hover:no-underline">
                    API Settings
                  </AccordionTrigger>
                  <AccordionContent className="space-y-4 pb-4">
                    <div className="space-y-2">
                      <Label>Response Mode</Label>
                      <Select
                        value={responseMode}
                        onValueChange={(v) => setResponseMode(v as WorkflowResponseMode)}
                      >
                        <SelectTrigger>
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          <SelectItem value="sync">
                            <div className="flex flex-col items-start">
                              <span>Synchronous</span>
                              <span className="text-xs text-muted-foreground">Wait for results</span>
                            </div>
                          </SelectItem>
                          <SelectItem value="async">
                            <div className="flex flex-col items-start">
                              <span>Asynchronous</span>
                              <span className="text-xs text-muted-foreground">Poll or webhook</span>
                            </div>
                          </SelectItem>
                        </SelectContent>
                      </Select>
                    </div>

                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-2">
                        <Label htmlFor="rateMin">Rate Limit / min</Label>
                        <Input
                          id="rateMin"
                          type="number"
                          min={1}
                          max={1000}
                          value={rateLimitPerMinute}
                          onChange={(e) => setRateLimitPerMinute(parseInt(e.target.value) || 60)}
                        />
                      </div>
                      <div className="space-y-2">
                        <Label htmlFor="rateDay">Rate Limit / day</Label>
                        <Input
                          id="rateDay"
                          type="number"
                          min={1}
                          max={100000}
                          value={rateLimitPerDay}
                          onChange={(e) => setRateLimitPerDay(parseInt(e.target.value) || 1000)}
                        />
                      </div>
                    </div>

                    {responseMode === "async" && (
                      <div className="space-y-3">
                        <div className="flex items-center justify-between">
                          <Label htmlFor="webhook">Webhook Callback</Label>
                          <Switch
                            id="webhook"
                            checked={webhookEnabled}
                            onCheckedChange={setWebhookEnabled}
                          />
                        </div>
                        {webhookEnabled && (
                          <Input
                            placeholder="https://your-server.com/webhook"
                            value={webhookUrl}
                            onChange={(e) => setWebhookUrl(e.target.value)}
                          />
                        )}
                      </div>
                    )}
                  </AccordionContent>
                </AccordionItem>
              </Accordion>
              </div>
            </div>

            <DialogFooter className="shrink-0">
              <Button variant="outline" onClick={() => onOpenChange(false)}>
                Cancel
              </Button>
              <Button onClick={handleCreate} disabled={createMutation.isPending}>
                {createMutation.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <Zap className="w-4 h-4 mr-2" />
                )}
                Create Workflow
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
