"use client";

import { useState, useMemo } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { api, WorkflowUsageSummary, WorkflowUsageLog, WorkflowUsageChartData } from "@/lib/api";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  BarChart2,
  Loader2,
  CheckCircle2,
  XCircle,
  TrendingUp,
  TrendingDown,
  Clock,
  Zap,
  DollarSign,
  Activity,
  Settings,
  Key,
  Terminal,
  X,
  PauseCircle,
  Archive,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { formatRelativeTime, isWorkflowAccessDeniedError } from "@/lib/utils";

/** Matches backend `get_usage_summary` date range (UTC). */
function getUsagePeriodStartDate(period: "today" | "week" | "month" | "all"): Date | null {
  const now = new Date();
  if (period === "all") return null;
  if (period === "today") {
    return new Date(Date.UTC(now.getUTCFullYear(), now.getUTCMonth(), now.getUTCDate(), 0, 0, 0, 0));
  }
  if (period === "week") {
    return new Date(now.getTime() - 7 * 24 * 60 * 60 * 1000);
  }
  if (period === "month") {
    return new Date(now.getTime() - 30 * 24 * 60 * 60 * 1000);
  }
  return null;
}

export default function WorkflowUsagePage() {
  const params = useParams();
  const workflowId = params.id as string;

  const [period, setPeriod] = useState<"today" | "week" | "month" | "all">("week");

  // Fetch workflow
  const { data: workflow, isLoading: wfLoading, isError: wfError, error: wfErr } = useQuery({
    queryKey: ["workflow", workflowId],
    queryFn: () => api.getWorkflow(workflowId),
  });

  // Fetch usage summary
  const { data: summary, isLoading: summaryLoading } = useQuery({
    queryKey: ["workflowUsage", workflowId, period],
    queryFn: () => api.getWorkflowUsage(workflowId, period),
    enabled: !!workflow,
  });

  // Fetch usage logs
  const { data: logsData, isLoading: logsLoading } = useQuery({
    queryKey: ["workflowUsageLogs", workflowId],
    queryFn: () => api.getWorkflowUsageLogs(workflowId, { limit: 50 }),
    enabled: !!workflow,
  });

  // Fetch chart data
  const { data: chartData } = useQuery({
    queryKey: ["workflowUsageChart", workflowId],
    queryFn: () => api.getWorkflowUsageChart(workflowId, 7),
    enabled: !!workflow,
  });

  const successRate = summary
    ? summary.total_requests > 0
      ? ((summary.successful_requests / summary.total_requests) * 100).toFixed(1)
      : "0"
    : "0";

  const filteredLogs = useMemo(() => {
    const logs = logsData?.logs ?? [];
    const start = getUsagePeriodStartDate(period);
    if (!start) return logs;
    const startMs = start.getTime();
    return logs.filter((log) => {
      if (!log.created_at) return false;
      return new Date(log.created_at).getTime() >= startMs;
    });
  }, [logsData?.logs, period]);

  const recentLogsCount = filteredLogs.length;

  const getStatusBadge = (status: string) => {
    const config: Record<string, { variant: "default" | "secondary" | "outline"; icon: typeof CheckCircle2; className: string }> = {
      active: { variant: "default", icon: CheckCircle2, className: "bg-green-500" },
      inactive: { variant: "secondary", icon: PauseCircle, className: "" },
      archived: { variant: "outline", icon: Archive, className: "" },
    };
    const { variant, icon: Icon, className } = config[status] || config.inactive;
    return (
      <Badge variant={variant} className={className}>
        <Icon className="w-3 h-3 mr-1" />
        {status.charAt(0).toUpperCase() + status.slice(1)}
      </Badge>
    );
  };

  if (wfLoading) {
    return (
      <div className="flex items-center justify-center py-12">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (wfError && isWorkflowAccessDeniedError(wfErr)) {
    return (
      <div className="container mx-auto py-6">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12 max-w-md mx-auto text-center">
            <h3 className="text-lg font-semibold mb-2">Access denied</h3>
            <p className="text-sm text-muted-foreground mb-6">
              You do not have permission to view usage analytics for this workflow.
            </p>
            <Link href="/workflows">
              <Button variant="outline">Back to Workflows</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  if (wfError || !workflow) {
    return (
      <div className="container mx-auto py-6">
        <Card>
          <CardContent className="flex flex-col items-center justify-center py-12">
            <h3 className="text-lg font-semibold mb-2">Workflow not found</h3>
            {wfErr instanceof Error && (
              <p className="text-sm text-muted-foreground mb-4 text-center max-w-md">{wfErr.message}</p>
            )}
            <Link href="/workflows">
              <Button variant="outline">Back to Workflows</Button>
            </Link>
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 px-4 max-w-6xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6 pb-4 border-b">
        <div className="flex items-center gap-3">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-bold tracking-tight">{workflow?.name || "Workflow"}</h1>
              {workflow?.status && getStatusBadge(workflow.status)}
            </div>
            <code className="text-xs text-muted-foreground">
              /{workflow?.slug || ""}
            </code>
          </div>
        </div>

        <div className="flex items-center gap-1">
          <Select value={period} onValueChange={(v) => setPeriod(v as typeof period)}>
            <SelectTrigger className="w-32 mr-2">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="today">Today</SelectItem>
              <SelectItem value="week">Last 7 days</SelectItem>
              <SelectItem value="month">Last 30 days</SelectItem>
              <SelectItem value="all">All time</SelectItem>
            </SelectContent>
          </Select>
          <Link href={`/workflows/${workflowId}`}>
            <Button variant="ghost" size="icon" className="h-9 w-9" title="API Reference">
              <Terminal className="w-4 h-4" />
            </Button>
          </Link>
          <Link href={`/workflows/${workflowId}?tab=settings`}>
            <Button variant="ghost" size="icon" className="h-9 w-9" title="Settings">
              <Settings className="w-4 h-4" />
            </Button>
          </Link>
          <Link href={`/workflows/${workflowId}/keys`}>
            <Button variant="ghost" size="icon" className="h-9 w-9" title="API Keys">
              <Key className="w-4 h-4" />
            </Button>
          </Link>
          <Button variant="secondary" size="icon" className="h-9 w-9" title="Usage Analytics">
            <BarChart2 className="w-4 h-4" />
          </Button>
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

      {/* Summary Cards */}
      <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-4 mb-6">
        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <Activity className="w-4 h-4" />
              Total Requests
            </CardDescription>
          </CardHeader>
          <CardContent>
            {summaryLoading ? (
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            ) : (
              <div className="text-3xl font-bold">
                {summary?.total_requests.toLocaleString() || 0}
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <CheckCircle2 className="w-4 h-4 text-green-500" />
              Success Rate
            </CardDescription>
          </CardHeader>
          <CardContent>
            {summaryLoading ? (
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            ) : (
              <div className="flex items-baseline gap-2">
                <span className="text-3xl font-bold">{successRate}%</span>
                <span className="text-sm text-muted-foreground">
                  ({summary?.successful_requests || 0} / {summary?.total_requests || 0})
                </span>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <Clock className="w-4 h-4" />
              Avg Response Time
            </CardDescription>
          </CardHeader>
          <CardContent>
            {summaryLoading ? (
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            ) : (
              <div className="text-3xl font-bold">
                {(summary?.avg_response_time_ms || 0).toFixed(0)}
                <span className="text-lg font-normal text-muted-foreground ml-1">ms</span>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="pb-2">
            <CardDescription className="flex items-center gap-2">
              <DollarSign className="w-4 h-4" />
              Estimated Cost
            </CardDescription>
          </CardHeader>
          <CardContent>
            {summaryLoading ? (
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            ) : (
              <div className="text-3xl font-bold">
                ${(summary?.total_cost || 0).toFixed(2)}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Token Usage */}
      <div className="grid gap-4 md:grid-cols-2 mb-6">
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Token Usage</CardTitle>
          </CardHeader>
          <CardContent>
            {summaryLoading ? (
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Input Tokens</span>
                  <span className="font-mono font-medium">
                    {(summary?.total_input_tokens || 0).toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="text-muted-foreground">Output Tokens</span>
                  <span className="font-mono font-medium">
                    {(summary?.total_output_tokens || 0).toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between pt-2 border-t">
                  <span className="text-muted-foreground">Total Tokens</span>
                  <span className="font-mono font-bold">
                    {(
                      (summary?.total_input_tokens || 0) +
                      (summary?.total_output_tokens || 0)
                    ).toLocaleString()}
                  </span>
                </div>
              </div>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Request Breakdown</CardTitle>
          </CardHeader>
          <CardContent>
            {summaryLoading ? (
              <Loader2 className="w-5 h-5 animate-spin text-muted-foreground" />
            ) : (
              <div className="space-y-4">
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <CheckCircle2 className="w-4 h-4 text-green-500" />
                    Successful
                  </span>
                  <span className="font-mono font-medium text-green-600 dark:text-green-400">
                    {(summary?.successful_requests || 0).toLocaleString()}
                  </span>
                </div>
                <div className="flex items-center justify-between">
                  <span className="flex items-center gap-2">
                    <XCircle className="w-4 h-4 text-red-500" />
                    Failed
                  </span>
                  <span className="font-mono font-medium text-red-600 dark:text-red-400">
                    {(summary?.failed_requests || 0).toLocaleString()}
                  </span>
                </div>
                {/* Progress bar */}
                <div className="pt-2">
                  <div className="h-2 bg-muted rounded-full overflow-hidden">
                    <div
                      className="h-full bg-green-500"
                      style={{
                        width: `${summary?.total_requests ? (summary.successful_requests / summary.total_requests) * 100 : 0}%`,
                      }}
                    />
                  </div>
                </div>
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Recent Requests */}
      <Card>
        <CardHeader>
          <CardTitle className="text-lg">Recent Requests</CardTitle>
          <CardDescription>
            {!logsLoading && recentLogsCount > 0
              ? `Last ${recentLogsCount.toLocaleString()} API requests to this workflow`
              : ""}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {logsLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : !logsData?.logs || logsData.logs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <BarChart2 className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No requests yet</p>
            </div>
          ) : filteredLogs.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <BarChart2 className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No requests in the selected period</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Status</TableHead>
                  <TableHead>Document</TableHead>
                  <TableHead>Response Time</TableHead>
                  <TableHead>Tokens</TableHead>
                  <TableHead>Cost</TableHead>
                  <TableHead>Time</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {filteredLogs.map((log) => (
                  <TableRow key={log.id}>
                    <TableCell>
                      {log.success ? (
                        <Badge className="bg-green-500">
                          <CheckCircle2 className="w-3 h-3 mr-1" />
                          {log.status_code}
                        </Badge>
                      ) : (
                        <Badge variant="destructive">
                          <XCircle className="w-3 h-3 mr-1" />
                          {log.status_code}
                        </Badge>
                      )}
                    </TableCell>
                    <TableCell className="max-w-[200px] truncate">
                      {log.document_name || "-"}
                    </TableCell>
                    <TableCell>
                      {log.response_time_ms.toFixed(0)} ms
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      {(log.input_tokens + log.output_tokens).toLocaleString()}
                    </TableCell>
                    <TableCell className="font-mono text-sm">
                      ${log.estimated_cost.toFixed(4)}
                    </TableCell>
                    <TableCell className="text-muted-foreground">
                      {log.created_at
                        ? formatRelativeTime(log.created_at)
                        : "-"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
