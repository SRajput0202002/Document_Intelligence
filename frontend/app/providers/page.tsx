"use client";

import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Cloud,
  HardDrive,
  TestTube,
  Trash2,
  AlertCircle,
  Gift,
  ServerOff,
  Filter,
} from "lucide-react";

// Animated icons
import { CpuIcon } from "@/components/ui/cpu";
import { CheckIcon } from "@/components/ui/check";
import { XIcon } from "@/components/ui/x";
import { KeyIcon } from "@/components/ui/key";
import { SettingsIcon } from "@/components/ui/settings";
import { RefreshCWIcon } from "@/components/ui/refresh-cw";
import { ZapIcon } from "@/components/ui/zap";
import { PlusIcon } from "@/components/ui/plus";
import { EyeIcon } from "@/components/ui/eye";
import { EyeOffIcon } from "@/components/ui/eye-off";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { SparklesIcon } from "@/components/ui/sparkles";
import { LayersIcon } from "@/components/ui/layers";
import { CogIcon } from "@/components/ui/cog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
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
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
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
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { toast } from "@/components/ui/toast";
import { api, Provider, ProviderConfig } from "@/lib/api";
import { cn } from "@/lib/utils";

export default function ProvidersPage() {
  const queryClient = useQueryClient();
  const [configureProvider, setConfigureProvider] = useState<Provider | null>(null);
  const [apiKeyInput, setApiKeyInput] = useState("");
  const [showApiKey, setShowApiKey] = useState(false);
  const [deleteConfirm, setDeleteConfirm] = useState<ProviderConfig | null>(null);
  const [testResult, setTestResult] = useState<{ success: boolean; message: string; time?: number } | null>(null);
  const [isTesting, setIsTesting] = useState(false);

  // Filters
  const [typeFilter, setTypeFilter] = useState<"all" | "cloud" | "local">("all");
  const [costFilter, setCostFilter] = useState<"all" | "free" | "paid">("all");
  const [statusFilter, setStatusFilter] = useState<"all" | "available" | "configured">("all");

  // Fetch available providers
  const { data: providers, isLoading, refetch } = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.getProviders(),
  });

  // Fetch saved provider configs
  const { data: savedConfigs, refetch: refetchConfigs } = useQuery({
    queryKey: ["providerConfigs"],
    queryFn: () => api.listProviderConfigs(),
  });

  // Save provider config mutation
  const saveConfigMutation = useMutation({
    mutationFn: async ({ provider, apiKey }: { provider: Provider; apiKey: string }) => {
      const providerType = providers?.ocr_providers?.some(p => p.name === provider.name) ? "ocr" : "llm";
      return api.createProviderConfig(
        provider.name,
        providerType as "ocr" | "llm",
        { api_key: apiKey },
        provider.display_name,
        true
      );
    },
    onSuccess: () => {
      toast({ title: "Configuration saved", description: "Provider configuration has been saved successfully." });
      setConfigureProvider(null);
      setApiKeyInput("");
      setTestResult(null);
      refetch();
      refetchConfigs();
    },
    onError: (error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  // Delete provider config mutation
  const deleteConfigMutation = useMutation({
    mutationFn: (configId: string) => api.deleteProviderConfig(configId),
    onSuccess: () => {
      toast({ title: "Configuration deleted", description: "Provider configuration has been removed." });
      setDeleteConfirm(null);
      refetch();
      refetchConfigs();
    },
    onError: (error) => {
      toast({ title: "Error", description: error.message, variant: "destructive" });
    },
  });

  // Test connection
  const handleTestConnection = async () => {
    if (!configureProvider) return;

    setIsTesting(true);
    setTestResult(null);

    try {
      const providerType = providers?.ocr_providers?.some(p => p.name === configureProvider.name) ? "ocr" : "llm";
      const result = await api.testProviderConnection(
        configureProvider.name,
        providerType as "ocr" | "llm",
        apiKeyInput || undefined
      );
      setTestResult({
        success: result.success,
        message: result.message,
        time: result.response_time_ms || undefined,
      });
    } catch (error) {
      setTestResult({
        success: false,
        message: error instanceof Error ? error.message : "Test failed",
      });
    } finally {
      setIsTesting(false);
    }
  };

  const handleSaveConfig = () => {
    if (!configureProvider) return;

    if (configureProvider.requires_api_key && !apiKeyInput) {
      toast({ title: "Error", description: "API key is required", variant: "destructive" });
      return;
    }

    saveConfigMutation.mutate({ provider: configureProvider, apiKey: apiKeyInput });
  };

  const getConfigForProvider = (providerName: string): ProviderConfig | undefined => {
    return savedConfigs?.find(c => c.provider_name === providerName);
  };

  const getCostBadge = (tier: string) => {
    switch (tier) {
      case "free":
        return <Badge variant="secondary" className="bg-green-500/10 text-green-600 border-green-500/20">FREE</Badge>;
      case "low":
        return <Badge variant="secondary" className="bg-blue-500/10 text-blue-600 border-blue-500/20">$</Badge>;
      case "medium":
        return <Badge variant="secondary" className="bg-yellow-500/10 text-yellow-600 border-yellow-500/20">$$</Badge>;
      case "high":
        return <Badge variant="secondary" className="bg-red-500/10 text-red-600 border-red-500/20">$$$</Badge>;
      default:
        return null;
    }
  };

  const getTypeIcon = (type: string) => {
    return type === "local" ? (
      <HardDrive className="h-4 w-4" />
    ) : (
      <Cloud className="h-4 w-4" />
    );
  };

  const getTypeLabel = (type: string) => {
    return type === "local" ? "Local" : "Cloud";
  };

  // Filter providers
  const filterProviders = (providerList: Provider[]) => {
    return providerList.filter(provider => {
      // Type filter
      if (typeFilter !== "all" && provider.provider_type !== typeFilter) {
        return false;
      }

      // Cost filter
      if (costFilter === "free" && provider.cost_tier !== "free") {
        return false;
      }
      if (costFilter === "paid" && provider.cost_tier === "free") {
        return false;
      }

      // Status filter
      if (statusFilter === "available" && !provider.is_available) {
        return false;
      }
      if (statusFilter === "configured" && !getConfigForProvider(provider.name)) {
        return false;
      }

      return true;
    });
  };

  const filteredOcrProviders = providers?.ocr_providers ? filterProviders(providers.ocr_providers) : [];
  const filteredLlmProviders = providers?.llm_providers ? filterProviders(providers.llm_providers) : [];

  if (isLoading) {
    return (
      <div className="flex items-center justify-center h-[calc(100vh-4rem)]">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 px-4 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Providers</h1>
          <p className="text-muted-foreground">
            Configure OCR and LLM providers for document extraction
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => { refetch(); refetchConfigs(); }}>
            <RefreshCWIcon size={16} className="mr-2" />
            Refresh Status
          </Button>
        </div>
      </div>

      {/* Stats - Clean professional monochrome design */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-8">
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">
                  {providers?.ocr_providers?.filter(p => p.is_available).length || 0}
                </div>
                <p className="text-xs text-muted-foreground">OCR Available</p>
              </div>
              <CpuIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">
                  {providers?.llm_providers?.filter(p => p.is_available).length || 0}
                </div>
                <p className="text-xs text-muted-foreground">LLM Available</p>
              </div>
              <ZapIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">
                  {[...(providers?.ocr_providers || []), ...(providers?.llm_providers || [])]
                    .filter(p => p.cost_tier === "free" && p.is_available).length}
                </div>
                <p className="text-xs text-muted-foreground">Free Providers</p>
              </div>
              <Gift className="w-5 h-5 text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">
                  {savedConfigs?.length || 0}
                </div>
                <p className="text-xs text-muted-foreground">Configured</p>
              </div>
              <CogIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* OCR Providers */}
      <div className="mb-8">
        <div className="flex items-center justify-between mb-4">
          <h2 className="text-lg font-semibold flex items-center gap-2">
            <CpuIcon size={20} />
            OCR Providers
            <span className="text-sm font-normal text-muted-foreground">
              ({filteredOcrProviders.length})
            </span>
          </h2>

          {/* Filter Dropdown */}
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm">
                <Filter className="w-4 h-4 mr-2" />
                Filters
                {(typeFilter !== "all" || costFilter !== "all" || statusFilter !== "all") && (
                  <span className="ml-2 w-5 h-5 rounded-full bg-primary text-primary-foreground text-[10px] flex items-center justify-center">
                    {[typeFilter !== "all", costFilter !== "all", statusFilter !== "all"].filter(Boolean).length}
                  </span>
                )}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="w-80 p-4">
              <div className="space-y-5">
                {/* Type Filter */}
                <div>
                  <p className="text-xs font-semibold text-foreground mb-2.5">Type</p>
                  <div className="flex items-center bg-muted rounded-full p-1 border border-border">
                    <button
                      onClick={() => setTypeFilter("all")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all",
                        typeFilter === "all"
                          ? "bg-primary text-primary-foreground shadow-md"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      All
                    </button>
                    <button
                      onClick={() => setTypeFilter("cloud")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all flex items-center justify-center gap-1.5",
                        typeFilter === "cloud"
                          ? "bg-primary text-primary-foreground shadow-md"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      <Cloud className="w-3.5 h-3.5" />
                      Cloud
                    </button>
                    <button
                      onClick={() => setTypeFilter("local")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all flex items-center justify-center gap-1.5",
                        typeFilter === "local"
                          ? "bg-primary text-primary-foreground shadow-md"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      <HardDrive className="w-3.5 h-3.5" />
                      Local
                    </button>
                  </div>
                </div>

                {/* Cost Filter */}
                <div>
                  <p className="text-xs font-semibold text-foreground mb-2.5">Pricing</p>
                  <div className="flex items-center bg-muted rounded-full p-1 border border-border">
                    <button
                      onClick={() => setCostFilter("all")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all",
                        costFilter === "all"
                          ? "bg-primary text-primary-foreground shadow-md"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      All
                    </button>
                    <button
                      onClick={() => setCostFilter("free")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all",
                        costFilter === "free"
                          ? "bg-emerald-500 text-white shadow-md"
                          : "text-emerald-600 hover:text-emerald-700"
                      )}
                    >
                      Free
                    </button>
                    <button
                      onClick={() => setCostFilter("paid")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all",
                        costFilter === "paid"
                          ? "bg-amber-500 text-white shadow-md"
                          : "text-amber-600 hover:text-amber-700"
                      )}
                    >
                      Paid
                    </button>
                  </div>
                </div>

                {/* Status Filter */}
                <div>
                  <p className="text-xs font-semibold text-foreground mb-2.5">Status</p>
                  <div className="flex items-center bg-muted rounded-full p-1 border border-border">
                    <button
                      onClick={() => setStatusFilter("all")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all",
                        statusFilter === "all"
                          ? "bg-primary text-primary-foreground shadow-md"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      All
                    </button>
                    <button
                      onClick={() => setStatusFilter("available")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all",
                        statusFilter === "available"
                          ? "bg-primary text-primary-foreground shadow-md"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Available
                    </button>
                    <button
                      onClick={() => setStatusFilter("configured")}
                      className={cn(
                        "flex-1 px-4 py-2 text-xs font-medium rounded-full transition-all",
                        statusFilter === "configured"
                          ? "bg-primary text-primary-foreground shadow-md"
                          : "text-muted-foreground hover:text-foreground"
                      )}
                    >
                      Configured
                    </button>
                  </div>
                </div>

                {/* Clear Filters */}
                {(typeFilter !== "all" || costFilter !== "all" || statusFilter !== "all") && (
                  <button
                    onClick={() => {
                      setTypeFilter("all");
                      setCostFilter("all");
                      setStatusFilter("all");
                    }}
                    className="w-full px-4 py-2.5 text-xs font-medium text-muted-foreground hover:text-foreground hover:bg-muted/80 rounded-lg border border-border transition-colors"
                  >
                    Clear all filters
                  </button>
                )}
              </div>
            </DropdownMenuContent>
          </DropdownMenu>
        </div>
        {filteredOcrProviders.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredOcrProviders.map((provider) => (
              <ProviderCard
                key={provider.name}
                provider={provider}
                savedConfig={getConfigForProvider(provider.name)}
                onConfigure={() => {
                  setConfigureProvider(provider);
                  setApiKeyInput("");
                  setTestResult(null);
                  setShowApiKey(false);
                }}
                onDelete={(config) => setDeleteConfirm(config)}
                getCostBadge={getCostBadge}
                getTypeIcon={getTypeIcon}
                getTypeLabel={getTypeLabel}
              />
            ))}
          </div>
        ) : (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-3">
                <ServerOff className="h-6 w-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">No OCR providers match filters</p>
              <p className="text-xs text-muted-foreground mt-1">Try adjusting your filter criteria</p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* LLM Extractors */}
      <div>
        <h2 className="text-lg font-semibold mb-4 flex items-center gap-2">
          <ZapIcon size={20} />
          LLM Extractors
          <span className="text-sm font-normal text-muted-foreground">
            ({filteredLlmProviders.length})
          </span>
        </h2>
        {filteredLlmProviders.length > 0 ? (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredLlmProviders.map((provider) => (
              <ProviderCard
                key={provider.name}
                provider={provider}
                savedConfig={getConfigForProvider(provider.name)}
                onConfigure={() => {
                  setConfigureProvider(provider);
                  setApiKeyInput("");
                  setTestResult(null);
                  setShowApiKey(false);
                }}
                onDelete={(config) => setDeleteConfirm(config)}
                getCostBadge={getCostBadge}
                getTypeIcon={getTypeIcon}
                getTypeLabel={getTypeLabel}
              />
            ))}
          </div>
        ) : (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <div className="w-12 h-12 rounded-full bg-muted flex items-center justify-center mb-3">
                <ServerOff className="h-6 w-6 text-muted-foreground" />
              </div>
              <p className="text-sm font-medium">No LLM extractors match filters</p>
              <p className="text-xs text-muted-foreground mt-1">Try adjusting your filter criteria</p>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Configure Dialog */}
      <Dialog open={!!configureProvider} onOpenChange={() => setConfigureProvider(null)}>
        <DialogContent className="sm:max-w-[500px]">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {configureProvider?.requires_api_key ? (
                <KeyIcon size={20} />
              ) : (
                <SettingsIcon size={20} />
              )}
              Configure {configureProvider?.display_name}
            </DialogTitle>
            <DialogDescription>
              {configureProvider?.requires_api_key
                ? "Enter your API key to enable this provider. Keys are stored securely."
                : "Configure settings for this provider."}
            </DialogDescription>
          </DialogHeader>

          <div className="py-4 space-y-4">
            {/* Provider Info */}
            <div className="flex items-center gap-2 text-sm">
              <Badge variant="outline">
                {getTypeIcon(configureProvider?.provider_type || "local")}
                <span className="ml-1">{configureProvider?.provider_type === "local" ? "Local" : "Cloud"}</span>
              </Badge>
              {getCostBadge(configureProvider?.cost_tier || "free")}
            </div>

            <p className="text-sm text-muted-foreground">
              {configureProvider?.description}
            </p>

            {/* API Key Input */}
            {configureProvider?.requires_api_key && (
              <div className="space-y-2">
                <Label htmlFor="apiKey">API Key</Label>
                <div className="relative">
                  <Input
                    id="apiKey"
                    type={showApiKey ? "text" : "password"}
                    placeholder="Enter your API key"
                    value={apiKeyInput}
                    onChange={(e) => setApiKeyInput(e.target.value)}
                    className="pr-10"
                  />
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    className="absolute right-0 top-0 h-full px-3 hover:bg-transparent"
                    onClick={() => setShowApiKey(!showApiKey)}
                  >
                    {showApiKey ? (
                      <EyeOffIcon size={16} className="text-muted-foreground" />
                    ) : (
                      <EyeIcon size={16} className="text-muted-foreground" />
                    )}
                  </Button>
                </div>
                {configureProvider.api_key_env_var && (
                  <p className="text-xs text-muted-foreground">
                    Or set environment variable: <code className="bg-muted px-1 rounded">{configureProvider.api_key_env_var}</code>
                  </p>
                )}
              </div>
            )}

            {/* Test Result */}
            {testResult && (
              <div className={cn(
                "flex items-center gap-2 p-3 rounded-md text-sm",
                testResult.success
                  ? "bg-green-500/10 text-green-600 border border-green-500/20"
                  : "bg-red-500/10 text-red-600 border border-red-500/20"
              )}>
                {testResult.success ? (
                  <CircleCheckIcon size={16} />
                ) : (
                  <AlertCircle className="h-4 w-4" />
                )}
                <span>{testResult.message}</span>
                {testResult.time && (
                  <span className="text-xs opacity-75">({testResult.time.toFixed(0)}ms)</span>
                )}
              </div>
            )}

            {/* Capabilities */}
            {configureProvider?.capabilities && configureProvider.capabilities.length > 0 && (
              <div className="space-y-2">
                <Label>Capabilities</Label>
                <div className="flex flex-wrap gap-2">
                  {configureProvider.capabilities.map((capability) => (
                    <Badge key={capability} variant="outline" className="text-xs">
                      {capability}
                    </Badge>
                  ))}
                </div>
              </div>
            )}
          </div>

          <DialogFooter className="gap-2 sm:gap-0">
            <Button
              variant="outline"
              onClick={handleTestConnection}
              disabled={isTesting || (configureProvider?.requires_api_key && !apiKeyInput)}
            >
              {isTesting ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : (
                <TestTube className="h-4 w-4 mr-2" />
              )}
              Test Connection
            </Button>
            <Button
              onClick={handleSaveConfig}
              disabled={saveConfigMutation.isPending || (configureProvider?.requires_api_key && !apiKeyInput)}
            >
              {saveConfigMutation.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              ) : null}
              Save Configuration
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteConfirm} onOpenChange={() => setDeleteConfirm(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Provider Configuration?</AlertDialogTitle>
            <AlertDialogDescription>
              This will remove the saved configuration for {deleteConfirm?.display_name || deleteConfirm?.provider_name}.
              You can reconfigure it at any time.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteConfirm && deleteConfigMutation.mutate(deleteConfirm.id)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteConfigMutation.isPending ? (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
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

function ProviderCard({
  provider,
  savedConfig,
  onConfigure,
  onDelete,
  getCostBadge,
  getTypeIcon,
  getTypeLabel,
}: {
  provider: Provider;
  savedConfig?: ProviderConfig;
  onConfigure: () => void;
  onDelete: (config: ProviderConfig) => void;
  getCostBadge: (tier: string) => React.ReactNode;
  getTypeIcon: (type: string) => React.ReactNode;
  getTypeLabel: (type: string) => string;
}) {
  const isConfigured = !!savedConfig;
  const lastTestSuccess = savedConfig?.last_test_success;

  return (
    <Card
      className={cn(
        "min-w-0 transition-all",
        !provider.is_available && !isConfigured && "opacity-60"
      )}
    >
      <CardHeader className="pb-3 space-y-0">
        <div className="flex flex-col gap-3 min-w-0 sm:flex-row sm:items-start sm:justify-between sm:gap-2">
          <div className="flex min-w-0 flex-1 items-start gap-3">
            <div className={cn(
              "w-10 h-10 shrink-0 rounded-lg flex items-center justify-center",
              provider.is_available
                ? "bg-green-500/10 text-green-600"
                : isConfigured
                  ? lastTestSuccess === true
                    ? "bg-green-500/10 text-green-600"
                    : lastTestSuccess === false
                      ? "bg-red-500/10 text-red-600"
                      : "bg-yellow-500/10 text-yellow-600"
                  : "bg-muted text-muted-foreground"
            )}>
              {provider.is_available ? (
                <CheckIcon size={20} />
              ) : isConfigured ? (
                lastTestSuccess === true ? (
                  <CheckIcon size={20} />
                ) : lastTestSuccess === false ? (
                  <XIcon size={20} />
                ) : (
                  <KeyIcon size={20} />
                )
              ) : (
                <XIcon size={20} />
              )}
            </div>
            <div className="min-w-0 flex-1">
              <CardTitle className="text-base break-words">{provider.display_name}</CardTitle>
              <div className="flex flex-wrap items-center gap-2 mt-1">
                <Badge variant="outline" className="text-xs">
                  {getTypeIcon(provider.provider_type)}
                  <span className="ml-1">{getTypeLabel(provider.provider_type)}</span>
                </Badge>
                {getCostBadge(provider.cost_tier)}
                {isConfigured && (
                  <Badge variant="secondary" className="text-xs bg-purple-500/10 text-purple-600 border-purple-500/20">
                    Configured
                  </Badge>
                )}
              </div>
            </div>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-0.5 w-full sm:w-auto">
            <Button
              variant="ghost"
              size="sm"
              className="shrink-0"
              onClick={onConfigure}
            >
              {provider.requires_api_key && !provider.is_available && !isConfigured ? (
                <>
                  <KeyIcon size={16} className="mr-1" />
                  Add Key
                </>
              ) : (
                <>
                  <SettingsIcon size={16} className="mr-1" />
                  Configure
                </>
              )}
            </Button>
            {isConfigured && (
              <Button
                variant="ghost"
                size="sm"
                className="shrink-0 text-muted-foreground hover:text-destructive"
                onClick={() => onDelete(savedConfig)}
              >
                <Trash2 className="h-4 w-4 mr-1" />
                Remove
              </Button>
            )}
          </div>
        </div>
      </CardHeader>
      <CardContent>
        <p className="text-sm text-muted-foreground mb-3">
          {provider.description}
        </p>
        {/* Available models - for OCR providers that support multiple models */}
        {(() => {
          const modelConfig = provider.config_options?.model as
            | { default?: string; options?: Array<{ value: string; label: string }> }
            | undefined;
          const modelOptions = modelConfig?.options;
          if (!modelOptions || !Array.isArray(modelOptions) || modelOptions.length === 0)
            return null;
          const defaultModel =
            modelConfig?.default ?? modelOptions[0]?.value ?? "";
          return (
            <div className="mt-3 space-y-1.5 mb-2">
              <Label className="text-xs text-muted-foreground">Available Models</Label>
              <Select defaultValue={defaultModel}>
                <SelectTrigger className="h-8 text-xs">
                  <SelectValue placeholder="Models" />
                </SelectTrigger>
                <SelectContent>
                  {modelOptions.map((opt) => (
                    <SelectItem key={opt.value} value={opt.value} className="text-xs">
                      {opt.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          );
        })()}
        <div className="flex items-center justify-between text-xs text-muted-foreground">
          <span className="flex items-center gap-1">
            {provider.is_available || (isConfigured && lastTestSuccess) ? (
              <CheckIcon size={12} className="text-green-500" />
            ) : isConfigured && lastTestSuccess === false ? (
              <XIcon size={12} className="text-red-500" />
            ) : (
              <XIcon size={12} className="text-muted-foreground" />
            )}
            {provider.is_available
              ? "Available"
              : isConfigured
                ? lastTestSuccess === true
                  ? "Configured & Working"
                  : lastTestSuccess === false
                    ? "Configuration Error"
                    : "Configured (not tested)"
                : "Not configured"}
          </span>
        </div>
        {!provider.is_available && !isConfigured && provider.requires_api_key && (
          <p className="text-xs text-amber-600 mt-2">
            Missing: {provider.api_key_env_var}
          </p>
        )}
        {isConfigured && savedConfig.last_test_at && (
          <p className="text-xs text-muted-foreground mt-2">
            Last tested: {new Date(savedConfig.last_test_at).toLocaleString()}
          </p>
        )}
      </CardContent>
    </Card>
  );
}
