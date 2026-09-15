"use client";

import React, { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, API_BASE_URL, Workflow, WorkflowStatus, WorkflowPublishStatus } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Plus,
  Zap,
  MoreHorizontal,
  Settings,
  Key,
  BarChart2,
  Trash2,
  ExternalLink,
  Copy,
  CheckCircle2,
  PauseCircle,
  Archive,
  Users,
  Upload,
  Terminal,
  AlertCircle,
  FileEdit,
  Clock,
  Globe,
  XCircle,
  Send,
} from "lucide-react";
import { toast } from "@/components/ui/toast";
import { TestWorkflowModal } from "@/components/workflows/test-workflow-modal";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { useAuth } from "@/hooks/use-auth";

type TestMode = "direct" | "api";

// Separate component to ensure proper closure isolation for each workflow
function WorkflowToggle({
  workflowId,
  isActive,
  onToggle
}: {
  workflowId: string;
  isActive: boolean;
  onToggle: (id: string, status: WorkflowStatus) => void;
}) {
  return (
    <div onClick={(e) => e.stopPropagation()}>
      <button
        role="switch"
        aria-checked={isActive}
        title={isActive ? "Deactivate workflow" : "Activate workflow"}
        onClick={() => onToggle(workflowId, isActive ? "inactive" : "active")}
        className="relative inline-flex h-5 w-10 items-center"
      >
        {/* Thin track */}
        <span
          className={`
            absolute h-3 w-full rounded-full transition-colors
            ${isActive ? "bg-green-300" : "bg-gray-300"}
          `}
        />
        {/* Large circular thumb */}
        <span
          className={`
            absolute h-5 w-5 rounded-full shadow-md transition-all
            ${isActive ? "right-0 bg-green-500" : "left-0 bg-gray-400"}
          `}
        />
      </button>
    </div>
  );
}

export default function WorkflowsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, isAdmin } = useAuth();
  const [statusFilter, setStatusFilter] = useState<WorkflowStatus | "all">("all");
  const [testWorkflow, setTestWorkflow] = useState<Workflow | null>(null);
  const [testMode, setTestMode] = useState<TestMode>("direct");
  const [statusChangeDialog, setStatusChangeDialog] = useState<{
    open: boolean;
    workflowId: string;
    workflowName: string;
    newStatus: WorkflowStatus;
  } | null>(null);
  const [statusChangeReason, setStatusChangeReason] = useState("");
  const [publishDialog, setPublishDialog] = useState<{
    open: boolean;
    workflowId: string;
    workflowName: string;
    isResubmit: boolean;
  } | null>(null);
  const [publishComment, setPublishComment] = useState("");
  const [reviewWorkflow, setReviewWorkflow] = useState<Workflow | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");

  const { data: workflowsData, isLoading, refetch } = useQuery({
    queryKey: ["workflows", statusFilter],
    queryFn: () => api.listWorkflows({
      status: statusFilter === "all" ? undefined : statusFilter,
    }),
  });

  // Sort workflows by name to maintain consistent order
  const workflows = workflowsData?.slice().sort((a, b) => a.name.localeCompare(b.name));

  // Separate workflows into categories
  // My Workflows: owned by user AND not published (draft, pending_review, rejected)
  const myWorkflows = workflows?.filter(w =>
    w.owner_id === user?.id && w.publish_status !== "published"
  ) || [];
  // Published Workflows: ALL published workflows (including user's own)
  const publishedWorkflows = workflows?.filter(w =>
    w.publish_status === "published"
  ) || [];
  // Pending Review: workflows from others that need admin review
  const pendingReviewWorkflows = workflows?.filter(w =>
    w.owner_id !== user?.id && w.publish_status === "pending_review"
  ) || [];

  const toggleStatusMutation = useMutation({
    mutationFn: ({ id, status, reason }: { id: string; status: WorkflowStatus; reason: string }) =>
      api.updateWorkflow(id, { status, status_change_reason: reason }),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      toast.success(`${data.name} is now ${data.status}`);
      setStatusChangeDialog(null);
      setStatusChangeReason("");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to update workflow status");
    },
  });

  const handleStatusToggle = (workflow: Workflow, newStatus: WorkflowStatus) => {
    setStatusChangeDialog({
      open: true,
      workflowId: workflow.id,
      workflowName: workflow.name,
      newStatus,
    });
  };

  const confirmStatusChange = () => {
    if (!statusChangeDialog || !statusChangeReason.trim()) {
      toast.error("Please provide a reason for the status change");
      return;
    }
    toggleStatusMutation.mutate({
      id: statusChangeDialog.workflowId,
      status: statusChangeDialog.newStatus,
      reason: statusChangeReason,
    });
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

  const submitForReviewMutation = useMutation({
    mutationFn: ({ workflowId, comment }: { workflowId: string; comment: string }) =>
      api.submitWorkflowForReview(workflowId, comment),
    onSuccess: (data) => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      toast.success(`${data.name} submitted for review`);
      setPublishDialog(null);
      setPublishComment("");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to submit for review");
    },
  });

  const reviewWorkflowMutation = useMutation({
    mutationFn: ({ workflowId, approved, notes }: { workflowId: string; approved: boolean; notes?: string }) =>
      api.reviewWorkflow(workflowId, approved, notes),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["workflows"] });
      queryClient.invalidateQueries({ queryKey: ["pendingWorkflowCount"] });
      queryClient.invalidateQueries({ queryKey: ["admin", "pendingWorkflows"] });
      toast.success(variables.approved ? "Workflow approved and published" : "Workflow rejected");
      setReviewWorkflow(null);
      setReviewNotes("");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to review workflow");
    },
  });

  const handlePublishClick = (workflow: Workflow) => {
    setPublishDialog({
      open: true,
      workflowId: workflow.id,
      workflowName: workflow.name,
      isResubmit: workflow.publish_status === "rejected",
    });
  };

  const handleReviewClick = (workflow: Workflow) => {
    setReviewWorkflow(workflow);
    setReviewNotes("");
  };

  const confirmPublish = () => {
    if (!publishDialog) return;
    submitForReviewMutation.mutate({
      workflowId: publishDialog.workflowId,
      comment: publishComment.trim(),
    });
  };

  const copyApiEndpoint = (slug: string) => {
    const endpoint = `${API_BASE_URL}/api/v1/workflows/${slug}/extract`;
    navigator.clipboard.writeText(endpoint);
    toast.success("API endpoint copied to clipboard");
  };

  const copyCurl = (slug: string) => {
    const curl = `curl -X POST "${API_BASE_URL}/api/v1/workflows/${slug}/extract" \\
  -H "X-API-Key: wf_your_api_key" \\
  -F "file=@document.pdf"`;
    navigator.clipboard.writeText(curl);
    toast.success("cURL command copied to clipboard");
  };

  return (
    <div className="container mx-auto py-6 px-4 max-w-7xl space-y-6">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Workflows</h1>
          <p className="text-muted-foreground">
            Expose document extraction as API endpoints for external systems
          </p>
        </div>
        <Link href="/">
          <Button>
            <Plus className="w-4 h-4 mr-2" />
            New Extraction
          </Button>
        </Link>
      </div>

      {/* Filters */}
      <div className="flex items-center gap-4">
        <Select
          value={statusFilter}
          onValueChange={(v) => setStatusFilter(v as WorkflowStatus | "all")}
        >
          <SelectTrigger className="w-40">
            <SelectValue placeholder="Filter by status" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All Status</SelectItem>
            <SelectItem value="active">Active</SelectItem>
            <SelectItem value="inactive">Inactive</SelectItem>
            <SelectItem value="archived">Archived</SelectItem>
          </SelectContent>
        </Select>
        <div className="text-sm text-muted-foreground">
          {workflows?.length || 0} workflow{workflows?.length !== 1 ? "s" : ""}
        </div>
      </div>

      {/* Workflows Grid */}
      {isLoading ? (
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 pt-1">
          {[1, 2, 3].map((i) => (
            <Card key={i} className="animate-pulse">
              <CardHeader>
                <div className="h-5 bg-muted rounded w-3/4" />
                <div className="h-4 bg-muted rounded w-1/2 mt-2" />
              </CardHeader>
              <CardContent>
                <div className="h-4 bg-muted rounded w-full" />
              </CardContent>
            </Card>
          ))}
        </div>
      ) : workflows?.length === 0 ? (
        <Card className="border-dashed">
          <CardContent className="flex flex-col items-center justify-center py-12">
            <Zap className="w-12 h-12 text-muted-foreground/50 mb-4" />
            <h3 className="text-lg font-semibold mb-2">No workflows yet</h3>
            <p className="text-muted-foreground text-center mb-4 max-w-md">
              Run an extraction on the Extract page, then use &quot;Save as Workflow&quot; to expose it as an API endpoint
            </p>
            <Link href="/">
              <Button>
                <Plus className="w-4 h-4 mr-2" />
                Start Extraction
              </Button>
            </Link>
          </CardContent>
        </Card>
      ) : (
        <div className="space-y-8">
          {/* Pending Review Section - Only visible to admins */}
          {isAdmin && pendingReviewWorkflows.length > 0 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Clock className="w-5 h-5 text-yellow-600" />
                <h2 className="text-lg font-semibold">Pending Review</h2>
                <Badge variant="secondary" className="bg-yellow-100 text-yellow-700">
                  {pendingReviewWorkflows.length}
                </Badge>
              </div>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 pt-1">
                {pendingReviewWorkflows.map((workflow) => (
                  <WorkflowCard
                    key={workflow.id}
                    workflow={workflow}
                    isAdmin={isAdmin}
                    isOwner={false}
                    user={user}
                    router={router}
                    onCopyApiEndpoint={copyApiEndpoint}
                    onCopyCurl={copyCurl}
                    onStatusToggle={handleStatusToggle}
                    onTestDirect={(wf) => { setTestMode("direct"); setTestWorkflow(wf); }}
                    onTestApi={(wf) => { setTestMode("api"); setTestWorkflow(wf); }}
                    onPublishClick={handlePublishClick}
                    onReviewClick={handleReviewClick}
                    isSubmitting={submitForReviewMutation.isPending}
                    workflows={workflows}
                    getPublishStatusBadge={getPublishStatusBadge}
                  />
                ))}
              </div>
            </div>
          )}

          {/* My Workflows Section */}
          {myWorkflows.length > 0 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Users className="w-5 h-5 text-primary" />
                <h2 className="text-lg font-semibold">My Workflows</h2>
                <Badge variant="secondary">{myWorkflows.length}</Badge>
              </div>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 pt-1">
                {myWorkflows.map((workflow) => (
                  <WorkflowCard
                    key={workflow.id}
                    workflow={workflow}
                    isAdmin={isAdmin}
                    isOwner={true}
                    user={user}
                    router={router}
                    onCopyApiEndpoint={copyApiEndpoint}
                    onCopyCurl={copyCurl}
                    onStatusToggle={handleStatusToggle}
                    onTestDirect={(wf) => { setTestMode("direct"); setTestWorkflow(wf); }}
                    onTestApi={(wf) => { setTestMode("api"); setTestWorkflow(wf); }}
                    onPublishClick={handlePublishClick}
                    onReviewClick={handleReviewClick}
                    isSubmitting={submitForReviewMutation.isPending}
                    workflows={workflows}
                    getPublishStatusBadge={getPublishStatusBadge}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Published Workflows Section */}
          {publishedWorkflows.length > 0 && (
            <div className="space-y-4">
              <div className="flex items-center gap-2">
                <Globe className="w-5 h-5 text-blue-500" />
                <h2 className="text-lg font-semibold">Published Workflows</h2>
                <Badge variant="secondary" className="bg-blue-100 text-blue-700">
                  {publishedWorkflows.length}
                </Badge>
              </div>
              <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3 pt-1">
                {publishedWorkflows.map((workflow) => (
                  <WorkflowCard
                    key={workflow.id}
                    workflow={workflow}
                    isAdmin={isAdmin}
                    isOwner={workflow.owner_id === user?.id}
                    user={user}
                    router={router}
                    onCopyApiEndpoint={copyApiEndpoint}
                    onCopyCurl={copyCurl}
                    onStatusToggle={handleStatusToggle}
                    onTestDirect={(wf) => { setTestMode("direct"); setTestWorkflow(wf); }}
                    onTestApi={(wf) => { setTestMode("api"); setTestWorkflow(wf); }}
                    onPublishClick={handlePublishClick}
                    onReviewClick={handleReviewClick}
                    isSubmitting={submitForReviewMutation.isPending}
                    workflows={workflows}
                    getPublishStatusBadge={getPublishStatusBadge}
                  />
                ))}
              </div>
            </div>
          )}

          {/* Empty state if no workflows in any section */}
          {myWorkflows.length === 0 && publishedWorkflows.length === 0 && pendingReviewWorkflows.length === 0 && (
            <Card className="border-dashed">
              <CardContent className="flex flex-col items-center justify-center py-12">
                <Zap className="w-12 h-12 text-muted-foreground/50 mb-4" />
                <h3 className="text-lg font-semibold mb-2">No workflows found</h3>
                <p className="text-muted-foreground text-center mb-4 max-w-md">
                  No workflows match the current filter
                </p>
              </CardContent>
            </Card>
          )}
        </div>
      )}

      {/* Test Workflow Modal */}
      {testWorkflow && (
        <TestWorkflowModal
          open={!!testWorkflow}
          onOpenChange={(open) => !open && setTestWorkflow(null)}
          workflow={testWorkflow}
          initialMode={testMode}
        />
      )}

      {/* Status Change Reason Dialog */}
      <Dialog
        open={statusChangeDialog?.open ?? false}
        onOpenChange={(open) => {
          if (!open) {
            setStatusChangeDialog(null);
            setStatusChangeReason("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {statusChangeDialog?.newStatus === "active" ? "Enable" : "Disable"} Workflow
            </DialogTitle>
            <DialogDescription>
              You are about to {statusChangeDialog?.newStatus === "active" ? "enable" : "disable"}{" "}
              <span className="font-medium">{statusChangeDialog?.workflowName}</span>.
              Please provide a reason for this change.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="reason">Reason for change</Label>
              <Input
                id="reason"
                placeholder="e.g., Maintenance, Testing complete, Issue found..."
                value={statusChangeReason}
                onChange={(e) => setStatusChangeReason(e.target.value)}
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setStatusChangeDialog(null);
                setStatusChangeReason("");
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={confirmStatusChange}
              disabled={!statusChangeReason.trim() || toggleStatusMutation.isPending}
            >
              {toggleStatusMutation.isPending ? "Updating..." : "Confirm"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Publish Confirmation Dialog */}
      <Dialog
        open={publishDialog?.open ?? false}
        onOpenChange={(open) => {
          if (!open) {
            setPublishDialog(null);
            setPublishComment("");
          }
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {publishDialog?.isResubmit ? "Resubmit for Review" : "Submit for Review"}
            </DialogTitle>
            <DialogDescription>
              You are about to submit <span className="font-medium">{publishDialog?.workflowName}</span> for admin review.
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
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setPublishDialog(null);
                setPublishComment("");
              }}
            >
              Cancel
            </Button>
            <Button
              onClick={confirmPublish}
              disabled={!publishComment.trim() || submitForReviewMutation.isPending}
            >
              {submitForReviewMutation.isPending ? (
                "Submitting..."
              ) : (
                <>
                  <Send className="w-4 h-4 mr-2" />
                  {publishDialog?.isResubmit ? "Resubmit" : "Submit for Review"}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Review Workflow Dialog - Admin only */}
      <Dialog open={!!reviewWorkflow} onOpenChange={(open) => {
        if (!open) {
          setReviewWorkflow(null);
          setReviewNotes("");
        }
      }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Review Workflow</DialogTitle>
            <DialogDescription>
              Review and approve or reject "{reviewWorkflow?.name}"
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {reviewWorkflow && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Zap className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{reviewWorkflow.name}</span>
                  <code className="text-xs bg-muted px-1.5 py-0.5 rounded">
                    /{reviewWorkflow.slug}
                  </code>
                </div>
                <p className="text-sm text-muted-foreground">
                  {reviewWorkflow.description || "No description provided"}
                </p>
                <div className="text-xs text-muted-foreground space-y-1">
                  {reviewWorkflow.owner && (
                    <p>
                      Submitted by: <span className="font-medium">{reviewWorkflow.owner.display_name || reviewWorkflow.owner.username}</span>
                    </p>
                  )}
                  {reviewWorkflow.submit_notes && (
                    <div className="rounded-md border bg-muted/40 p-3 text-sm text-foreground">
                      <p className="text-xs font-medium text-muted-foreground mb-1">Publisher Comment</p>
                      <p>{reviewWorkflow.submit_notes}</p>
                    </div>
                  )}
                  {reviewWorkflow.schema_info && (
                    <p>
                      Schema: <span className="font-medium">{reviewWorkflow.schema_info.name}</span>
                    </p>
                  )}
                  <p>
                    Response Mode: <span className="font-medium">{reviewWorkflow.response_mode === "sync" ? "Synchronous" : "Asynchronous"}</span>
                  </p>
                </div>
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="workflow-review-notes">
                Review Notes <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="workflow-review-notes"
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                placeholder="Add feedback or notes for the workflow owner (required)..."
                rows={3}
              />
              <p className="text-xs text-muted-foreground">
                Review notes are required to approve or reject a workflow.
              </p>
            </div>
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => {
              setReviewWorkflow(null);
              setReviewNotes("");
            }}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => reviewWorkflow && reviewWorkflowMutation.mutate({
                workflowId: reviewWorkflow.id,
                approved: false,
                notes: reviewNotes,
              })}
              disabled={reviewWorkflowMutation.isPending || !reviewNotes.trim()}
            >
              <XCircle className="h-4 w-4 mr-1" />
              Reject
            </Button>
            <Button
              onClick={() => reviewWorkflow && reviewWorkflowMutation.mutate({
                workflowId: reviewWorkflow.id,
                approved: true,
                notes: reviewNotes,
              })}
              disabled={reviewWorkflowMutation.isPending || !reviewNotes.trim()}
            >
              <CheckCircle2 className="h-4 w-4 mr-1" />
              Approve & Publish
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

// Workflow Card Component
function WorkflowCard({
  workflow,
  isAdmin,
  isOwner,
  user,
  router,
  onCopyApiEndpoint,
  onCopyCurl,
  onStatusToggle,
  onTestDirect,
  onTestApi,
  onPublishClick,
  onReviewClick,
  isSubmitting,
  workflows,
  getPublishStatusBadge,
}: {
  workflow: Workflow;
  isAdmin: boolean;
  isOwner: boolean;
  user: { id: string } | null;
  router: ReturnType<typeof useRouter>;
  onCopyApiEndpoint: (slug: string) => void;
  onCopyCurl: (slug: string) => void;
  onStatusToggle: (workflow: Workflow, status: WorkflowStatus) => void;
  onTestDirect: (workflow: Workflow) => void;
  onTestApi: (workflow: Workflow) => void;
  onPublishClick: (workflow: Workflow) => void;
  onReviewClick: (workflow: Workflow) => void;
  isSubmitting: boolean;
  workflows: Workflow[] | undefined;
  getPublishStatusBadge: (status: WorkflowPublishStatus) => React.ReactNode;
}) {
  const isPendingReview = isAdmin && workflow.publish_status === "pending_review" && !isOwner;
  const managementAccess = workflow.management_access === true;
  const openDetailOnCardClick = managementAccess || isPendingReview;

  return (
    <Card
      className={`relative transition-all shadow-sm hover:shadow-md ${
        openDetailOnCardClick ? "cursor-pointer" : ""
      } ${isPendingReview ? "border-yellow-200 dark:border-yellow-800" : ""}`}
      onClick={() => {
        if (openDetailOnCardClick) router.push(`/workflows/${workflow.id}`);
      }}
    >
      {/* Needs Review Banner - for admins viewing pending workflows they don't own */}
      {isPendingReview && (
        <div className="absolute top-0 left-0 right-0 bg-yellow-100 dark:bg-yellow-900/30 px-3 py-1.5 rounded-t-lg border-b border-yellow-200 dark:border-yellow-800 z-10">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-yellow-700 dark:text-yellow-400 flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Needs your review
            </span>
            <button
              className="text-xs font-medium text-primary hover:underline"
              onClick={(e) => { e.stopPropagation(); onReviewClick(workflow); }}
            >
              Review
            </button>
          </div>
        </div>
      )}

      <CardHeader className={`pb-3 ${isPendingReview ? "pt-10" : ""}`}>
        <div className="flex items-start justify-between">
          <div className="flex-1 min-w-0">
            <CardTitle className="text-lg truncate">{workflow.name}</CardTitle>
            <CardDescription className="flex items-center gap-2 mt-1">
              <code className="text-xs bg-muted px-1.5 py-0.5 rounded">
                /{workflow.slug}
              </code>
            </CardDescription>
          </div>
          <DropdownMenu>
            <DropdownMenuTrigger asChild onClick={(e) => e.stopPropagation()}>
              <Button variant="ghost" size="icon" className="h-8 w-8" title="More options">
                <MoreHorizontal className="w-4 h-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" onClick={(e) => e.stopPropagation()}>
              <DropdownMenuItem onClick={(e) => { e.stopPropagation(); onCopyApiEndpoint(workflow.slug); }}>
                <Copy className="w-4 h-4 mr-2" />
                Copy API Endpoint
              </DropdownMenuItem>
              <DropdownMenuItem onClick={(e) => { e.stopPropagation(); onCopyCurl(workflow.slug); }}>
                <Terminal className="w-4 h-4 mr-2" />
                Copy cURL
              </DropdownMenuItem>
              {managementAccess && (
                <>
                  <DropdownMenuSeparator />
                  <DropdownMenuItem asChild>
                    <Link href={`/workflows/${workflow.id}`} onClick={(e) => e.stopPropagation()}>
                      <Settings className="w-4 h-4 mr-2" />
                      Settings
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link href={`/workflows/${workflow.id}/keys`} onClick={(e) => e.stopPropagation()}>
                      <Key className="w-4 h-4 mr-2" />
                      API Keys
                    </Link>
                  </DropdownMenuItem>
                  <DropdownMenuItem asChild>
                    <Link href={`/workflows/${workflow.id}/usage`} onClick={(e) => e.stopPropagation()}>
                      <BarChart2 className="w-4 h-4 mr-2" />
                      Usage Analytics
                    </Link>
                  </DropdownMenuItem>
                </>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {workflow.description && (
          <p className="text-sm text-muted-foreground line-clamp-2">
            {workflow.description}
          </p>
        )}

        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 flex-wrap">
            {getPublishStatusBadge(workflow.publish_status)}
            <Badge variant="outline">
              {workflow.response_mode === "sync" ? "Sync" : "Async"}
            </Badge>
            {workflow.publish_status === "published" && (
              <Badge variant="outline" className="text-xs font-normal bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/30 dark:text-purple-300 dark:border-purple-800">
                <Users className="w-3 h-3 mr-1" />
                {workflow.owner?.display_name || workflow.owner?.username || "Unknown"}
              </Badge>
            )}
          </div>
          {/* Toggle: owners can toggle non-published, only admins can toggle published */}
          {((isOwner && workflow.publish_status !== "published") || isAdmin) && (
            <WorkflowToggle
              workflowId={workflow.id}
              isActive={workflow.status === "active"}
              onToggle={(id, status) => {
                const wf = workflows?.find(w => w.id === id);
                if (wf) onStatusToggle(wf, status);
              }}
            />
          )}
        </div>

        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <span>Schema:</span>
            <span className="font-medium truncate">
              {workflow.schema_info?.name || "Unknown"}
            </span>
          </div>
          <div className="flex items-center gap-1.5 text-muted-foreground">
            <span>Rate:</span>
            <span className="font-medium">
              {workflow.rate_limit_per_minute}/min
            </span>
          </div>
        </div>

        {/* Show rejected review notes */}
        {workflow.publish_status === "rejected" && workflow.review_notes && (
          <div className="flex items-start gap-2 p-3 bg-red-50 dark:bg-red-950/30 rounded-lg" onClick={(e) => e.stopPropagation()}>
            <XCircle className="w-4 h-4 text-red-600 dark:text-red-400 flex-shrink-0 mt-0.5" />
            <div className="text-xs">
              <p className="font-medium text-red-700 dark:text-red-400">Review feedback:</p>
              <p className="text-red-600 dark:text-red-300 mt-0.5">{workflow.review_notes}</p>
            </div>
          </div>
        )}

        {workflow.status !== "active" ? (
          <div className="flex items-center gap-2 p-2 bg-amber-50 dark:bg-amber-950/30 rounded-lg" onClick={(e) => e.stopPropagation()}>
            <AlertCircle className="w-3.5 h-3.5 text-amber-600 dark:text-amber-400 flex-shrink-0" />
            <p className="text-xs text-amber-600 dark:text-amber-400 truncate" title={workflow.status_reason || "Workflow disabled"}>
              {workflow.status_reason || "Workflow disabled"}
            </p>
          </div>
        ) : (
          <div
            className="flex flex-col gap-2 pt-2 min-[480px]:flex-row min-[480px]:items-center min-[480px]:min-w-0"
            onClick={(e) => e.stopPropagation()}
          >
            <div className="grid min-w-0 flex-1 grid-cols-2 gap-2 max-[360px]:grid-cols-1">
              <Button
                variant="outline"
                size="sm"
                className="w-full min-w-0 hover:bg-muted"
                title="Try Extract"
                onClick={(e) => {
                  e.stopPropagation();
                  onTestDirect(workflow);
                }}
              >
                <Upload className="w-3.5 h-3.5 mr-1.5 shrink-0" />
                <span className="truncate">Try Extract</span>
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="w-full min-w-0 hover:bg-muted"
                title="API Console"
                onClick={(e) => {
                  e.stopPropagation();
                  onTestApi(workflow);
                }}
              >
                <Terminal className="w-3.5 h-3.5 mr-1.5 shrink-0" />
                <span className="truncate">API Console</span>
              </Button>
            </div>
            <div className="flex shrink-0 items-center justify-end gap-2 min-[480px]:justify-start">
              {isOwner && (workflow.publish_status === "draft" || workflow.publish_status === "rejected") && (
                <Button
                  variant="default"
                  size="sm"
                  className="px-3"
                  onClick={(e) => {
                    e.stopPropagation();
                    onPublishClick(workflow);
                  }}
                  disabled={isSubmitting}
                  title={workflow.publish_status === "rejected" ? "Resubmit for Review" : "Request Publishing"}
                >
                  <Send className="w-3.5 h-3.5" />
                </Button>
              )}
              {managementAccess && (
                <Link href={`/workflows/${workflow.id}`} onClick={(e) => e.stopPropagation()}>
                  <Button variant="ghost" size="sm" className="px-2">
                    <Settings className="w-4 h-4 text-muted-foreground" />
                  </Button>
                </Link>
              )}
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
