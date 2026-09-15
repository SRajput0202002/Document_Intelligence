"use client";

import { useState } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { api, WorkflowApiKey } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
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
  AlertDialogTrigger,
} from "@/components/ui/alert-dialog";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import {
  Key,
  Plus,
  Copy,
  Trash2,
  RotateCcw,
  Loader2,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Eye,
  EyeOff,
  Settings,
  BarChart2,
  Terminal,
  X,
  PauseCircle,
  Archive,
} from "lucide-react";
import { toast } from "@/components/ui/toast";
import { formatRelativeTime, isWorkflowAccessDeniedError } from "@/lib/utils";
import { CopyButton } from "@/components/ui/copy-button";

const MASKED_API_KEY = "••••••••••••••••••••••••••••••••";

export default function WorkflowKeysPage() {
  const params = useParams();
  const queryClient = useQueryClient();
  const workflowId = params.id as string;

  const [createDialogOpen, setCreateDialogOpen] = useState(false);
  const [newKeyName, setNewKeyName] = useState("");
  const [newKeyExpires, setNewKeyExpires] = useState<number | undefined>();
  const [newlyCreatedKey, setNewlyCreatedKey] = useState<string | null>(null);
  const [showNewKey, setShowNewKey] = useState(true);
  const [revealedKeys, setRevealedKeys] = useState<Record<string, string>>({});
  const [revealingKeyId, setRevealingKeyId] = useState<string | null>(null);

  // Fetch workflow
  const { data: workflow, isLoading: wfLoading, isError: wfError, error: wfErr } = useQuery({
    queryKey: ["workflow", workflowId],
    queryFn: () => api.getWorkflow(workflowId),
  });

  // Fetch API keys
  const { data: keys, isLoading } = useQuery({
    queryKey: ["workflowKeys", workflowId],
    queryFn: () => api.listApiKeys(workflowId, true),
    enabled: !!workflow,
  });

  // Create key mutation
  const createMutation = useMutation({
    mutationFn: () => api.createApiKey(workflowId, newKeyName, newKeyExpires),
    onSuccess: (data) => {
      if (data.key) {
        setNewlyCreatedKey(data.key);
      }
      queryClient.invalidateQueries({ queryKey: ["workflowKeys", workflowId] });
      toast.success("API key created");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to create API key");
    },
  });

  // Revoke key mutation
  const revokeMutation = useMutation({
    mutationFn: (keyId: string) => api.revokeApiKey(workflowId, keyId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["workflowKeys", workflowId] });
      toast.success("API key revoked");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to revoke API key");
    },
  });

  // Rotate key mutation
  const rotateMutation = useMutation({
    mutationFn: (keyId: string) => api.rotateApiKey(workflowId, keyId),
    onSuccess: (data) => {
      if (data.key) {
        setNewlyCreatedKey(data.key);
        setCreateDialogOpen(true);
      }
      queryClient.invalidateQueries({ queryKey: ["workflowKeys", workflowId] });
      toast.success("API key rotated");
    },
    onError: (error: Error) => {
      toast.error(error.message || "Failed to rotate API key");
    },
  });

  const handleCreateKey = () => {
    if (!newKeyName.trim()) {
      toast.error("Please enter a name for the API key");
      return;
    }
    createMutation.mutate();
  };

  const copyKey = (key: string) => {
    navigator.clipboard.writeText(key);
    toast.success("API key copied to clipboard");
  };

  const handleRevealKey = async (keyId: string) => {
    if (revealedKeys[keyId]) {
      // Key is already revealed, toggle visibility
      setRevealedKeys((prev) => {
        const updated = { ...prev };
        delete updated[keyId];
        return updated;
      });
      return;
    }

    setRevealingKeyId(keyId);
    try {
      const result = await api.revealApiKey(workflowId, keyId);
      setRevealedKeys((prev) => ({ ...prev, [keyId]: result.key }));
    } catch (error: unknown) {
      const message = error instanceof Error ? error.message : "Failed to reveal API key";
      toast.error(message);
    } finally {
      setRevealingKeyId(null);
    }
  };

  const resetCreateDialog = () => {
    setNewKeyName("");
    setNewKeyExpires(undefined);
    setNewlyCreatedKey(null);
    setShowNewKey(true);
  };

  /** Radix may not call `onOpenChange(false)` when `open` is set from a plain Button; always reset when closing explicitly. */
  const closeCreateDialog = () => {
    resetCreateDialog();
    setCreateDialogOpen(false);
  };

  const activeKeys = keys?.filter((k) => k.is_active) || [];
  const revokedKeys = keys?.filter((k) => !k.is_active) || [];

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

  const formatExpiresInDays = (expiresAt?: string) => {
    if (!expiresAt) return "Never";

    const expiresDate = new Date(expiresAt);
    if (Number.isNaN(expiresDate.getTime())) return "Never";

    const diffMs = expiresDate.getTime() - Date.now();
    if (diffMs <= 0) return "Expired";

    const daysRemaining = Math.ceil(diffMs / (1000 * 60 * 60 * 24));
    return `${daysRemaining} day${daysRemaining === 1 ? "" : "s"}`;
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
              You do not have permission to manage API keys for this workflow.
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
    <div className="container mx-auto py-6 px-4 max-w-4xl">
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
          <Button variant="secondary" size="icon" className="h-9 w-9" title="API Keys">
            <Key className="w-4 h-4" />
          </Button>
          <Link href={`/workflows/${workflowId}/usage`}>
            <Button variant="ghost" size="icon" className="h-9 w-9" title="Usage Analytics">
              <BarChart2 className="w-4 h-4" />
            </Button>
          </Link>
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

      <div className="flex items-center justify-end mb-6">
          <Dialog
            open={createDialogOpen}
            onOpenChange={(open) => {
              setCreateDialogOpen(open);
              if (!open) resetCreateDialog();
            }}
          >
            <DialogTrigger asChild>
              <Button>
                <Plus className="w-4 h-4 mr-2" />
                Create API Key
              </Button>
            </DialogTrigger>
            <DialogContent>
              {newlyCreatedKey ? (
                <>
                  <DialogHeader>
                    <DialogTitle>API Key Created</DialogTitle>
                    <DialogDescription>
                      You may copy your API key now!
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div className="flex items-center gap-2 p-3 bg-muted rounded-lg">
                      <code className="flex-1 text-sm break-all">
                        {showNewKey ? newlyCreatedKey : "••••••••••••••••••••••••••••••••"}
                      </code>
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setShowNewKey(!showNewKey)}
                      >
                        {showNewKey ? <EyeOff className="w-4 h-4" /> : <Eye className="w-4 h-4" />}
                      </Button>
                      <CopyButton value={newlyCreatedKey} />
                    </div>
                  </div>
                  <DialogFooter>
                    <Button onClick={closeCreateDialog}>Done</Button>
                  </DialogFooter>
                </>
              ) : (
                <>
                  <DialogHeader>
                    <DialogTitle>Create API Key</DialogTitle>
                    <DialogDescription>
                      Create a new API key to authenticate requests to this workflow
                    </DialogDescription>
                  </DialogHeader>
                  <div className="space-y-4">
                    <div className="space-y-2">
                      <Label htmlFor="keyName">
                        Key Name <span className="text-destructive">*</span>
                      </Label>
                      <Input
                        id="keyName"
                        placeholder="e.g., Production, Testing, Mobile App"
                        value={newKeyName}
                        onChange={(e) => setNewKeyName(e.target.value)}
                      />
                    </div>
                    <div className="space-y-2">
                      <Label htmlFor="expires">Expires In (days)</Label>
                      <Input
                        id="expires"
                        type="number"
                        placeholder="Leave empty for no expiration"
                        min={1}
                        max={365}
                        value={newKeyExpires || ""}
                        onChange={(e) => setNewKeyExpires(e.target.value ? parseInt(e.target.value) : undefined)}
                      />
                      <p className="text-xs text-muted-foreground">
                        Optional. Leave empty for a key that never expires.
                      </p>
                    </div>
                  </div>
                  <DialogFooter>
                    <Button variant="outline" onClick={closeCreateDialog}>
                      Cancel
                    </Button>
                    <Button onClick={handleCreateKey} disabled={createMutation.isPending}>
                      {createMutation.isPending ? (
                        <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                      ) : (
                        <Key className="w-4 h-4 mr-2" />
                      )}
                      Create Key
                    </Button>
                  </DialogFooter>
                </>
              )}
            </DialogContent>
          </Dialog>
      </div>

      {/* Active Keys */}
      <Card className="mb-6">
        <CardHeader>
          <CardTitle className="text-lg">Active Keys</CardTitle>
          <CardDescription>
            These keys can be used to authenticate API requests
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading ? (
            <div className="flex items-center justify-center py-8">
              <Loader2 className="w-6 h-6 animate-spin text-muted-foreground" />
            </div>
          ) : activeKeys.length === 0 ? (
            <div className="text-center py-8 text-muted-foreground">
              <Key className="w-12 h-12 mx-auto mb-4 opacity-50" />
              <p>No active API keys</p>
              <p className="text-sm">Create a key to start making API requests</p>
            </div>
          ) : (
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Key</TableHead>
                  <TableHead>Usage</TableHead>
                  <TableHead>Last Used</TableHead>
                  <TableHead>Expires</TableHead>
                  <TableHead className="text-right">Actions</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {activeKeys.map((key) => (
                  <TableRow key={key.id}>
                    <TableCell className="font-medium">{key.name}</TableCell>
                    <TableCell>
                      <div className="flex items-center gap-2">
                        <code className="text-xs bg-muted px-2 py-1 rounded font-mono">
                          {revealedKeys[key.id] ? revealedKeys[key.id] : MASKED_API_KEY}
                        </code>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7"
                          onClick={() => handleRevealKey(key.id)}
                          disabled={revealingKeyId === key.id}
                          title={revealedKeys[key.id] ? "Hide key" : "Show key"}
                        >
                          {revealingKeyId === key.id ? (
                            <Loader2 className="w-3.5 h-3.5 animate-spin" />
                          ) : revealedKeys[key.id] ? (
                            <EyeOff className="w-3.5 h-3.5" />
                          ) : (
                            <Eye className="w-3.5 h-3.5" />
                          )}
                        </Button>
                        {revealedKeys[key.id] && (
                          <Button
                            variant="ghost"
                            size="icon"
                            className="h-7 w-7"
                            onClick={() => copyKey(revealedKeys[key.id])}
                            title="Copy key"
                          >
                            <Copy className="w-3.5 h-3.5" />
                          </Button>
                        )}
                      </div>
                    </TableCell>
                    <TableCell>{key.usage_count.toLocaleString()}</TableCell>
                    <TableCell className="text-muted-foreground">
                      {key.last_used_at
                        ? formatRelativeTime(key.last_used_at)
                        : "Never"}
                    </TableCell>
                    <TableCell>
                      {key.expires_at ? (
                        <span>{formatExpiresInDays(key.expires_at)}</span>
                      ) : (
                        <span className="text-muted-foreground">Never</span>
                      )}
                    </TableCell>
                    <TableCell className="text-right">
                      <div className="flex items-center justify-end gap-1">
                        <Button
                          variant="ghost"
                          size="icon"
                          onClick={() => rotateMutation.mutate(key.id)}
                          disabled={rotateMutation.isPending}
                          title="Rotate key"
                        >
                          <RotateCcw className="w-4 h-4" />
                        </Button>
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button
                              variant="ghost"
                              size="icon"
                              className="text-destructive hover:text-destructive"
                              title="Revoke key"
                            >
                              <Trash2 className="w-4 h-4" />
                            </Button>
                          </AlertDialogTrigger>
                          <AlertDialogContent>
                            <AlertDialogHeader>
                              <AlertDialogTitle>Revoke API key?</AlertDialogTitle>
                              <AlertDialogDescription>
                                This will immediately disable the key &quot;{key.name}&quot;.
                                Any applications using this key will stop working.
                              </AlertDialogDescription>
                            </AlertDialogHeader>
                            <AlertDialogFooter>
                              <AlertDialogCancel>Cancel</AlertDialogCancel>
                              <AlertDialogAction
                                onClick={() => revokeMutation.mutate(key.id)}
                                className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
                              >
                                Revoke Key
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      </div>
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          )}
        </CardContent>
      </Card>

      {/* Revoked Keys */}
      {revokedKeys.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-lg">Revoked Keys</CardTitle>
            <CardDescription>
              These keys have been revoked and can no longer be used
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Table>
              <TableHeader>
                <TableRow>
                  <TableHead>Name</TableHead>
                  <TableHead>Key</TableHead>
                  <TableHead>Revoked</TableHead>
                  <TableHead>Total Usage</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {revokedKeys.map((key) => (
                  <TableRow key={key.id} className="opacity-60">
                    <TableCell className="font-medium">{key.name}</TableCell>
                    <TableCell>
                      <code className="text-xs bg-muted px-2 py-1 rounded">
                        {key.key_prefix}
                      </code>
                    </TableCell>
                    <TableCell>
                      {key.revoked_at
                        ? formatRelativeTime(key.revoked_at)
                        : "Unknown"}
                    </TableCell>
                    <TableCell>{key.usage_count.toLocaleString()}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
