"use client";

import { useQuery } from "@tanstack/react-query";
import Link from "next/link";
import { api, Job, Schema, ProvidersResponse, Workflow } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { CheckCircle2, XCircle, Clock, Loader2, FileText, Database, Cpu, Brain, Settings2, Upload, Zap, Key, BarChart2, FlaskConical, Layers, Fingerprint, SplitSquareVertical } from "lucide-react";
import { cn } from "@/lib/utils";

// Status badge component for jobs
function StatusBadge({ status }: { status: Job["status"] }) {
  const statusConfig: Record<string, { icon: typeof Clock; className: string; label: string }> = {
    completed: { icon: CheckCircle2, className: "text-green-500", label: "Done" },
    failed: { icon: XCircle, className: "text-red-500", label: "Failed" },
    processing: { icon: Loader2, className: "text-blue-500 animate-spin", label: "Running" },
    pending: { icon: Clock, className: "text-yellow-500", label: "Pending" },
  };

  const config = statusConfig[status] || { icon: Clock, className: "text-muted-foreground", label: status };
  const Icon = config.icon;

  return (
    <span className={cn("flex items-center gap-1", config.className)}>
      <Icon className="w-3 h-3" />
    </span>
  );
}

// Jobs hover content
export function JobsHoverContent() {
  const { data, isLoading } = useQuery({
    queryKey: ["recentJobs"],
    queryFn: () => api.listJobs({ limit: 6 }),
    staleTime: 30000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const jobs = data?.jobs || [];

  return (
    <div className="space-y-1">
      <div className="font-semibold text-sm mb-3">Recent Jobs</div>
      {jobs.length === 0 ? (
        <p className="text-xs text-muted-foreground py-2">No jobs yet</p>
      ) : (
        <>
          {jobs.map((job) => (
            <Link
              key={job.id}
              href={`/jobs?job=${job.id}`}
              className="flex items-center gap-2 py-1.5 px-2 -mx-2 rounded-md hover:bg-muted/50 transition-colors group"
            >
              <StatusBadge status={job.status} />
              <span className="flex-1 text-xs truncate text-muted-foreground group-hover:text-foreground transition-colors">
                {job.document_name}
              </span>
            </Link>
          ))}
          <Link
            href="/jobs"
            className="block text-xs text-primary hover:underline pt-2 mt-1 border-t"
          >
            See all jobs
          </Link>
        </>
      )}
    </div>
  );
}

// Schemas hover content
export function SchemasHoverContent() {
  const { data: schemas, isLoading } = useQuery({
    queryKey: ["sidebarSchemas"],
    queryFn: () => api.listSchemas(),
    staleTime: 60000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const activeSchemas = schemas?.filter(s => s.is_active && s.status === "published") || [];
  const mySchemas = schemas?.filter(s => !s.is_default) || [];

  return (
    <div className="space-y-1">
      <div className="font-semibold text-sm mb-3">Schemas</div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="text-center p-2 bg-muted/50 rounded-md">
          <div className="text-lg font-semibold">{activeSchemas.length}</div>
          <div className="text-[10px] text-muted-foreground">Active</div>
        </div>
        <div className="text-center p-2 bg-muted/50 rounded-md">
          <div className="text-lg font-semibold">{mySchemas.length}</div>
          <div className="text-[10px] text-muted-foreground">Custom</div>
        </div>
      </div>
      {activeSchemas.slice(0, 4).map((schema) => (
        <Link
          key={schema.id}
          href={`/schemas?schema=${schema.id}`}
          className="flex items-center gap-2 py-1.5 px-2 -mx-2 rounded-md hover:bg-muted/50 transition-colors group"
        >
          <Database className="w-3 h-3 text-muted-foreground" />
          <span className="flex-1 text-xs truncate text-muted-foreground group-hover:text-foreground transition-colors">
            {schema.name}
          </span>
          {schema.is_default && (
            <Badge variant="secondary" className="text-[9px] px-1 py-0 h-4">
              Default
            </Badge>
          )}
        </Link>
      ))}
      <Link
        href="/schemas"
        className="block text-xs text-primary hover:underline pt-2 mt-1 border-t"
      >
        Manage schemas
      </Link>
    </div>
  );
}

// Providers hover content
export function ProvidersHoverContent() {
  const { data, isLoading } = useQuery({
    queryKey: ["sidebarProviders"],
    queryFn: () => api.getProviders(),
    staleTime: 60000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const ocrCount = data?.ocr_providers?.filter(p => p.is_available).length || 0;
  const llmCount = data?.llm_providers?.filter(p => p.is_available).length || 0;

  return (
    <div className="space-y-1">
      <div className="font-semibold text-sm mb-3">Providers</div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="text-center p-2 bg-muted/50 rounded-md">
          <div className="flex items-center justify-center gap-1.5 mb-1">
            <Cpu className="w-3.5 h-3.5 text-blue-500" />
            <span className="text-lg font-semibold">{ocrCount}</span>
          </div>
          <div className="text-[10px] text-muted-foreground">OCR</div>
        </div>
        <div className="text-center p-2 bg-muted/50 rounded-md">
          <div className="flex items-center justify-center gap-1.5 mb-1">
            <Brain className="w-3.5 h-3.5 text-purple-500" />
            <span className="text-lg font-semibold">{llmCount}</span>
          </div>
          <div className="text-[10px] text-muted-foreground">LLM</div>
        </div>
      </div>
      <div className="space-y-1">
        {data?.ocr_providers?.filter(p => p.is_available).slice(0, 2).map((p) => (
          <div key={p.name} className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
            <span className="truncate">{p.display_name}</span>
            <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 ml-auto">OCR</Badge>
          </div>
        ))}
        {data?.llm_providers?.filter(p => p.is_available).slice(0, 2).map((p) => (
          <div key={p.name} className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
            <span className="w-1.5 h-1.5 rounded-full bg-green-500" />
            <span className="truncate">{p.display_name}</span>
            <Badge variant="outline" className="text-[9px] px-1 py-0 h-4 ml-auto">LLM</Badge>
          </div>
        ))}
      </div>
      <Link
        href="/providers"
        className="block text-xs text-primary hover:underline pt-2 mt-1 border-t"
      >
        Configure providers
      </Link>
    </div>
  );
}

// Settings hover content
export function SettingsHoverContent() {
  const { data, isLoading } = useQuery({
    queryKey: ["sidebarSettings"],
    queryFn: () => api.getSettings(),
    staleTime: 60000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const settings = data?.settings;

  return (
    <div className="space-y-1">
      <div className="font-semibold text-sm mb-3">Quick Settings</div>
      <div className="space-y-2 text-xs">
        <div className="flex items-center justify-between py-1">
          <span className="text-muted-foreground">Default OCR</span>
          <Badge variant="secondary" className="text-[10px]">
            {settings?.default_ocr_provider || "Auto"}
          </Badge>
        </div>
        <div className="flex items-center justify-between py-1">
          <span className="text-muted-foreground">Default LLM</span>
          <Badge variant="secondary" className="text-[10px]">
            {settings?.default_llm_provider || "Auto"}
          </Badge>
        </div>
        <div className="flex items-center justify-between py-1">
          <span className="text-muted-foreground">Auto-detect Type</span>
          <Badge variant={settings?.auto_detect_document_type ? "default" : "outline"} className="text-[10px]">
            {settings?.auto_detect_document_type ? "On" : "Off"}
          </Badge>
        </div>
        <div className="flex items-center justify-between py-1">
          <span className="text-muted-foreground">Consensus</span>
          <Badge variant={settings?.consensus_enabled ? "default" : "outline"} className="text-[10px]">
            {settings?.consensus_enabled ? "On" : "Off"}
          </Badge>
        </div>
      </div>
      <Link
        href="/settings"
        className="block text-xs text-primary hover:underline pt-2 mt-1 border-t"
      >
        All settings
      </Link>
    </div>
  );
}

// Extract hover content
export function ExtractHoverContent() {
  const formats = ["PDF", "PNG", "JPG", "TIFF", "WEBP", "HEIC"];
  const docTypes = ["Invoices", "Receipts", "Contracts", "Bank Statements", "Tax Forms"];

  return (
    <div className="space-y-1">
      <div className="font-semibold text-sm mb-3">Document Extraction</div>
      <div className="space-y-3">
        <div>
          <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">
            Supported Formats
          </div>
          <div className="flex flex-wrap gap-1">
            {formats.map((f) => (
              <Badge key={f} variant="outline" className="text-[10px] px-1.5 py-0">
                {f}
              </Badge>
            ))}
          </div>
        </div>
        <div>
          <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-1.5">
            Document Types
          </div>
          <div className="flex flex-wrap gap-1">
            {docTypes.map((d) => (
              <Badge key={d} variant="secondary" className="text-[10px] px-1.5 py-0">
                {d}
              </Badge>
            ))}
          </div>
        </div>
      </div>
      <Link
        href="/extract"
        className="block text-xs text-primary hover:underline pt-2 mt-1 border-t"
      >
        Start extraction
      </Link>
    </div>
  );
}

// Admin hover content
export function AdminHoverContent() {
  const { data: pendingSchemas, isLoading: schemasLoading } = useQuery({
    queryKey: ["pendingSchemas"],
    queryFn: () => api.getPendingSchemas(),
    staleTime: 30000,
  });

  const { data: pendingWorkflows, isLoading: workflowsLoading } = useQuery({
    queryKey: ["admin", "pendingWorkflows"],
    queryFn: () => api.getPendingWorkflows(),
    staleTime: 30000,
  });

  if (schemasLoading || workflowsLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const schemaCount = pendingSchemas?.length || 0;
  const workflowCount = pendingWorkflows?.length || 0;

  return (
    <div className="space-y-1">
      <div className="font-semibold text-sm mb-3">Admin Dashboard</div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="text-center p-2 bg-muted/50 rounded-md">
          <div className="flex items-center justify-center gap-1.5 mb-1">
            <Database className="w-3.5 h-3.5 text-yellow-500" />
            <span className="text-lg font-semibold">{schemaCount}</span>
          </div>
          <div className="text-[10px] text-muted-foreground">Schemas</div>
        </div>
        <div className="text-center p-2 bg-muted/50 rounded-md">
          <div className="flex items-center justify-center gap-1.5 mb-1">
            <Zap className="w-3.5 h-3.5 text-yellow-500" />
            <span className="text-lg font-semibold">{workflowCount}</span>
          </div>
          <div className="text-[10px] text-muted-foreground">Workflows</div>
        </div>
      </div>
      {(schemaCount > 0 || workflowCount > 0) && (
        <div className="space-y-1">
          {pendingSchemas?.slice(0, 2).map((schema) => (
            <div key={schema.id} className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
              <Clock className="w-3 h-3 text-yellow-500" />
              <Database className="w-3 h-3" />
              <span className="truncate">{schema.name}</span>
            </div>
          ))}
          {pendingWorkflows?.slice(0, 2).map((workflow) => (
            <div key={workflow.id} className="flex items-center gap-2 py-1 text-xs text-muted-foreground">
              <Clock className="w-3 h-3 text-yellow-500" />
              <Zap className="w-3 h-3" />
              <span className="truncate">{workflow.name}</span>
            </div>
          ))}
        </div>
      )}
      <Link
        href="/admin"
        className="block text-xs text-primary hover:underline pt-2 mt-1 border-t"
      >
        Review submissions
      </Link>
    </div>
  );
}

// Workflows hover content
export function WorkflowsHoverContent() {
  const { data: workflows, isLoading } = useQuery({
    queryKey: ["sidebarWorkflows"],
    queryFn: () => api.listWorkflows({ limit: 5 }),
    staleTime: 30000,
  });

  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-4">
        <Loader2 className="w-4 h-4 animate-spin text-muted-foreground" />
      </div>
    );
  }

  const activeWorkflows = workflows?.filter(w => w.status === "active") || [];

  return (
    <div className="space-y-1">
      <div className="font-semibold text-sm mb-3">Workflow APIs</div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="text-center p-2 bg-muted/50 rounded-md">
          <div className="flex items-center justify-center gap-1.5 mb-1">
            <Zap className="w-3.5 h-3.5 text-green-500" />
            <span className="text-lg font-semibold">{activeWorkflows.length}</span>
          </div>
          <div className="text-[10px] text-muted-foreground">Active</div>
        </div>
        <div className="text-center p-2 bg-muted/50 rounded-md">
          <div className="flex items-center justify-center gap-1.5 mb-1">
            <Key className="w-3.5 h-3.5 text-blue-500" />
            <span className="text-lg font-semibold">{workflows?.length || 0}</span>
          </div>
          <div className="text-[10px] text-muted-foreground">Total</div>
        </div>
      </div>
      {activeWorkflows.length === 0 ? (
        <p className="text-xs text-muted-foreground py-2">No workflows yet</p>
      ) : (
        <div className="space-y-1">
          {activeWorkflows.slice(0, 4).map((workflow) => (
            <Link
              key={workflow.id}
              href={`/workflows/${workflow.id}`}
              className="flex items-center gap-2 py-1.5 px-2 -mx-2 rounded-md hover:bg-muted/50 transition-colors group"
            >
              <Zap className="w-3 h-3 text-green-500" />
              <span className="flex-1 text-xs truncate text-muted-foreground group-hover:text-foreground transition-colors">
                {workflow.name}
              </span>
              <Badge variant="outline" className="text-[9px] px-1 py-0 h-4">
                {workflow.slug}
              </Badge>
            </Link>
          ))}
        </div>
      )}
      <Link
        href="/workflows"
        className="block text-xs text-primary hover:underline pt-2 mt-1 border-t"
      >
        Manage workflows
      </Link>
    </div>
  );
}

// Segmentation Lab hover content
export function LabHoverContent() {
  const approaches = [
    { icon: Layers, name: "Heuristics", desc: "Pattern-based detection" },
    { icon: Fingerprint, name: "SimHash", desc: "Document fingerprinting" },
    { icon: SplitSquareVertical, name: "ML Similarity", desc: "TF-IDF & MiniLM" },
  ];

  return (
    <div className="space-y-1">
      <div className="font-semibold text-sm mb-3">Segmentation Lab</div>
      <p className="text-xs text-muted-foreground mb-3">
        Test and compare document segmentation approaches in real-time.
      </p>
      <div className="space-y-2 mb-3">
        {approaches.map(({ icon: Icon, name, desc }) => (
          <div key={name} className="flex items-center gap-2 py-1.5 px-2 -mx-2 rounded-md bg-muted/30">
            <Icon className="w-3.5 h-3.5 text-purple-500" />
            <div className="flex-1">
              <span className="text-xs font-medium">{name}</span>
              <span className="text-[10px] text-muted-foreground ml-1.5">{desc}</span>
            </div>
          </div>
        ))}
      </div>
      <div className="grid grid-cols-2 gap-2 mb-3">
        <div className="text-center p-2 bg-purple-50 dark:bg-purple-950/30 rounded-md border border-purple-200 dark:border-purple-800">
          <FlaskConical className="w-4 h-4 text-purple-500 mx-auto mb-1" />
          <div className="text-[10px] text-purple-700 dark:text-purple-300">Test Documents</div>
        </div>
        <div className="text-center p-2 bg-purple-50 dark:bg-purple-950/30 rounded-md border border-purple-200 dark:border-purple-800">
          <Database className="w-4 h-4 text-purple-500 mx-auto mb-1" />
          <div className="text-[10px] text-purple-700 dark:text-purple-300">Manage Profiles</div>
        </div>
      </div>
      <Link
        href="/lab/segmentation"
        className="block text-xs text-primary hover:underline pt-2 mt-1 border-t"
      >
        Open Lab
      </Link>
    </div>
  );
}
