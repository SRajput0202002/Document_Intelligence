"use client";

import { useState, useMemo, useEffect } from "react";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Trash2,
  XCircle,
  Loader2,
  AlertCircle,
  ChevronLeft,
  ChevronRight,
} from "lucide-react";

// Animated icons
import { HistoryIcon } from "@/components/ui/history";
import { EyeIcon } from "@/components/ui/eye";
import { DownloadIcon } from "@/components/ui/download";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { ClockIcon } from "@/components/ui/clock";
import { FileTextIcon } from "@/components/ui/file-text";
import { SearchIcon } from "@/components/ui/search";
import { RefreshCWIcon } from "@/components/ui/refresh-cw";
import { RotateCCWIcon } from "@/components/ui/rotate-ccw";
import { CopyIcon } from "@/components/ui/copy";
import { ChevronDownIcon } from "@/components/ui/chevron-down";
import { SparklesIcon } from "@/components/ui/sparkles";
import { LayersIcon } from "@/components/ui/layers";
import { DollarSignIcon } from "@/components/ui/dollar-sign";
import { TrendingUpIcon } from "@/components/ui/trending-up";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import {
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from "@/components/ui/alert-dialog";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Progress } from "@/components/ui/progress";
import { toast } from "@/components/ui/toast";
import { api, type Job, type JobPart, type Workflow } from "@/lib/api";
import { formatDate, formatCost, cn } from "@/lib/utils";

const JOBS_PAGE_SIZE = 20;

/** Compact numbered list with ellipses (Google-style). */
function buildPaginationRange(
  currentPage: number,
  totalPages: number,
  delta = 1
): (number | "ellipsis")[] {
  if (totalPages <= 1) {
    return totalPages === 1 ? [1] : [];
  }

  const range: number[] = [];
  for (let i = 1; i <= totalPages; i++) {
    if (
      i === 1 ||
      i === totalPages ||
      (i >= currentPage - delta && i <= currentPage + delta)
    ) {
      range.push(i);
    }
  }

  const out: (number | "ellipsis")[] = [];
  let prev: number | undefined;
  for (const i of range) {
    if (prev !== undefined) {
      if (i - prev === 2) {
        out.push(prev + 1);
      } else if (i - prev > 1) {
        out.push("ellipsis");
      }
    }
    out.push(i);
    prev = i;
  }
  return out;
}

export default function JobsPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const [statusFilter, setStatusFilter] = useState<string>("all");
  const [docTypeFilter, setDocTypeFilter] = useState<string>("all");
  const [workflowFilter, setWorkflowFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedJob, setSelectedJob] = useState<Job | null>(null);
  const [deleteJob, setDeleteJob] = useState<Job | null>(null);
  const [expandedParts, setExpandedParts] = useState<Set<string>>(new Set());
  const [tablePage, setTablePage] = useState(1);

  // Fetch workflows for filter dropdown
  const { data: workflows } = useQuery({
    queryKey: ["workflows"],
    queryFn: () => api.listWorkflows(),
  });

  const { data, isLoading, refetch, isFetching } = useQuery({
    queryKey: ["jobs", statusFilter, docTypeFilter, workflowFilter],
    queryFn: () =>
      api.listJobs({
        status: statusFilter !== "all" ? statusFilter : undefined,
        doc_type: docTypeFilter !== "all" ? docTypeFilter : undefined,
        workflow_id: workflowFilter === "all" ? undefined : workflowFilter,
        limit: 100,
      }),
    // Always refetch when opening Job History (sidebar / nav); keep global staleTime for in-page behavior.
    refetchOnMount: "always",
  });

  const { data: statsSummary } = useQuery({
    queryKey: ["jobs", "stats", "summary"],
    queryFn: () => api.getJobStatsSummary(),
  });

  const deleteMutation = useMutation({
    mutationFn: (jobId: string) => api.deleteJob(jobId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["jobs"] });
      queryClient.invalidateQueries({ queryKey: ["jobs", "stats", "summary"] });
      toast({ title: "Job deleted", description: "The job has been deleted." });
      setDeleteJob(null);
    },
    onError: (error) => {
      toast({
        title: "Delete failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    },
  });

  const jobs = data?.jobs ?? [];

  // Get unique doc types for filter
  const docTypes = useMemo((): string[] => {
    const types = new Set<string>(jobs.map(j => j.doc_type));
    return Array.from(types).sort();
  }, [jobs]);

  // Filter jobs by search query
  const filteredJobs = useMemo(() => {
    if (!searchQuery.trim()) return jobs;
    const query = searchQuery.toLowerCase();
    return jobs.filter(
      (job) =>
        job.document_name.toLowerCase().includes(query) ||
        job.id.toLowerCase().includes(query) ||
        job.doc_type.toLowerCase().includes(query)
    );
  }, [jobs, searchQuery]);

  const totalTablePages = Math.max(1, Math.ceil(filteredJobs.length / JOBS_PAGE_SIZE));
  const pageForSlice = Math.min(tablePage, totalTablePages);

  const paginatedJobs = useMemo(() => {
    const start = (pageForSlice - 1) * JOBS_PAGE_SIZE;
    return filteredJobs.slice(start, start + JOBS_PAGE_SIZE);
  }, [filteredJobs, pageForSlice]);

  const paginationItems = useMemo(
    () => buildPaginationRange(pageForSlice, totalTablePages),
    [pageForSlice, totalTablePages]
  );

  const rangeStart = filteredJobs.length === 0 ? 0 : (pageForSlice - 1) * JOBS_PAGE_SIZE + 1;
  const rangeEnd = Math.min(pageForSlice * JOBS_PAGE_SIZE, filteredJobs.length);

  useEffect(() => {
    setTablePage(1);
  }, [searchQuery, statusFilter, docTypeFilter, workflowFilter]);

  useEffect(() => {
    setTablePage((p) => Math.min(p, totalTablePages));
  }, [totalTablePages]);

  // Calculate stats
  const stats = useMemo(() => {
    const byStatus = statsSummary?.by_status ?? {};
    const totalFromSummary = Object.values(byStatus).reduce((sum, count) => sum + count, 0);
    if (statsSummary) {
      return {
        total: totalFromSummary,
        completed: byStatus.completed ?? 0,
        failed: byStatus.failed ?? 0,
        processing: (byStatus.extracting ?? 0) + (byStatus.analyzing ?? 0) + (byStatus.pending ?? 0),
        totalCost: statsSummary.totals?.estimated_cost ?? 0,
      };
    }

    return {
      total: jobs.length,
      completed: jobs.filter((j) => j.status === "completed").length,
      failed: jobs.filter((j) => j.status === "failed").length,
      processing: jobs.filter((j) => ["extracting", "analyzing", "pending"].includes(j.status)).length,
      totalCost: jobs.reduce((sum, j) => sum + (j.estimated_cost ?? 0), 0),
    };
  }, [jobs, statsSummary]);

  const getStatusIcon = (status: string) => {
    switch (status) {
      case "completed":
        return <CircleCheckIcon size={16} className="text-green-500" />;
      case "failed":
        return <XCircle className="h-4 w-4 text-red-500" />;
      case "extracting":
      case "analyzing":
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />;
      default:
        return <ClockIcon size={16} className="text-muted-foreground" />;
    }
  };

  const getStatusBadge = (status: string) => {
    switch (status) {
      case "completed":
        return <Badge className="bg-green-500/10 text-green-600 border-green-500/20">Completed</Badge>;
      case "failed":
        return <Badge variant="destructive">Failed</Badge>;
      case "extracting":
        return <Badge className="bg-blue-500/10 text-blue-600 border-blue-500/20">Extracting</Badge>;
      case "analyzing":
        return <Badge className="bg-purple-500/10 text-purple-600 border-purple-500/20">Analyzing</Badge>;
      case "pending":
        return <Badge variant="outline">Pending</Badge>;
      case "cancelled":
        return <Badge variant="secondary">Cancelled</Badge>;
      default:
        return <Badge variant="outline">{status}</Badge>;
    }
  };

  const formatDocType = (docType: string) => {
    return docType
      .split("_")
      .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
      .join(" ");
  };

  // Dynamic color palette for document types (excluding green which is used for progress)
  const colorPalette = [
    { bg: "bg-blue-500/10", text: "text-blue-500", border: "border-blue-500/20" },
    { bg: "bg-purple-500/10", text: "text-purple-500", border: "border-purple-500/20" },
    { bg: "bg-orange-500/10", text: "text-orange-500", border: "border-orange-500/20" },
    { bg: "bg-cyan-500/10", text: "text-cyan-500", border: "border-cyan-500/20" },
    { bg: "bg-pink-500/10", text: "text-pink-500", border: "border-pink-500/20" },
    { bg: "bg-amber-500/10", text: "text-amber-500", border: "border-amber-500/20" },
    { bg: "bg-teal-500/10", text: "text-teal-500", border: "border-teal-500/20" },
    { bg: "bg-indigo-500/10", text: "text-indigo-500", border: "border-indigo-500/20" },
    { bg: "bg-rose-500/10", text: "text-rose-500", border: "border-rose-500/20" },
    { bg: "bg-violet-500/10", text: "text-violet-500", border: "border-violet-500/20" },
    { bg: "bg-sky-500/10", text: "text-sky-500", border: "border-sky-500/20" },
    { bg: "bg-fuchsia-500/10", text: "text-fuchsia-500", border: "border-fuchsia-500/20" },
  ];

  // Hash function to get consistent color index for a string
  const getColorIndex = (str: string): number => {
    let hash = 0;
    for (let i = 0; i < str.length; i++) {
      hash = str.charCodeAt(i) + ((hash << 5) - hash);
    }
    return Math.abs(hash) % colorPalette.length;
  };

  const getDocTypeBadge = (docType: string) => {
    const color = colorPalette[getColorIndex(docType.toLowerCase())];

    return (
      <Badge variant="outline" className={`${color.bg} ${color.text} ${color.border}`}>
        {formatDocType(docType)}
      </Badge>
    );
  };

  const togglePartExpanded = (partId: string) => {
    setExpandedParts((prev) => {
      const next = new Set(prev);
      if (next.has(partId)) {
        next.delete(partId);
      } else {
        next.add(partId);
      }
      return next;
    });
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    toast({ title: "Copied", description: "Copied to clipboard" });
  };

  const formatDuration = (startedAt: string | null, completedAt: string | null): string => {
    if (!startedAt) return "-";
    const start = new Date(startedAt);
    const end = completedAt ? new Date(completedAt) : new Date();
    const seconds = Math.floor((end.getTime() - start.getTime()) / 1000);
    if (seconds < 60) return `${seconds}s`;
    const minutes = Math.floor(seconds / 60);
    const remainingSeconds = seconds % 60;
    return `${minutes}m ${remainingSeconds}s`;
  };

  const getProgressColor = (progress: number): string => {
    const percent = progress * 100;
    if (percent >= 100) return "bg-green-500";
    if (percent >= 75) return "bg-emerald-500";
    if (percent >= 50) return "bg-yellow-500";
    if (percent >= 25) return "bg-orange-500";
    return "bg-red-500";
  };

  return (
    <div className="container mx-auto min-w-0 max-w-7xl py-6 px-4">
      {/* Stats Row - Clean professional monochrome design */}
      <div className="grid grid-cols-2 md:grid-cols-5 gap-3 mb-6">
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">{stats.total}</div>
                <p className="text-xs text-muted-foreground">Total Jobs</p>
              </div>
              <LayersIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">{stats.completed}</div>
                <p className="text-xs text-muted-foreground">Completed</p>
              </div>
              <CircleCheckIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">{stats.failed}</div>
                <p className="text-xs text-muted-foreground">Failed</p>
              </div>
              <XCircle className="w-5 h-5 text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">{stats.processing}</div>
                <p className="text-xs text-muted-foreground">Processing</p>
              </div>
              <TrendingUpIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">{formatCost(stats.totalCost)}</div>
                <p className="text-xs text-muted-foreground">Total Cost</p>
              </div>
              <DollarSignIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4">
            <CardTitle className="flex items-center gap-2">
              <HistoryIcon size={20} />
              Job History
            </CardTitle>
            <div className="flex flex-wrap items-center gap-2">
              {/* Search */}
              <div className="relative">
                <SearchIcon size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                <Input
                  placeholder="Search jobs..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="pl-9 w-[200px]"
                />
              </div>

              {/* Filters */}
              <Select value={statusFilter} onValueChange={setStatusFilter}>
                <SelectTrigger className="w-[140px]">
                  <SelectValue placeholder="Status" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Status</SelectItem>
                  <SelectItem value="completed">Completed</SelectItem>
                  <SelectItem value="failed">Failed</SelectItem>
                  <SelectItem value="pending">Pending</SelectItem>
                  <SelectItem value="analyzing">Analyzing</SelectItem>
                  <SelectItem value="extracting">Extracting</SelectItem>
                  <SelectItem value="cancelled">Cancelled</SelectItem>
                </SelectContent>
              </Select>

              <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="Doc Type" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Types</SelectItem>
                  {docTypes.map((type) => (
                    <SelectItem key={type} value={type}>
                      {formatDocType(type)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              <Select value={workflowFilter} onValueChange={setWorkflowFilter}>
                <SelectTrigger className="w-[160px]">
                  <SelectValue placeholder="Workflow" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="all">All Workflows</SelectItem>
                  <SelectItem value="none">No Workflow</SelectItem>
                  {workflows?.map((workflow) => (
                    <SelectItem key={workflow.id} value={workflow.id}>
                      {workflow.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>

              {/* Refresh */}
              <Button
                variant="outline"
                size="icon"
                onClick={() => refetch()}
                disabled={isFetching}
              >
                <RefreshCWIcon size={16} className={cn(isFetching && "animate-spin")} />
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-12">
              <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
            </div>
          ) : filteredJobs.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-16">
              <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
                <FileTextIcon size={32} className="text-muted-foreground" />
              </div>
              <h3 className="text-lg font-semibold mb-1">No jobs found</h3>
              <p className="text-sm text-muted-foreground mb-6 text-center max-w-sm">
                {searchQuery
                  ? "Try a different search term or clear filters"
                  : "Start extracting documents to see your job history here"}
              </p>
              {!searchQuery && (
                <Button onClick={() => window.location.href = "/extract"}>
                  <SparklesIcon size={16} className="mr-2" />
                  Extract Document
                </Button>
              )}
            </div>
          ) : (
            <div className="h-[600px] w-full min-w-0 overflow-auto">
              <div className="min-w-[920px]">
                <table className="w-full min-w-[920px] caption-bottom text-sm">
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-[80px]">Status</TableHead>
                    <TableHead>Document</TableHead>
                    <TableHead className="w-[140px]">Type</TableHead>
                    <TableHead className="w-[180px]">Providers</TableHead>
                    <TableHead className="w-[100px]">Progress</TableHead>
                    <TableHead className="w-[80px]">Duration</TableHead>
                    <TableHead className="w-[80px]">Cost</TableHead>
                    <TableHead className="w-[150px]">Created</TableHead>
                    <TableHead className="w-[100px] text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {paginatedJobs.map((job) => (
                    <TableRow key={job.id}>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          {getStatusIcon(job.status)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div
                          className="max-w-[250px] truncate font-medium"
                          title={job.document_name}
                        >
                          {job.document_name}
                        </div>
                        <div className="text-xs text-muted-foreground">
                          {job.id.slice(0, 8)}...
                        </div>
                      </TableCell>
                      <TableCell>{getDocTypeBadge(job.doc_type)}</TableCell>
                      <TableCell>
                        <div className="text-sm space-y-0.5">
                          <div className="flex items-center gap-1">
                            <span className="text-muted-foreground text-xs">OCR:</span>
                            <span className="truncate">{job.ocr_provider}</span>
                          </div>
                          <div className="flex items-center gap-1">
                            <span className="text-muted-foreground text-xs">LLM:</span>
                            <span className="truncate">{job.llm_provider}</span>
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="space-y-1">
                          <Progress
                            value={job.progress * 100}
                            className="h-2"
                            indicatorClassName={getProgressColor(job.progress)}
                          />
                          <div className="text-xs text-muted-foreground">
                            {Math.round(job.progress * 100)}%
                          </div>
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="text-sm">
                          {formatDuration(job.started_at, job.completed_at)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="text-sm font-medium">
                          {formatCost(job.estimated_cost)}
                        </div>
                      </TableCell>
                      <TableCell>
                        <div className="text-sm">
                          {job.created_at ? formatDate(job.created_at) : "-"}
                        </div>
                      </TableCell>
                      <TableCell className="text-right">
                        <div className="flex items-center justify-end gap-1">
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => router.push(`/jobs/${job.id}`)}
                            title="View results"
                          >
                            <EyeIcon size={16} />
                          </Button>
                          <Button
                            variant="ghost"
                            size="icon"
                            onClick={() => setDeleteJob(job)}
                            disabled={(job.status ?? "").toLowerCase() === "extracting"}
                            title="Delete job"
                          >
                            <Trash2 className="h-4 w-4 text-destructive" />
                          </Button>
                        </div>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
                </table>
              </div>
            </div>
          )}

          {/* Pagination: summary left, page numbers centered in the row */}
          {filteredJobs.length > 0 && (
            <div className="grid grid-cols-1 gap-3 pt-4 border-t sm:grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] sm:items-center">
              <div className="text-sm text-muted-foreground min-w-0">
                Showing {rangeStart}–{rangeEnd} of {filteredJobs.length} jobs
              </div>
              {totalTablePages > 1 && (
                <nav
                  className="flex flex-wrap items-center justify-center gap-1 justify-self-center"
                  aria-label="Job list pages"
                >
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-9 min-w-9 px-2 text-muted-foreground"
                    disabled={pageForSlice <= 1}
                    onClick={() => setTablePage((p) => Math.max(1, p - 1))}
                    aria-label="Previous page"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  {paginationItems.map((item, idx) =>
                    item === "ellipsis" ? (
                      <span
                        key={`e-${idx}`}
                        className="flex h-9 min-w-9 items-center justify-center text-sm text-muted-foreground"
                        aria-hidden
                      >
                        …
                      </span>
                    ) : (
                      <Button
                        key={item}
                        type="button"
                        variant="outline"
                        size="sm"
                        className={cn(
                          "h-9 min-w-9 px-0 font-normal",
                          item === pageForSlice &&
                            "border-primary bg-primary text-primary-foreground hover:bg-primary hover:text-primary-foreground"
                        )}
                        onClick={() => setTablePage(item)}
                        aria-label={`Page ${item}`}
                        aria-current={item === pageForSlice ? "page" : undefined}
                      >
                        {item}
                      </Button>
                    )
                  )}
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-9 min-w-9 px-2 text-muted-foreground"
                    disabled={pageForSlice >= totalTablePages}
                    onClick={() => setTablePage((p) => Math.min(totalTablePages, p + 1))}
                    aria-label="Next page"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </nav>
              )}
            </div>
          )}
        </CardContent>
      </Card>

      {/* Job Details Dialog */}
      <Dialog open={!!selectedJob} onOpenChange={() => setSelectedJob(null)}>
        <DialogContent className="max-w-3xl max-h-[90vh] overflow-hidden flex flex-col">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {selectedJob && getStatusIcon(selectedJob.status)}
              Job Details
            </DialogTitle>
            <DialogDescription className="flex items-center gap-2">
              <span className="truncate max-w-[300px]">{selectedJob?.document_name}</span>
              <Button
                variant="ghost"
                size="sm"
                className="h-6 px-2"
                onClick={() => selectedJob && copyToClipboard(selectedJob.id)}
              >
                <CopyIcon size={12} className="mr-1" />
                {selectedJob?.id.slice(0, 8)}...
              </Button>
            </DialogDescription>
          </DialogHeader>

          {selectedJob && (
            <ScrollArea className="flex-1 -mx-6 px-6">
              <div className="space-y-6 pb-4">
                {/* Status and Info */}
                <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">Status</div>
                    {getStatusBadge(selectedJob.status)}
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">Document Type</div>
                    {getDocTypeBadge(selectedJob.doc_type)}
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">Progress</div>
                    <div className="flex items-center gap-2">
                      <Progress
                        value={selectedJob.progress * 100}
                        className="flex-1 h-2"
                        indicatorClassName={getProgressColor(selectedJob.progress)}
                      />
                      <span className="text-sm">{Math.round(selectedJob.progress * 100)}%</span>
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">OCR Provider</div>
                    <div className="font-medium">{selectedJob.ocr_provider}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">LLM Provider</div>
                    <div className="font-medium">{selectedJob.llm_provider}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">Duration</div>
                    <div className="font-medium">
                      {formatDuration(selectedJob.started_at, selectedJob.completed_at)}
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">Tokens Used</div>
                    <div className="font-medium">
                      {selectedJob.input_tokens.toLocaleString()} in / {selectedJob.output_tokens.toLocaleString()} out
                    </div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">Estimated Cost</div>
                    <div className="font-medium">{formatCost(selectedJob.estimated_cost)}</div>
                  </div>
                  <div>
                    <div className="text-sm text-muted-foreground mb-1">Current Step</div>
                    <div className="font-medium text-sm truncate">
                      {selectedJob.current_step || "-"}
                    </div>
                  </div>
                </div>

                {/* Error */}
                {selectedJob.error && (
                  <div className="p-4 rounded-lg bg-destructive/10 border border-destructive/20">
                    <div className="flex items-center gap-2 font-medium text-destructive">
                      <AlertCircle className="h-4 w-4" />
                      Error
                    </div>
                    <div className="text-sm mt-2 text-destructive/90">
                      {selectedJob.error}
                    </div>
                  </div>
                )}

                {/* Parts */}
                {selectedJob.parts && selectedJob.parts.length > 0 && (
                  <div>
                    <div className="text-sm font-medium mb-3">Parts ({selectedJob.parts.length})</div>
                    <div className="space-y-2">
                      {selectedJob.parts.map((part) => (
                        <Collapsible
                          key={part.part_name}
                          open={expandedParts.has(part.part_name)}
                          onOpenChange={() => togglePartExpanded(part.part_name)}
                        >
                          <div className="border rounded-lg">
                            <CollapsibleTrigger className="flex items-center justify-between w-full p-3 hover:bg-muted/50">
                              <div className="flex items-center gap-3">
                                {expandedParts.has(part.part_name) ? (
                                  <ChevronDownIcon size={16} className="text-muted-foreground" />
                                ) : (
                                  <ChevronRight className="h-4 w-4 text-muted-foreground" />
                                )}
                                <span className="font-medium">{part.part_name}</span>
                                {getStatusBadge(part.status)}
                              </div>
                              <div className="flex items-center gap-4 text-sm text-muted-foreground">
                                {part.confidence > 0 && (
                                  <span>Confidence: {Math.round(part.confidence * 100)}%</span>
                                )}
                                {part.processing_time > 0 && (
                                  <span>{part.processing_time.toFixed(2)}s</span>
                                )}
                              </div>
                            </CollapsibleTrigger>
                            <CollapsibleContent>
                              <div className="p-3 border-t bg-muted/30">
                                {part.error ? (
                                  <div className="text-sm text-destructive">{part.error}</div>
                                ) : part.extracted_data ? (
                                  <div className="relative">
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      className="absolute top-0 right-0"
                                      onClick={() =>
                                        copyToClipboard(JSON.stringify(part.extracted_data, null, 2))
                                      }
                                    >
                                      <CopyIcon size={12} className="mr-1" />
                                      Copy
                                    </Button>
                                    <pre className="text-xs overflow-auto max-h-[300px] p-2 bg-background rounded">
                                      {JSON.stringify(part.extracted_data, null, 2)}
                                    </pre>
                                  </div>
                                ) : (
                                  <div className="text-sm text-muted-foreground">No data</div>
                                )}
                              </div>
                            </CollapsibleContent>
                          </div>
                        </Collapsible>
                      ))}
                    </div>
                  </div>
                )}

                {/* Timestamps */}
                <div className="grid grid-cols-3 gap-4 text-sm">
                  <div>
                    <div className="text-muted-foreground">Created</div>
                    <div>{selectedJob.created_at ? new Date(selectedJob.created_at).toLocaleString() : "-"}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Started</div>
                    <div>{selectedJob.started_at ? new Date(selectedJob.started_at).toLocaleString() : "-"}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Completed</div>
                    <div>{selectedJob.completed_at ? new Date(selectedJob.completed_at).toLocaleString() : "-"}</div>
                  </div>
                </div>
              </div>
            </ScrollArea>
          )}

          <DialogFooter className="mt-4">
            {selectedJob?.status === "failed" && (
              <Button variant="outline">
                <RotateCCWIcon size={16} className="mr-2" />
                Retry
              </Button>
            )}
            {selectedJob?.output_dir && (
              <Button variant="outline">
                <DownloadIcon size={16} className="mr-2" />
                Download Results
              </Button>
            )}
            <Button variant="outline" onClick={() => setSelectedJob(null)}>
              Close
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation Dialog */}
      <AlertDialog open={!!deleteJob} onOpenChange={() => setDeleteJob(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Job?</AlertDialogTitle>
            <AlertDialogDescription>
              Are you sure you want to delete this job? This will also remove all
              extracted data. This action cannot be undone.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteJob && deleteMutation.mutate(deleteJob.id)}
              disabled={deleteMutation.isPending}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending ? (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              ) : (
                <Trash2 className="h-4 w-4 mr-2" />
              )}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
