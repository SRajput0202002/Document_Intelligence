"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE_URL, Workflow, WorkflowUpdate, WorkflowStatus, WorkflowPublishStatus, WorkflowStatusChangeLog } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Zap,
  Loader2,
  Save,
  Trash2,
  Key,
  BarChart2,
  Users,
  Copy,
  ExternalLink,
  CheckCircle2,
  PauseCircle,
  Archive,
  Terminal,
  X,
  Play,
  Settings,
  FileEdit,
  Clock,
  Globe,
  XCircle,
  Send,
  History,
} from "lucide-react";
import { toast } from "@/components/ui/toast";
import { TestWorkflowModal } from "@/components/workflows/test-workflow-modal";
import { CopyButton } from "@/components/ui/copy-button";
import { useAuth } from "@/hooks/use-auth";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { isWorkflowAccessDeniedError } from "@/lib/utils";

export default function WorkflowDetailPage() {
  const params = useParams();
  const router = useRouter();
  const queryClient = useQueryClient();
  const workflowId = params.id as string;
  const normalizedWorkflowId = String(workflowId);

  const [form, setForm] = useState<WorkflowUpdate>({});
  const [webhookEnabled, setWebhookEnabled] = useState(false);
  const [isDirty, setIsDirty] = useState(false);
  const [showTestModal, setShowTestModal] = useState(false);
  const [testMode, setTestMode] = useState<"direct" | "api">("api");
  const [activeTab, setActiveTab] = useState<"api" | "settings" | "history">("api");
  const [rejectDialogOpen, setRejectDialogOpen] = useState(false);
  const [rejectReason, setRejectReason] = useState("");
  const [approveDialogOpen, setApproveDialogOpen] = useState(false);
  const [approveNotes, setApproveNotes] = useState("");
  const [publishDialogOpen, setPublishDialogOpen] = useState(false);
  const [publishComment, setPublishComment] = useState("");
  const [statusToggleDialog, setStatusToggleDialog] = useState<{
    open: boolean;
    newStatus: WorkflowStatus;
  } | null>(null);
  const [toggleReason, setToggleReason] = useState("");
  const { user, isAdmin } = useAuth();

  // Fetch workflow
  const { data: workflow, isLoading, isError, error } = useQuery({
    queryKey: ["workflow", workflowId],
    queryFn: () => api.getWorkflow(workflowId),
  });

  // Fetch schemas and providers
  const { data: schemas } = useQuery({
    queryKey: ["schemas"],
    queryFn: () => api.listSchemas(),
  });

  const { data: providers } = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.getProviders(),
  });

  const segmentationProfileSlug =
    workflow?.is_multidoc &&
    workflow.segmentation_settings &&
    typeof workflow.segmentation_settings.profile === "string" &&
    workflow.segmentation_settings.profile &&
    workflow.segmentation_settings.profile !== "auto"
      ? workflow.segmentation_settings.profile
      : null;

  const { data: segmentationProfiles, isLoading: segmentationProfilesLoading } = useQuery({
    queryKey: ["segmentation-profiles"],
    queryFn: () => api.listSegmentationProfiles(),
    enabled: !!segmentationProfileSlug,
  });

  const linkedSegmentationProfile = segmentationProfiles?.find(
    (p) => p.name === segmentationProfileSlug
  );

  // Fetch status history
  const { data: statusHistory } = useQuery({
    queryKey: ["workflow-status-history", workflowId],
    queryFn: () => api.getWorkflowStatusHistory(workflowId),
    enabled: activeTab === "history",
  });

  // Initialize form when workflow loads
  useEffect(() => {
    if (workflow) {
      setForm({
        name: workflow.name,
        description: workflow.description || "",
        schema_id: workflow.schema_id,
        ocr_provider: workflow.ocr_provider,
        llm_provider: workflow.llm_provider,
        ocr_model_config: workflow.ocr_model_config ?? undefined,
        status: workflow.status,
        response_mode: workflow.response_mode,
        webhook_url: workflow.webhook_url || "",
        rate_limit_per_minute: workflow.rate_limit_per_minute,
        rate_limit_per_day: workflow.rate_limit_per_day,
        settings: workflow.settings || {},
      });
      setWebhookEnabled(!!workflow.webhook_url);
    }
  }, [workflow]);

  // Update mutation
  const updateMutation = useMutation({
    mutationFn: (data: WorkflowUpdate) => api.updateWorkflow(workflowId, data),
    onSuccess: (updated) => {
      toast.success("Workflow updated");
      queryClient.invalidateQueries({ queryKey: ["workflow", normalizedWorkflowId] });
      queryClient.invalidateQueries({ queryKey: ["workflow", Number(normalizedWorkflowId)] });
      // Keep list/dropdown caches in sync: inactive ["workflows", ...] queries may not refetch
      // before navigating back, so merge the API response (name, description, etc.) now.
      queryClient.setQueriesData<Workflow[]>({ queryKey: ["workflows"] }, (old) => {
        if (!old) return old;
        return old.map((w) => (w.id === updated.id ? { ...w, ...updated } : w));
      });
      queryClient.invalidateQueries({ queryKey: ["workflows"], refetchType: "all" });
      setIsDirty(false);
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update workflow");
    },
  });

  // Delete mutation
  const deleteMutation = useMutation({
    mutationFn: () => api.deleteWorkflow(workflowId),
    onSuccess: () => {
      toast.success("Workflow deleted");
      router.push("/workflows");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to delete workflow");
    },
  });

  // Toggle status mutation
  const toggleStatusMutation = useMutation({
    mutationFn: ({ status, reason }: { status: WorkflowStatus; reason: string }) =>
      api.updateWorkflow(workflowId, { status, status_change_reason: reason }),
    onSuccess: (data) => {
      toast.success(`Workflow is now ${data.status}`);
      queryClient.invalidateQueries({ queryKey: ["workflow", normalizedWorkflowId] });
      queryClient.invalidateQueries({ queryKey: ["workflow", Number(normalizedWorkflowId)] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.invalidateQueries({ queryKey: ["workflow-status-history", workflowId] });
      setStatusToggleDialog(null);
      setToggleReason("");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update workflow status");
    },
  });

  // Submit for review mutation
  const submitForReviewMutation = useMutation({
    mutationFn: () => api.submitWorkflowForReview(workflowId, publishComment.trim()),
    onSuccess: () => {
      toast.success("Workflow submitted for review");
      queryClient.invalidateQueries({ queryKey: ["workflow", normalizedWorkflowId] });
      queryClient.invalidateQueries({ queryKey: ["workflow", Number(normalizedWorkflowId)] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.invalidateQueries({ queryKey: ["workflow-status-history", workflowId] });
      setPublishDialogOpen(false);
      setPublishComment("");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to submit for review");
    },
  });

  // Review workflow mutation (for admins)
  const reviewWorkflowMutation = useMutation({
    mutationFn: ({ approved, notes }: { approved: boolean; notes?: string }) =>
      api.reviewWorkflow(workflowId, approved, notes),
    onSuccess: (_, variables) => {
      toast.success(variables.approved ? "Workflow approved and published" : "Workflow rejected");
      queryClient.invalidateQueries({ queryKey: ["workflow", normalizedWorkflowId] });
      queryClient.invalidateQueries({ queryKey: ["workflow", Number(normalizedWorkflowId)] });
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.invalidateQueries({ queryKey: ["workflow-status-history", workflowId] });
      queryClient.invalidateQueries({ queryKey: ["admin", "pendingWorkflows"] });
      setRejectDialogOpen(false);
      setRejectReason("");
      setApproveDialogOpen(false);
      setApproveNotes("");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to review workflow");
    },
  });

  const handleFormChange = (updates: Partial<WorkflowUpdate>) => {
    setForm((prev) => ({ ...prev, ...updates }));
    setIsDirty(true);
  };

  const handleSave = () => {
    const data: WorkflowUpdate = {
      ...form,
      // Don't include status - it's now handled via toggle dialog
      status: undefined,
      webhook_url: webhookEnabled ? form.webhook_url : undefined,
    };
    updateMutation.mutate(data);
  };

  const copyApiEndpoint = () => {
    if (workflow) {
      const endpoint = `${API_BASE_URL}/api/v1/workflows/${workflow.slug}/extract`;
      navigator.clipboard.writeText(endpoint);
      toast.success("API endpoint copied");
    }
  };

  const getStatusBadge = (status: WorkflowStatus) => {
    const config = {
      active: { variant: "default" as const, icon: CheckCircle2, className: "bg-green-500" },
      inactive: { variant: "secondary" as const, icon: PauseCircle, className: "" },
      archived: { variant: "outline" as const, icon: Archive, className: "" },
    };
    const { variant, icon: Icon, className } = config[status];
    return (
      <Badge variant={variant} className={className}>
        <Icon className="w-3 h-3 mr-1" />
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </Badge>
    );
  };

  const getPublishStatusBadge = (publishStatus: WorkflowPublishStatus) => {
    const config = {
      draft: { variant: "outline" as const, icon: FileEdit, className: "border-gray-400 text-gray-600", label: "Draft" },
      pending_review: { variant: "outline" as const, icon: Clock, className: "border-yellow-500 text-yellow-600 bg-yellow-50 dark:bg-yellow-950/30", label: "Pending Review" },
      published: { variant: "default" as const, icon: Globe, className: "bg-blue-500", label: "Published" },
      rejected: { variant: "destructive" as const, icon: XCircle, className: "", label: "Rejected" },
    };
    const { variant, icon: Icon, className, label } = config[publishStatus];
    return (
      <Badge variant={variant} className={className}>
        <Icon className="w-3 h-3 mr-1" />
        {label}
      </Badge>
    );
  };

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (isError && isWorkflowAccessDeniedError(error)) {
    return (
      <div className="container mx-auto py-6">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 max-w-md mx-auto text-center">
            <h3 className="text-lg font-semibold mb-2">Access denied</h3>
            <p className="text-sm text-muted-foreground mb-6">
              Published workflows are visible to everyone, but only the owner, collaborators, or an administrator can open settings and management pages.
            </p>
            <Link href="/workflows">
              <Button variant="outline">Back to Workflows</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (isError || !workflow) {
    return (
      <div className="container mx-auto py-6">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <h3 className="text-lg font-semibold mb-2">Workflow not found</h3>
            {isError && error instanceof Error && (
              <p className="text-sm text-muted-foreground mb-4 text-center max-w-md">{error.message}</p>
            )}
            <Link href="/workflows">
              <Button variant="outline">Back to Workflows</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  // Include current schema even if not published, plus all active published schemas
  const currentSchema = schemas?.find((s) => s.id === workflow.schema_id);
  const activeSchemas = schemas?.filter((s) => s.is_active && s.status === "published") || [];
  const schemaOptions = currentSchema && !activeSchemas.find(s => s.id === currentSchema.id)
    ? [currentSchema, ...activeSchemas]
    : activeSchemas;
  const availableOcr = providers?.ocr_providers?.filter((p) => p.is_available) || [];
  const availableLlm = providers?.llm_providers?.filter((p) => p.is_available) || [];

  return (
    <div className="container mx-auto py-6 px-4 max-w-4xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 pb-4 border-b">
        <div className="flex items-center gap-3">
          <div>
            <h1 className="text-xl font-bold tracking-tight">{workflow.name}</h1>
            <div className="flex items-center gap-2">
              <code className="text-xs text-muted-foreground">
                /{workflow.slug}
              </code>
              {getStatusBadge(workflow.status)}
              {getPublishStatusBadge(workflow.publish_status)}
            </div>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <Button
            variant={activeTab === "api" ? "secondary" : "ghost"}
            size="icon"
            className="h-9 w-9"
            onClick={() => setActiveTab("api")}
            title="API Reference"
          >
            <Terminal className="w-4 h-4" />
          </Button>
          <Button
            variant={activeTab === "settings" ? "secondary" : "ghost"}
            size="icon"
            className="h-9 w-9"
            onClick={() => setActiveTab("settings")}
            title="Settings"
          >
            <Settings className="w-4 h-4" />
          </Button>
          <Button
            variant={activeTab === "history" ? "secondary" : "ghost"}
            size="icon"
            className="h-9 w-9"
            onClick={() => setActiveTab("history")}
            title="Status History"
          >
            <History className="w-4 h-4" />
          </Button>
          <Link href={`/workflows/${workflowId}/keys`}>
            <Button variant="ghost" size="icon" className="h-9 w-9" title="API Keys">
              <Key className="w-4 h-4" />
            </Button>
          </Link>
          <Link href={`/workflows/${workflowId}/usage`}>
            <Button variant="ghost" size="icon" className="h-9 w-9" title="Usage Analytics">
              <BarChart2 className="w-4 h-4" />
            </Button>
          </Link>
          {(workflow.publish_status === "draft" || workflow.publish_status === "rejected") && (
            <Button
              variant="default"
              size="sm"
              className="ml-2"
              onClick={() => setPublishDialogOpen(true)}
              disabled={submitForReviewMutation.isPending}
              title={workflow.publish_status === "rejected" ? "Resubmit for Review" : "Request Publishing"}
            >
              {submitForReviewMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-1 animate-spin" />
              ) : (
                <Send className="w-4 h-4 mr-1" />
              )}
              Publish
            </Button>
          )}
          <Link href="/workflows">
            <Button
              variant="ghost"
              size="icon"
              className="h-9 w-9 ml-2 bg-red-100 hover:bg-red-200 dark:bg-red-900/30 dark:hover:bg-red-900/50"
              title="Close"
            >
              <X className="w-4 h-4 text-red-600" />
            </Button>
          </Link>
        </div>
      </div>

      {activeTab === "settings" && (
        <div className="space-y-6">
          {/* Publishing Status */}
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Publishing Status</CardTitle>
                  <CardDescription>
                    {workflow.publish_status === "published"
                      ? "This workflow is published and accessible via the external API"
                      : workflow.publish_status === "pending_review"
                      ? "This workflow is awaiting admin review"
                      : workflow.publish_status === "rejected"
                      ? "This workflow was rejected and needs changes"
                      : "Submit this workflow for review to enable external API access"}
                  </CardDescription>
                </div>
                {getPublishStatusBadge(workflow.publish_status)}
              </div>
            </CardHeader>
            <CardContent className="space-y-4">
              {workflow.submit_notes && (
                <div className="rounded-md border bg-muted/40 p-3">
                  <p className="text-xs font-medium text-muted-foreground mb-1">Publisher Comment</p>
                  <p className="text-sm">{workflow.submit_notes}</p>
                </div>
              )}
              {/* Show review info if reviewed */}
              {workflow.reviewed_by && workflow.reviewed_at && (
                <div className="text-sm text-muted-foreground">
                  Reviewed by <span className="font-medium">{workflow.reviewed_by.display_name || workflow.reviewed_by.username}</span> on{" "}
                  {new Date(workflow.reviewed_at).toLocaleDateString()}
                </div>
              )}

              {/* Show rejection notes */}
              {workflow.publish_status === "rejected" && workflow.review_notes && (
                <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-950/30 rounded-lg">
                  <XCircle className="w-4 h-4 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
                  <div className="text-sm">
                    <p className="font-medium text-red-700 dark:text-red-400">Review feedback:</p>
                    <p className="text-red-600 dark:text-red-300 mt-1">{workflow.review_notes}</p>
                  </div>
                </div>
              )}

              {/* Submit for review button */}
              {(workflow.publish_status === "draft" || workflow.publish_status === "rejected") && (
                <Button
                  onClick={() => setPublishDialogOpen(true)}
                  disabled={submitForReviewMutation.isPending}
                >
                  {submitForReviewMutation.isPending ? (
                    <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  ) : (
                    <Send className="w-4 h-4 mr-2" />
                  )}
                  {workflow.publish_status === "rejected" ? "Resubmit for Review" : "Submit for Review"}
                </Button>
              )}

              {/* Pending review notice */}
              {workflow.publish_status === "pending_review" && (
                <div className="flex items-center gap-2 p-3 bg-yellow-50 dark:bg-yellow-950/30 rounded-lg">
                  <Clock className="w-4 h-4 text-yellow-600 dark:text-yellow-400 flex-shrink-0" />
                  <p className="text-sm text-yellow-700 dark:text-yellow-400">
                    Your workflow is pending admin review. You will be notified once it&apos;s approved or if changes are requested.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Basic Info */}
          <Card>
            <CardHeader>
              <CardTitle>Basic Information</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between gap-4">
                <div className="flex-1 space-y-2">
                  <Label htmlFor="name">Name</Label>
                  <Input
                    id="name"
                    value={form.name || ""}
                    onChange={(e) => handleFormChange({ name: e.target.value })}
                  />
                </div>

                <div className="flex flex-col items-end gap-1 pt-6">
                  <div className="flex items-center gap-3">
                    <Label htmlFor="status-toggle" className="text-sm text-muted-foreground">
                      {workflow.status === "active" ? "Active" : "Inactive"}
                    </Label>
                    <button
                      id="status-toggle"
                      role="switch"
                      aria-checked={workflow.status === "active"}
                      onClick={() => {
                        if (workflow.publish_status === "published" && !isAdmin) return;
                        setStatusToggleDialog({
                          open: true,
                          newStatus: workflow.status === "active" ? "inactive" : "active",
                        });
                      }}
                      disabled={workflow.publish_status === "published" && !isAdmin}
                      className={`relative inline-flex h-6 w-12 items-center ${
                        workflow.publish_status === "published" && !isAdmin ? "opacity-50 cursor-not-allowed" : ""
                      }`}
                    >
                      <span
                        className={`absolute h-4 w-full rounded-full transition-colors ${
                          workflow.status === "active" ? "bg-green-300" : "bg-gray-300"
                        }`}
                      />
                      <span
                        className={`absolute h-6 w-6 rounded-full shadow-md transition-all ${
                          workflow.status === "active" ? "right-0 bg-green-500" : "left-0 bg-gray-400"
                        }`}
                      />
                    </button>
                  </div>
                  {workflow.publish_status === "published" && !isAdmin && (
                    <p className="text-xs text-muted-foreground">
                      Only admins can change status
                    </p>
                  )}
                </div>
              </div>

              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea
                  id="description"
                  value={form.description || ""}
                  onChange={(e) => handleFormChange({ description: e.target.value })}
                  rows={2}
                  placeholder="Optional description for this workflow"
                />
              </div>

              {/* Status reason at bottom of card */}
              {workflow.status !== "active" && workflow.status_reason && (
                <div className="flex items-center gap-2 p-2 bg-amber-50 dark:bg-amber-950/30 rounded-lg">
                  <PauseCircle className="w-4 h-4 text-amber-600 dark:text-amber-400 flex-shrink-0" />
                  <p className="text-xs text-amber-600 dark:text-amber-400 truncate" title={workflow.status_reason}>
                    {workflow.status_reason}
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Extraction Configuration */}
          <Card>
            <CardHeader>
              <CardTitle>Extraction Configuration</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Schema</Label>
                <Select
                  value={form.schema_id}
                  onValueChange={(v) => handleFormChange({ schema_id: v })}
                >
                  <SelectTrigger>
                    <SelectValue placeholder="Select a schema" />
                  </SelectTrigger>
                  <SelectContent>
                    {schemaOptions.map((schema) => (
                      <SelectItem key={schema.id} value={schema.id}>
                        {schema.name} ({schema.doc_type})
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>OCR Provider</Label>
                  <Select
                    value={form.ocr_provider}
                    onValueChange={(v) => handleFormChange({ ocr_provider: v })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {availableOcr.map((provider) => (
                        <SelectItem key={provider.name} value={provider.name}>
                          {provider.display_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-2">
                  <Label>LLM Provider</Label>
                  <Select
                    value={form.llm_provider}
                    onValueChange={(v) => handleFormChange({ llm_provider: v })}
                  >
                    <SelectTrigger>
                      <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                      {availableLlm.map((provider) => (
                        <SelectItem key={provider.name} value={provider.name}>
                          {provider.display_name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>
              </div>

              {(() => {
                const selectedOcr = availableOcr.find((p) => p.name === form.ocr_provider);
                const modelConfig = selectedOcr?.config_options?.model as { default?: string; options?: Array<{ value: string; label: string }> } | undefined;
                const modelOptions = modelConfig?.options;
                if (!modelOptions || !Array.isArray(modelOptions) || modelOptions.length === 0) return null;
                const currentModel =
                  typeof (form.ocr_model_config as { model?: string } | undefined)?.model === "string"
                    ? (form.ocr_model_config as { model: string }).model
                    : undefined;
                return (
                  <div className="space-y-2">
                    <Label>OCR Model</Label>
                    <Select
                      value={currentModel ?? modelConfig?.default ?? ""}
                      onValueChange={(value) =>
                        handleFormChange({
                          ocr_model_config: { ...(form.ocr_model_config as Record<string, unknown>), model: value },
                        })
                      }
                    >
                      <SelectTrigger>
                        <SelectValue placeholder="Use provider default" />
                      </SelectTrigger>
                      <SelectContent>
                        {modelOptions.map((opt) => (
                          <SelectItem key={opt.value} value={opt.value}>
                            {opt.label}
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                );
              })()}

              {workflow.is_multidoc && workflow.segmentation_settings && (
                <div className="rounded-xl border border-border/80 bg-muted/25 p-5 text-sm shadow-sm">
                  <h4 className="text-base font-semibold tracking-tight text-foreground pb-3 mb-1 border-b border-border/60">
                    Multi-doc segmentation
                  </h4>
                  <div className="mt-4 space-y-0">
                    {segmentationProfileSlug ? (
                      segmentationProfilesLoading ? (
                        <>
                          {typeof workflow.segmentation_settings.profile === "string" &&
                            workflow.segmentation_settings.profile && (
                              <dl className="grid grid-cols-1 gap-y-3 sm:grid-cols-[minmax(11rem,13rem)_1fr] sm:gap-x-6 text-sm">
                                <dt className="text-muted-foreground font-medium leading-snug pt-0.5">
                                  Profile slug
                                </dt>
                                <dd className="text-foreground font-mono text-xs sm:text-sm break-all">
                                  {workflow.segmentation_settings.profile}
                                </dd>
                              </dl>
                            )}
                          <p className="mt-4 flex items-center gap-2.5 text-sm text-muted-foreground py-2">
                            <Loader2 className="h-4 w-4 shrink-0 animate-spin text-muted-foreground/80" />
                            Loading profile from server…
                          </p>
                        </>
                      ) : linkedSegmentationProfile ? (
                        <>
                          <dl className="grid grid-cols-1 gap-y-3.5 sm:grid-cols-[minmax(11rem,13rem)_1fr] sm:gap-x-6 sm:gap-y-3.5 text-sm">
                            <dt className="text-muted-foreground font-medium leading-snug pt-0.5">
                              Profile slug
                            </dt>
                            <dd className="text-foreground font-mono text-xs sm:text-sm break-all">
                              {workflow.segmentation_settings.profile}
                            </dd>
                            <dt className="text-muted-foreground font-medium leading-snug pt-0.5">
                              Display name
                            </dt>
                            <dd className="text-foreground leading-relaxed">
                              {linkedSegmentationProfile.display_name}
                            </dd>
                            <dt className="text-muted-foreground font-medium leading-snug pt-0.5">
                              Default detection method
                            </dt>
                            <dd className="text-foreground leading-relaxed">
                              {linkedSegmentationProfile.default_detection_method
                                ? String(linkedSegmentationProfile.default_detection_method)
                                : "—"}
                            </dd>
                            <dt className="text-muted-foreground font-medium leading-snug pt-0.5">
                              Segmentation OCR (profile)
                            </dt>
                            <dd className="text-foreground leading-relaxed">
                              {linkedSegmentationProfile.ocr_method
                                ? String(linkedSegmentationProfile.ocr_method)
                                : "—"}
                            </dd>
                            <dt className="text-muted-foreground font-medium leading-snug pt-0.5">
                              Section splitting
                            </dt>
                            <dd className="text-foreground leading-relaxed">
                              <span
                                className={
                                  linkedSegmentationProfile.enable_section_splitting
                                    ? "inline-flex items-center rounded-md bg-emerald-500/15 px-2 py-0.5 text-xs font-medium text-emerald-800 dark:text-emerald-300"
                                    : "inline-flex items-center rounded-md bg-muted px-2 py-0.5 text-xs font-medium text-muted-foreground"
                                }
                              >
                                {linkedSegmentationProfile.enable_section_splitting ? "On" : "Off"}
                              </span>
                            </dd>
                          </dl>
                          <p className="mt-5 pt-4 border-t border-border/50 text-xs leading-relaxed text-muted-foreground">
                            Values are read from the current{" "}
                            <code className="rounded-md bg-muted px-1.5 py-0.5 text-[0.7rem] font-mono">
                              segmentation_profiles
                            </code>{" "}
                            row (same source as API execution). Reload this page after editing the profile in
                            Segmentation settings to refresh.
                          </p>
                        </>
                      ) : (
                        <p className="mt-4 text-sm leading-relaxed text-amber-800 dark:text-amber-300/95 bg-amber-500/10 dark:bg-amber-950/40 rounded-lg px-3 py-2.5 border border-amber-500/20">
                          No segmentation profile named &quot;{segmentationProfileSlug}&quot; was found.
                          Workflow runs will not apply profile defaults until the name matches a row.
                        </p>
                      )
                    ) : (
                      <p className="mt-4 text-sm leading-relaxed text-muted-foreground py-1">
                        No profile slug on this workflow. Multi-doc runs use workflow OCR and defaults
                        only.
                      </p>
                    )}
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          {/* API Settings */}
          <Card>
            <CardHeader>
              <CardTitle>API Settings</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="space-y-2">
                <Label>Response Mode</Label>
                <Select
                  value={form.response_mode}
                  onValueChange={(v) => handleFormChange({ response_mode: v as "sync" | "async" })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="sync">Synchronous</SelectItem>
                    <SelectItem value="async">Asynchronous</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              {form.response_mode === "async" && (
                <div className="space-y-4 pl-4 border-l-2 border-muted">
                  <div className="flex items-center justify-between">
                    <div>
                      <Label>Webhook Callback</Label>
                      <p className="text-xs text-muted-foreground">
                        Receive a POST when extraction completes
                      </p>
                    </div>
                    <Switch
                      checked={webhookEnabled}
                      onCheckedChange={(checked) => {
                        setWebhookEnabled(checked);
                        setIsDirty(true);
                      }}
                    />
                  </div>

                  {webhookEnabled && (
                    <div className="space-y-2">
                      <Label>Webhook URL</Label>
                      <Input
                        type="url"
                        placeholder="https://your-app.com/webhook"
                        value={form.webhook_url || ""}
                        onChange={(e) => handleFormChange({ webhook_url: e.target.value })}
                      />
                    </div>
                  )}
                </div>
              )}

              <div className="grid gap-4 md:grid-cols-2">
                <div className="space-y-2">
                  <Label>Rate Limit (per minute)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={1000}
                    value={form.rate_limit_per_minute}
                    onChange={(e) => handleFormChange({ rate_limit_per_minute: parseInt(e.target.value) || 60 })}
                  />
                </div>

                <div className="space-y-2">
                  <Label>Rate Limit (per day)</Label>
                  <Input
                    type="number"
                    min={1}
                    max={100000}
                    value={form.rate_limit_per_day}
                    onChange={(e) => handleFormChange({ rate_limit_per_day: parseInt(e.target.value) || 1000 })}
                  />
                </div>
              </div>
            </CardContent>
          </Card>

          {/* Auto-Disable Triggers */}
          <Card>
            <CardHeader>
              <CardTitle>Auto-Disable Triggers</CardTitle>
              <CardDescription>
                Automatically disable this workflow when usage limits are reached
              </CardDescription>
            </CardHeader>
            <CardContent className="space-y-4">
              <div className="flex items-center justify-between">
                <div>
                  <Label>Enable Auto-Disable</Label>
                  <p className="text-xs text-muted-foreground">
                    Workflow will be disabled when any limit is reached
                  </p>
                </div>
                <Switch
                  checked={form.settings?.auto_disable?.enabled || false}
                  onCheckedChange={(checked) => {
                    handleFormChange({
                      settings: {
                        ...form.settings,
                        auto_disable: {
                          ...form.settings?.auto_disable,
                          enabled: checked,
                          period: form.settings?.auto_disable?.period || "monthly",
                        },
                      },
                    });
                  }}
                />
              </div>

              {form.settings?.auto_disable?.enabled && (
                <div className="space-y-4 pl-4 border-l-2 border-muted">
                  <div className="space-y-2">
                    <Label>Reset Period</Label>
                    <Select
                      value={form.settings?.auto_disable?.period || "monthly"}
                      onValueChange={(v) => {
                        handleFormChange({
                          settings: {
                            ...form.settings,
                            auto_disable: {
                              ...form.settings?.auto_disable,
                              enabled: true,
                              period: v as "daily" | "monthly" | "total",
                            },
                          },
                        });
                      }}
                    >
                      <SelectTrigger>
                        <SelectValue />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="daily">Daily</SelectItem>
                        <SelectItem value="monthly">Monthly</SelectItem>
                        <SelectItem value="total">Total (no reset)</SelectItem>
                      </SelectContent>
                    </Select>
                    <p className="text-xs text-muted-foreground">
                      Usage counters reset at the start of each period
                    </p>
                  </div>

                  <div className="grid gap-4 md:grid-cols-3">
                    <div className="space-y-2">
                      <Label>Max API Calls</Label>
                      <Input
                        type="number"
                        min={1}
                        placeholder="No limit"
                        value={form.settings?.auto_disable?.max_calls || ""}
                        onChange={(e) => {
                          const value = e.target.value ? parseInt(e.target.value) : undefined;
                          handleFormChange({
                            settings: {
                              ...form.settings,
                              auto_disable: {
                                ...form.settings?.auto_disable,
                                enabled: true,
                                period: form.settings?.auto_disable?.period || "monthly",
                                max_calls: value,
                              },
                            },
                          });
                        }}
                      />
                    </div>

                    <div className="space-y-2">
                      <Label>Max Tokens</Label>
                      <Input
                        type="number"
                        min={1}
                        placeholder="No limit"
                        value={form.settings?.auto_disable?.max_tokens || ""}
                        onChange={(e) => {
                          const value = e.target.value ? parseInt(e.target.value) : undefined;
                          handleFormChange({
                            settings: {
                              ...form.settings,
                              auto_disable: {
                                ...form.settings?.auto_disable,
                                enabled: true,
                                period: form.settings?.auto_disable?.period || "monthly",
                                max_tokens: value,
                              },
                            },
                          });
                        }}
                      />
                    </div>

                    <div className="space-y-2">
                      <Label>Max Cost (USD)</Label>
                      <Input
                        type="number"
                        min={0.01}
                        step={0.01}
                        placeholder="No limit"
                        value={form.settings?.auto_disable?.max_cost || ""}
                        onChange={(e) => {
                          const value = e.target.value ? parseFloat(e.target.value) : undefined;
                          handleFormChange({
                            settings: {
                              ...form.settings,
                              auto_disable: {
                                ...form.settings?.auto_disable,
                                enabled: true,
                                period: form.settings?.auto_disable?.period || "monthly",
                                max_cost: value,
                              },
                            },
                          });
                        }}
                      />
                    </div>
                  </div>

                  <p className="text-xs text-muted-foreground">
                    Leave empty for no limit. The workflow will be disabled when any limit is reached.
                  </p>
                </div>
              )}
            </CardContent>
          </Card>

          {/* Actions */}
          <div className="flex items-center justify-between">
            <AlertDialog>
              <AlertDialogTrigger asChild>
                <Button variant="destructive" size="sm">
                  <Trash2 className="w-4 h-4 mr-2" />
                  Delete Workflow
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>Delete workflow?</AlertDialogTitle>
                  <AlertDialogDescription>
                    This will permanently delete the workflow and all associated API keys.
                    This action cannot be undone.
                  </AlertDialogDescription>
                </AlertDialogHeader>
                <AlertDialogFooter>
                  <AlertDialogCancel>Cancel</AlertDialogCancel>
                  <AlertDialogAction
                    onClick={() => deleteMutation.mutate()}
                    className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                  >
                    Delete
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>

            <Button
              onClick={handleSave}
              disabled={!isDirty || updateMutation.isPending}
            >
              {updateMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Save className="w-4 h-4 mr-2" />
              )}
              Save Changes
            </Button>
          </div>
        </div>
      )}

      {activeTab === "api" && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>API Reference</CardTitle>
                  <CardDescription>How to call this workflow from external systems</CardDescription>
                </div>
                <div className="flex items-center gap-2">
                  <Button
                    variant="outline"
                    onClick={() => {
                      setTestMode("direct");
                      setShowTestModal(true);
                    }}
                  >
                    <Play className="w-4 h-4 mr-2" />
                    Test
                  </Button>
                  <Button
                    onClick={() => {
                      setTestMode("api");
                      setShowTestModal(true);
                    }}
                  >
                    <Terminal className="w-4 h-4 mr-2" />
                    Test API
                  </Button>
                </div>
              </div>
            </CardHeader>
            <CardContent className="space-y-6">
              {/* Endpoint */}
              <div>
                <h4 className="font-medium mb-2">Endpoint</h4>
                <CodeBlock code={`POST /api/v1/workflows/${workflow.slug}/extract`} />
              </div>

              {/* Authentication */}
              <div>
                <h4 className="font-medium mb-2">Authentication</h4>
                <p className="text-sm text-muted-foreground mb-2">
                  Include your API key in the X-API-Key header:
                </p>
                <CodeBlock code="X-API-Key: wf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx" />
              </div>

              {/* Request */}
              <div>
                <h4 className="font-medium mb-2">Request</h4>
                <p className="text-sm text-muted-foreground mb-2">
                  Send a multipart/form-data request with your document:
                </p>
                <CodeBlock
                  code={`curl -X POST "${API_BASE_URL}/api/v1/workflows/${workflow.slug}/extract" \\
  -H "X-API-Key: wf_your_api_key" \\
  -F "file=@document.pdf"`}
                  multiline
                />
              </div>

              {/* Response */}
              <div>
                <h4 className="font-medium mb-2">Response ({workflow.response_mode})</h4>
                <CodeBlock
                  code={workflow.response_mode === "sync" ? `{
  "success": true,
  "job_id": "uuid",
  "data": {
    "parts": [
      { "name": "header", "data": {...}, "confidence": 0.95 }
    ]
  },
  "processing_time_ms": 2450,
  "tokens": { "input": 1000, "output": 500 }
}` : `{
  "success": true,
  "job_id": "uuid",
  "status": "processing",
  "poll_url": "/api/v1/workflows/${workflow.slug}/jobs/{job_id}"
}`}
                  multiline
                />
              </div>

              {/* Rate Limits */}
              <div>
                <h4 className="font-medium mb-2">Rate Limits</h4>
                <ul className="text-sm text-muted-foreground space-y-1">
                  <li>{workflow.rate_limit_per_minute} requests per minute</li>
                  <li>{workflow.rate_limit_per_day} requests per day</li>
                </ul>
              </div>
            </CardContent>
          </Card>
        </div>
      )}

      {activeTab === "history" && (
        <div className="space-y-6">
          <Card>
            <CardHeader>
              <CardTitle>Status Change History</CardTitle>
              <CardDescription>
                Track all status and publishing changes for this workflow
              </CardDescription>
            </CardHeader>
            <CardContent>
              {!statusHistory || statusHistory.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground">
                  <History className="w-12 h-12 mx-auto mb-4 opacity-50" />
                  <p>No status changes recorded yet</p>
                </div>
              ) : (
                <div className="space-y-4">
                  {statusHistory.map((log) => (
                    <div key={log.id} className="flex items-start gap-3 p-3 border rounded-lg">
                      <div className="flex-shrink-0 mt-0.5">
                        {log.change_type === "status_change" ? (
                          <Settings className="w-4 h-4 text-muted-foreground" />
                        ) : log.change_type === "publish_submit" ? (
                          <Send className="w-4 h-4 text-blue-500" />
                        ) : log.new_value === "published" ? (
                          <CheckCircle2 className="w-4 h-4 text-green-500" />
                        ) : (
                          <XCircle className="w-4 h-4 text-red-500" />
                        )}
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 flex-wrap">
                          <span className="font-medium text-sm">
                            {log.change_type === "status_change"
                              ? "Status changed"
                              : log.change_type === "publish_submit"
                              ? "Submitted for review"
                              : log.new_value === "published"
                              ? "Published"
                              : "Rejected"}
                          </span>
                          {log.old_value && (
                            <>
                              <Badge variant="outline" className="text-xs">
                                {log.old_value}
                              </Badge>
                              <span className="text-muted-foreground">→</span>
                            </>
                          )}
                          <Badge
                            variant={
                              log.new_value === "active" || log.new_value === "published"
                                ? "default"
                                : log.new_value === "rejected"
                                ? "destructive"
                                : "secondary"
                            }
                            className={
                              log.new_value === "active" || log.new_value === "published"
                                ? "bg-green-500"
                                : ""
                            }
                          >
                            {log.new_value}
                          </Badge>
                        </div>
                        {log.reason && (
                          <p className="text-sm text-muted-foreground mt-1">{log.reason}</p>
                        )}
                        <p className="text-xs text-muted-foreground mt-1">
                          by {log.changed_by?.display_name || log.changed_by?.username || "Unknown"} on{" "}
                          {log.created_at ? new Date(log.created_at).toLocaleString() : "Unknown"}
                        </p>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </div>
      )}

      {/* Admin Review Section - Floating buttons */}
      {isAdmin && workflow.publish_status === "pending_review" && workflow.owner_id !== user?.id && (
        <div className="fixed bottom-6 right-6 flex items-center gap-2 z-50">
          <Button
            variant="outline"
            onClick={() => setRejectDialogOpen(true)}
            disabled={reviewWorkflowMutation.isPending}
            className="border-red-300 text-red-600 hover:bg-red-50 hover:text-red-700 shadow-lg"
          >
            <XCircle className="w-4 h-4 mr-2" />
            Reject
          </Button>
          <Button
            onClick={() => setApproveDialogOpen(true)}
            disabled={reviewWorkflowMutation.isPending}
            className="bg-green-600 hover:bg-green-700 shadow-lg"
          >
            <CheckCircle2 className="w-4 h-4 mr-2" />
            Approve
          </Button>
        </div>
      )}

      {/* Reject Dialog */}
      <Dialog open={rejectDialogOpen} onOpenChange={setRejectDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Reject Workflow</DialogTitle>
            <DialogDescription>
              Please provide a reason for rejecting this workflow. This feedback will be shown to the owner so they can address the issues.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="reject-reason">
                Rejection Reason <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="reject-reason"
                placeholder="Explain why this workflow is being rejected and what changes are needed..."
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                rows={4}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setRejectDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => {
                if (!rejectReason.trim()) {
                  toast.error("Please provide a reason for rejection");
                  return;
                }
                reviewWorkflowMutation.mutate({ approved: false, notes: rejectReason });
              }}
              disabled={!rejectReason.trim() || reviewWorkflowMutation.isPending}
            >
              {reviewWorkflowMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <XCircle className="w-4 h-4 mr-2" />
              )}
              Reject Workflow
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Approve Dialog */}
      <Dialog open={approveDialogOpen} onOpenChange={setApproveDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve Workflow</DialogTitle>
            <DialogDescription>
              Please provide review notes for approving this workflow. This feedback will be recorded in the history.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="approve-notes">
                Review Notes <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="approve-notes"
                placeholder="Add any notes about the approval (e.g., 'Reviewed and approved for production use')..."
                value={approveNotes}
                onChange={(e) => setApproveNotes(e.target.value)}
                rows={4}
              />
              <p className="text-xs text-muted-foreground">
                Review notes are required to approve this workflow.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setApproveDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (!approveNotes.trim()) {
                  toast.error("Please provide review notes");
                  return;
                }
                reviewWorkflowMutation.mutate({ approved: true, notes: approveNotes });
              }}
              disabled={!approveNotes.trim() || reviewWorkflowMutation.isPending}
              className="bg-green-600 hover:bg-green-700"
            >
              {reviewWorkflowMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <CheckCircle2 className="w-4 h-4 mr-2" />
              )}
              Approve & Publish
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Publish Confirmation Dialog */}
      <Dialog open={publishDialogOpen} onOpenChange={setPublishDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {workflow?.publish_status === "rejected" ? "Resubmit for Review" : "Submit for Review"}
            </DialogTitle>
            <DialogDescription>
              You are about to submit <span className="font-medium">{workflow?.name}</span> for admin review.
              Once approved, this workflow will be published and accessible to all users via the API.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="publish-comment">
                Comments <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="publish-comment"
                placeholder="Describe what this workflow does and why it should be published..."
                value={publishComment}
                onChange={(e) => setPublishComment(e.target.value)}
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setPublishDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={() => submitForReviewMutation.mutate()}
              disabled={!publishComment.trim() || submitForReviewMutation.isPending}
            >
              {submitForReviewMutation.isPending ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin" />
              ) : (
                <Send className="w-4 h-4 mr-2" />
              )}
              {workflow?.publish_status === "rejected" ? "Resubmit" : "Submit for Review"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Status Toggle Dialog */}
      <Dialog
        open={statusToggleDialog?.open ?? false}
        onOpenChange={(open) => {
          if (!open) {
            setStatusToggleDialog(null);
            setToggleReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {statusToggleDialog?.newStatus === "active" ? "Enable" : "Disable"} Workflow
            </DialogTitle>
            <DialogDescription>
              You are about to {statusToggleDialog?.newStatus === "active" ? "enable" : "disable"}{" "}
              <span className="font-medium">{workflow?.name}</span>.
              Please provide a reason for this change.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="toggle-reason">Reason for change</Label>
              <Input
                id="toggle-reason"
                placeholder="e.g., Maintenance, Testing complete, Issue found..."
                value={toggleReason}
                onChange={(e) => setToggleReason(e.target.value)}
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setStatusToggleDialog(null);
                setToggleReason("");
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={() => {
                if (statusToggleDialog) {
                  toggleStatusMutation.mutate({
                    status: statusToggleDialog.newStatus,
                    reason: toggleReason,
                  });
                }
              }}
              disabled={!toggleReason.trim() || toggleStatusMutation.isPending}
            >
              {toggleStatusMutation.isPending ? "Updating..." : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Test API Modal */}
      <TestWorkflowModal
        open={showTestModal}
        onOpenChange={setShowTestModal}
        workflow={workflow}
        initialMode={testMode}
      />
    </div>
  );
}

// Code block component with copy button
function CodeBlock({
  code,
  multiline = false,
}: {
  code: string;
  multiline?: boolean;
}) {
  return (
    <div className="relative group">
      {multiline ? (
        <pre className="bg-muted p-3 pr-12 rounded text-sm overflow-x-auto">{code}</pre>
      ) : (
        <code className="block bg-muted p-3 pr-12 rounded text-sm">{code}</code>
      )}
      <CopyButton
        value={code}
        className="absolute top-2 right-2 h-7 w-7 opacity-0 group-hover:opacity-100"
      />
    </div>
  );
}
