"use client";

import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Database,
  FolderOpen,
  Globe,
  Bell,
  Shield,
  Info,
  Save,
  Brain,
  CheckCircle2,
  ScanText,
  Cpu,
  Cloud,
  HardDrive,
  FileText,
  Palette,
  RotateCcw,
  Loader2,
  AlertCircle,
  Eye,
  Settings2,
  Zap,
  Layers,
  ChevronRight,
  Split,
  FlaskConical,
} from "lucide-react";
import Link from "next/link";
import { useTheme } from "next-themes";

// Animated icons
import { SettingsIcon } from "@/components/ui/settings";
import { RefreshCWIcon } from "@/components/ui/refresh-cw";
import { ScanTextIcon } from "@/components/ui/scan-text";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Badge } from "@/components/ui/badge";
import { Slider } from "@/components/ui/slider";
import { toast } from "@/components/ui/toast";
import { useSettings } from "@/hooks/use-settings";
import { api, type UserSettings } from "@/lib/api";


export default function SettingsPage() {
  const queryClient = useQueryClient();
  const { settings, defaults, loading, error, updateSettings, resetSettings, refreshSettings } = useSettings();
  const { theme: currentTheme, setTheme } = useTheme();
  const [localSettings, setLocalSettings] = useState<Partial<UserSettings>>({});
  const [saving, setSaving] = useState(false);
  const [hasChanges, setHasChanges] = useState(false);
  const [initialLoadDone, setInitialLoadDone] = useState(false);
  const [justSaved, setJustSaved] = useState(false);

  // Fetch providers from API
  const { data: providers } = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.getProviders(),
  });

  const ocrProviders = providers?.ocr_providers?.filter(p => p.is_available) || [];
  const llmProviders = providers?.llm_providers?.filter(p => p.is_available) || [];

  // Sync local settings with server settings - only on initial load
  // IMPORTANT: Merge server settings with defaults so all keys are present
  useEffect(() => {
    if (settings && defaults) {
      if (!initialLoadDone) {
        // Merge defaults with actual settings - settings take precedence
        const mergedSettings = { ...defaults, ...settings };
        setLocalSettings(mergedSettings);
        setInitialLoadDone(true);
      }
    }
  }, [settings, defaults, initialLoadDone]);

  // Track changes by comparing local settings with server settings
  useEffect(() => {
    // Skip comparison right after save to avoid race condition
    if (justSaved) {
      setJustSaved(false);
      return;
    }
    if (settings && localSettings && initialLoadDone) {
      const changed = Object.keys(localSettings).some(
        key => JSON.stringify(localSettings[key as keyof UserSettings]) !== JSON.stringify(settings[key as keyof UserSettings])
      );
      setHasChanges(changed);
    }
  }, [localSettings, settings, initialLoadDone, justSaved]);

  const handleSave = async () => {
    if (!hasChanges) return;

    setSaving(true);
    try {
      const savedSettings = await updateSettings(localSettings);
      // Mark that we just saved to skip the next comparison
      setJustSaved(true);
      // Sync local settings with the server response to clear Modified state
      setLocalSettings(savedSettings);
      // Invalidate sidebar hover card cache so it shows updated settings
      queryClient.invalidateQueries({ queryKey: ["sidebarSettings"] });
      toast({
        title: "Settings saved",
        description: "Your settings have been updated successfully.",
      });
      setHasChanges(false);
    } catch (err) {
      toast({
        title: "Failed to save",
        description: err instanceof Error ? err.message : "An error occurred",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  const handleReset = async () => {
    if (confirm("Are you sure you want to reset all settings to defaults?")) {
      try {
        await resetSettings();
        // Allow re-sync with server defaults
        setInitialLoadDone(false);
        // Invalidate sidebar hover card cache
        queryClient.invalidateQueries({ queryKey: ["sidebarSettings"] });
        toast({
          title: "Settings reset",
          description: "All settings have been restored to defaults.",
        });
      } catch (err) {
        toast({
          title: "Failed to reset",
          description: err instanceof Error ? err.message : "An error occurred",
          variant: "destructive",
        });
      }
    }
  };

  const updateLocalSetting = <K extends keyof UserSettings>(key: K, value: UserSettings[K]) => {
    setLocalSettings(prev => ({ ...prev, [key]: value }));
  };

  const handleThemeChange = (theme: "light" | "dark" | "system") => {
    updateLocalSetting("theme", theme);
    setTheme(theme);
  };

  // Get current value - check localSettings first, then settings, then defaults
  const getValue = <K extends keyof UserSettings>(key: K): UserSettings[K] => {
    // After initial load, localSettings will have merged values
    // Before that, fall back to settings/defaults from API
    return (localSettings[key] ?? settings?.[key] ?? defaults?.[key]) as UserSettings[K];
  };

  const selectedTheme = (currentTheme === "light" || currentTheme === "dark" || currentTheme === "system")
    ? currentTheme
    : (getValue("theme") as "light" | "dark" | "system");

  // Check loading state first
  if (loading) {
    return (
      <div className="container mx-auto py-6 px-4 max-w-4xl">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  // Then check for errors (after loading is complete)
  if (error || !settings || !defaults) {
    return (
      <div className="container mx-auto py-6 px-4 max-w-4xl">
        <div className="flex flex-col items-center justify-center h-64 gap-4">
          <AlertCircle className="h-12 w-12 text-destructive" />
          <p className="text-destructive">{error || "Failed to load settings"}</p>
          <Button onClick={refreshSettings}>Try Again</Button>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 px-4 max-w-4xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Settings</h1>
          <p className="text-muted-foreground">
            Configure platform settings and preferences
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" onClick={handleReset}>
            <RotateCcw className="h-4 w-4 mr-2" />
            Reset
          </Button>
          <Button onClick={handleSave} disabled={!hasChanges || saving}>
            {saving ? (
              <Loader2 className="h-4 w-4 mr-2 animate-spin" />
            ) : (
              <Save className="h-4 w-4 mr-2" />
            )}
            Save Changes
            {hasChanges && <Badge variant="secondary" className="ml-2">Modified</Badge>}
          </Button>
        </div>
      </div>

      <div className="space-y-6">
        {/* Document Classification */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Brain className="h-5 w-5" />
              Document Classifier
            </CardTitle>
            <CardDescription>
              AI model for document type detection and automatic schema generation
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* Classifier Selection */}
            <div className="space-y-2">
              <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                <Brain className="w-3.5 h-3.5" />
                Classification Model
              </Label>
              <p className="text-xs text-muted-foreground mb-2">
                Also used for automatic schema inference when generating extraction schemas
              </p>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { value: "pattern", label: "Pattern", description: "Fast keyword matching" },
                  { value: "gpt-4o", label: "GPT-4o", description: "OpenAI high accuracy" },
                  { value: "gemini", label: "Gemini", description: "Google AI" },
                  { value: "mistral", label: "Mistral", description: "Mistral AI" },
                  { value: "custom", label: "Custom", description: "Custom classifier", beta: true },
                ].map((clf) => {
                  const isSelected = getValue("document_classifier") === clf.value;
                  return (
                    <button
                      key={clf.value}
                      onClick={() => updateLocalSetting("document_classifier", clf.value)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all border ${
                        isSelected
                          ? "bg-emerald-50 text-emerald-700 border-emerald-500 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500"
                          : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"
                      }`}
                      title={clf.description}
                    >
                      {isSelected && <CheckCircle2 className="w-3 h-3" />}
                      {clf.label}
                      {clf.beta && <span className="text-[9px] px-1 py-0.5 rounded-full bg-amber-100 text-amber-700 dark:bg-amber-500/20 dark:text-amber-400">Beta</span>}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* PDF Extractor */}
            <div className="space-y-2">
              <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                <FileText className="w-3.5 h-3.5" />
                PDF Text Extractor
              </Label>
              <p className="text-xs text-muted-foreground mb-2">
                Library used for initial PDF text extraction (before OCR fallback)
              </p>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { value: "pymupdf4llm", label: "PyMuPDF4LLM", description: "Markdown output (recommended)" },
                  { value: "pymupdf", label: "PyMuPDF", description: "Basic text extraction" },
                  { value: "pdfplumber", label: "PDFPlumber", description: "Table-aware extraction" },
                  { value: "pypdf", label: "PyPDF", description: "Lightweight fallback" },
                ].map((ext) => {
                  const isSelected = getValue("pdf_extractor") === ext.value;
                  return (
                    <button
                      key={ext.value}
                      onClick={() => updateLocalSetting("pdf_extractor", ext.value)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all border ${
                        isSelected
                          ? "bg-blue-50 text-blue-700 border-blue-500 dark:bg-blue-500/10 dark:text-blue-400 dark:border-blue-500"
                          : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"
                      }`}
                      title={ext.description}
                    >
                      {isSelected && <CheckCircle2 className="w-3 h-3" />}
                      {ext.label}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Fallback OCR */}
            <div className="space-y-2">
              <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                <ScanText className="w-3.5 h-3.5" />
                Fallback OCR Provider
              </Label>
              <p className="text-xs text-muted-foreground mb-2">
                OCR provider used when PDF extraction yields minimal text (e.g., scanned documents). Also used for schema inference.
              </p>
              <div className="flex flex-wrap gap-1.5">
                {ocrProviders.map((p) => {
                  const isSelected = getValue("fallback_ocr") === p.name;
                  return (
                    <button
                      key={p.name}
                      onClick={() => updateLocalSetting("fallback_ocr", p.name)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all border ${
                        isSelected
                          ? "bg-orange-50 text-orange-700 border-orange-500 dark:bg-orange-500/10 dark:text-orange-400 dark:border-orange-500"
                          : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"
                      }`}
                    >
                      {isSelected && <CheckCircle2 className="w-3 h-3" />}
                      {p.display_name}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* Min Text Threshold */}
            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                  <Settings2 className="w-3.5 h-3.5" />
                  Minimum Text Threshold
                </Label>
                <span className="text-sm font-medium">{getValue("min_text_threshold")} chars</span>
              </div>
              <Slider
                value={[getValue("min_text_threshold")]}
                onValueChange={([value]) => updateLocalSetting("min_text_threshold", value)}
                min={10}
                max={200}
                step={10}
                className="w-full"
              />
              <p className="text-xs text-muted-foreground">
                If PDF extraction returns less than this many characters, fallback to OCR
              </p>
            </div>
          </CardContent>
        </Card>

        {/* Default Providers */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <SettingsIcon size={20} />
              Default Extraction Providers
            </CardTitle>
            <CardDescription>
              Default providers used for document extraction
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            {/* OCR Providers */}
            <div className="space-y-2">
              <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                <ScanText className="w-3.5 h-3.5" />
                Default OCR Provider
              </Label>
              <div className="flex flex-wrap gap-1.5">
                {ocrProviders.map((p) => {
                  const isSelected = getValue("default_ocr_provider") === p.name;
                  return (
                    <button
                      key={p.name}
                      onClick={() => updateLocalSetting("default_ocr_provider", p.name)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all border ${
                        isSelected
                          ? "bg-emerald-50 text-emerald-700 border-emerald-500 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500"
                          : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"
                      }`}
                    >
                      {isSelected && <CheckCircle2 className="w-3 h-3" />}
                      {p.display_name}
                    </button>
                  );
                })}
              </div>
            </div>

            {/* LLM Providers */}
            <div className="space-y-2">
              <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                <Cpu className="w-3.5 h-3.5" />
                Default LLM Extractor
              </Label>
              <div className="flex flex-wrap gap-1.5">
                {llmProviders.map((p) => {
                  const isSelected = getValue("default_llm_provider") === p.name;
                  return (
                    <button
                      key={p.name}
                      onClick={() => updateLocalSetting("default_llm_provider", p.name)}
                      className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all border ${
                        isSelected
                          ? "bg-emerald-50 text-emerald-700 border-emerald-500 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500"
                          : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"
                      }`}
                    >
                      {isSelected && <CheckCircle2 className="w-3 h-3" />}
                      {p.display_name}
                    </button>
                  );
                })}
              </div>
            </div>
          </CardContent>
        </Card>

        {/* Consensus Extraction */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Layers className="h-5 w-5" />
              Consensus Extraction
            </CardTitle>
            <CardDescription>
              Use multiple providers for higher accuracy extraction
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-6">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Enable Consensus Mode</Label>
                <p className="text-xs text-muted-foreground">
                  Run multiple providers and combine results for better accuracy
                </p>
              </div>
              <Switch
                checked={getValue("consensus_enabled")}
                onCheckedChange={(checked) => updateLocalSetting("consensus_enabled", checked)}
              />
            </div>

            {getValue("consensus_enabled") && (
              <>
                {/* Consensus Threshold */}
                <div className="space-y-2">
                  <div className="flex items-center justify-between">
                    <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                      Agreement Threshold
                    </Label>
                    <span className="text-sm font-medium">{Math.round(getValue("consensus_threshold") * 100)}%</span>
                  </div>
                  <Slider
                    value={[getValue("consensus_threshold") * 100]}
                    onValueChange={([value]) => updateLocalSetting("consensus_threshold", value / 100)}
                    min={30}
                    max={100}
                    step={5}
                    className="w-full"
                  />
                </div>

                {/* Consensus OCR Providers */}
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">Consensus OCR Providers</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {ocrProviders.map((p) => {
                      const isSelected = getValue("consensus_ocr_providers")?.includes(p.name);
                      return (
                        <button
                          key={p.name}
                          onClick={() => {
                            const current = getValue("consensus_ocr_providers") || [];
                            if (isSelected) {
                              updateLocalSetting("consensus_ocr_providers", current.filter(n => n !== p.name));
                            } else {
                              updateLocalSetting("consensus_ocr_providers", [...current, p.name]);
                            }
                          }}
                          className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all border ${
                            isSelected
                              ? "bg-purple-50 text-purple-700 border-purple-500 dark:bg-purple-500/10 dark:text-purple-400 dark:border-purple-500"
                              : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"
                          }`}
                        >
                          {isSelected && <CheckCircle2 className="w-3 h-3" />}
                          {p.display_name}
                        </button>
                      );
                    })}
                  </div>
                </div>

                {/* Consensus LLM Providers */}
                <div className="space-y-2">
                  <Label className="text-xs text-muted-foreground">Consensus LLM Providers</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {llmProviders.map((p) => {
                      const isSelected = getValue("consensus_llm_providers")?.includes(p.name);
                      return (
                        <button
                          key={p.name}
                          onClick={() => {
                            const current = getValue("consensus_llm_providers") || [];
                            if (isSelected) {
                              updateLocalSetting("consensus_llm_providers", current.filter(n => n !== p.name));
                            } else {
                              updateLocalSetting("consensus_llm_providers", [...current, p.name]);
                            }
                          }}
                          className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all border ${
                            isSelected
                              ? "bg-purple-50 text-purple-700 border-purple-500 dark:bg-purple-500/10 dark:text-purple-400 dark:border-purple-500"
                              : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"
                          }`}
                        >
                          {isSelected && <CheckCircle2 className="w-3 h-3" />}
                          {p.display_name}
                        </button>
                      );
                    })}
                  </div>
                </div>
              </>
            )}
          </CardContent>
        </Card>

        {/* Processing Options */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Zap className="h-5 w-5" />
              Processing Options
            </CardTitle>
            <CardDescription>
              Configure automatic processing behavior
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Auto-detect Document Type</Label>
                <p className="text-xs text-muted-foreground">
                  Automatically classify documents before extraction
                </p>
              </div>
              <Switch
                checked={getValue("auto_detect_document_type")}
                onCheckedChange={(checked) => updateLocalSetting("auto_detect_document_type", checked)}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Auto-infer Schema</Label>
                <p className="text-xs text-muted-foreground">
                  Automatically generate extraction schema from document
                </p>
              </div>
              <Switch
                checked={getValue("auto_infer_schema")}
                onCheckedChange={(checked) => updateLocalSetting("auto_infer_schema", checked)}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Save OCR Text</Label>
                <p className="text-xs text-muted-foreground">
                  Save raw OCR text alongside extracted data
                </p>
              </div>
              <Switch
                checked={getValue("save_ocr_text")}
                onCheckedChange={(checked) => updateLocalSetting("save_ocr_text", checked)}
              />
            </div>

            <div className="space-y-2">
              <div className="flex items-center justify-between">
                <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                  Max Pages for Classification
                </Label>
                <span className="text-sm font-medium">{getValue("max_pages_for_classification")} pages</span>
              </div>
              <Slider
                value={[getValue("max_pages_for_classification")]}
                onValueChange={([value]) => updateLocalSetting("max_pages_for_classification", value)}
                min={1}
                max={10}
                step={1}
                className="w-full"
              />
            </div>
          </CardContent>
        </Card>

        {/* UI Preferences */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Palette className="h-5 w-5" />
              UI Preferences
            </CardTitle>
            <CardDescription>
              Customize the interface appearance
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            {/* Theme */}
            <div className="space-y-2">
              <Label className="text-xs flex items-center gap-1.5 text-muted-foreground">
                <Palette className="w-3.5 h-3.5" />
                Theme
              </Label>
              <div className="flex flex-wrap gap-1.5">
                {[
                  { value: "light", label: "Light" },
                  { value: "dark", label: "Dark" },
                  { value: "system", label: "System" },
                ].map((theme) => {
                  const isSelected = selectedTheme === theme.value;
                  return (
                    <button
                      key={theme.value}
                      onClick={() => handleThemeChange(theme.value as "light" | "dark" | "system")}
                      className={`inline-flex items-center gap-1 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all border ${
                        isSelected
                          ? "bg-emerald-50 text-emerald-700 border-emerald-500 dark:bg-emerald-500/10 dark:text-emerald-400 dark:border-emerald-500"
                          : "bg-muted text-muted-foreground border-transparent hover:bg-muted/80"
                      }`}
                    >
                      {isSelected && <CheckCircle2 className="w-3 h-3" />}
                      {theme.label}
                    </button>
                  );
                })}
              </div>
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Compact View</Label>
                <p className="text-xs text-muted-foreground">
                  Use compact layout for denser information display
                </p>
              </div>
              <Switch
                checked={getValue("compact_view")}
                onCheckedChange={(checked) => updateLocalSetting("compact_view", checked)}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Show Confidence Scores</Label>
                <p className="text-xs text-muted-foreground">
                  Display confidence percentages in extraction results
                </p>
              </div>
              <Switch
                checked={getValue("show_confidence_scores")}
                onCheckedChange={(checked) => updateLocalSetting("show_confidence_scores", checked)}
              />
            </div>

            <div className="flex items-center justify-between">
              <div className="space-y-0.5">
                <Label>Auto-expand Results</Label>
                <p className="text-xs text-muted-foreground">
                  Automatically expand extraction results on completion
                </p>
              </div>
              <Switch
                checked={getValue("auto_expand_results")}
                onCheckedChange={(checked) => updateLocalSetting("auto_expand_results", checked)}
              />
            </div>
          </CardContent>
        </Card>

        {/* Segmentation Lab Link */}
        <Link href="/lab/segmentation">
          <Card className="hover:shadow-md transition-shadow cursor-pointer">
            <CardContent className="flex items-center justify-between p-4">
              <div className="flex items-center gap-3">
                <div className="h-10 w-10 rounded-lg bg-purple-100 dark:bg-purple-900/30 flex items-center justify-center">
                  <FlaskConical className="h-5 w-5 text-purple-600 dark:text-purple-400" />
                </div>
                <div>
                  <h3 className="font-medium">Segmentation Lab</h3>
                  <p className="text-sm text-muted-foreground">
                    Test segmentation approaches and configure profiles
                  </p>
                </div>
              </div>
              <ChevronRight className="h-5 w-5 text-muted-foreground" />
            </CardContent>
          </Card>
        </Link>

        {/* About */}
        <Card>
          <CardHeader>
            <CardTitle className="text-lg flex items-center gap-2">
              <Info className="h-5 w-5" />
              About
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-2 text-sm">
              <div className="flex justify-between">
                <span className="text-muted-foreground">Version</span>
                <Badge variant="outline">2.0.0</Badge>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">Platform</span>
                <span>OCR Extraction Platform</span>
              </div>
              <div className="flex justify-between">
                <span className="text-muted-foreground">License</span>
                <span>MIT</span>
              </div>
            </div>
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
