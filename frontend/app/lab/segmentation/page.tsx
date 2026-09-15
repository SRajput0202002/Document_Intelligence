"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import { useDropzone, type FileRejection } from "react-dropzone";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Loader2,
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  BarChart3,
  Layers,
  Fingerprint,
  Key,
  Copy,
  Brain,
  Zap,
  ChevronDown,
  ChevronRight,
  Eye,
  Clock,
  Target,
  RotateCcw,
  Plus,
  Pencil,
  Trash2,
  Save,
  FlaskConical,
  Shield,
  PanelLeftClose,
  PanelLeft,
  Settings2,
  TestTube2,
  Database,
  ChevronUp,
  Play,
  SplitSquareVertical,
  Search,
  Hash,
  Regex,
  ToggleLeft,
  ArrowLeftRight,
  Sparkles,
  Info,
  Code2,
  X,
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { formatApiErrorDetail } from "@/lib/format-api-error";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Separator } from "@/components/ui/separator";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
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
import { PDFViewer } from "@/components/pdf-viewer";
import { getAuthHeaders } from "@/hooks/use-auth";
import { cn } from "@/lib/utils";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// Types
interface VetoField {
  name: string;
  pattern: string;
  bidirectional: boolean;
  enabled: boolean;
}

interface SectionPattern {
  pattern: string;
  capture_group: number;
}

interface StartKeyword {
  pattern: string;
  confidence: number;
}

interface SegmentationProfile {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  veto_fields: VetoField[];
  section_patterns: SectionPattern[];
  start_keywords: StartKeyword[];
  supporting_fields: { name: string; pattern: string }[];
  continuity_patterns: string[];
  enable_section_splitting: boolean;
  default_detection_method: string | null;
  ocr_method: string;
  is_builtin: boolean;
  created_by: string | null;
  created_at: string | null;
  updated_at: string | null;
}

interface PatternTestResult {
  field_name: string;
  pattern: string;
  matched: boolean;
  value: string | null;
  match_count: number;
  error: string | null;
}

interface ApproachResult {
  approach: string;
  segments: [number, number][];
  boundaries: number[];
  processing_time_ms: number;
  accuracy: number | null;
  true_positives: number;
  false_positives: number;
  false_negatives: number;
  confidence_scores?: Record<number, number>;
  metadata?: Record<string, unknown>;
}

interface ComparisonResult {
  document_path: string;
  total_pages: number;
  ocr_method: string;
  ground_truth_segments: [number, number][] | null;
  results: ApproachResult[];
}

// API functions
const profileApi = {
  getProfiles: async (): Promise<SegmentationProfile[]> => {
    const res = await fetch(`${API_BASE_URL}/api/segmentation-profiles`, {
      headers: getAuthHeaders(),
    });
    if (!res.ok) throw new Error("Failed to fetch profiles");
    return res.json();
  },

  createProfile: async (profile: Partial<SegmentationProfile>): Promise<SegmentationProfile> => {
    const res = await fetch(`${API_BASE_URL}/api/segmentation-profiles`, {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(formatApiErrorDetail(error.detail, "Failed to create profile"));
    }
    return res.json();
  },

  updateProfile: async (id: string, profile: Partial<SegmentationProfile>): Promise<SegmentationProfile> => {
    const res = await fetch(`${API_BASE_URL}/api/segmentation-profiles/${id}`, {
      method: "PUT",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(formatApiErrorDetail(error.detail, "Failed to update profile"));
    }
    return res.json();
  },

  deleteProfile: async (id: string): Promise<void> => {
    const res = await fetch(`${API_BASE_URL}/api/segmentation-profiles/${id}`, {
      method: "DELETE",
      headers: getAuthHeaders(),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(formatApiErrorDetail(error.detail, "Failed to delete profile"));
    }
  },

  testPatterns: async (patterns: VetoField[], sampleText: string): Promise<PatternTestResult[]> => {
    const res = await fetch(`${API_BASE_URL}/api/segmentation-profiles/test-patterns-bulk`, {
      method: "POST",
      headers: { ...getAuthHeaders(), "Content-Type": "application/json" },
      body: JSON.stringify({ patterns, sample_text: sampleText }),
    });
    if (!res.ok) throw new Error("Failed to test patterns");
    const data = await res.json();
    return data.results;
  },
};

// OCR methods available
const OCR_METHODS = [
  { value: "auto", label: "Auto (PyMuPDF → Tesseract → Mistral)" },
  { value: "mistral", label: "Mistral API (Best quality)" },
  { value: "pymupdf", label: "PyMuPDF (Fast, digital PDFs)" },
  { value: "tesseract", label: "Tesseract (Scanned docs)" },
];

// Empty profile template
const emptyProfile: Partial<SegmentationProfile> = {
  name: "",
  display_name: "",
  description: "",
  veto_fields: [],
  section_patterns: [],
  start_keywords: [],
  supporting_fields: [],
  continuity_patterns: [],
  enable_section_splitting: false,
  default_detection_method: null,
  ocr_method: "auto",
};

export default function SegmentationLabPage() {
  const queryClient = useQueryClient();

  // Panel states
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [sidebarView, setSidebarView] = useState<"profiles" | "results">("profiles");

  // Profile management states
  const [editingProfile, setEditingProfile] = useState<SegmentationProfile | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isNewProfile, setIsNewProfile] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [formData, setFormData] = useState<Partial<SegmentationProfile>>(emptyProfile);
  const [originalFormData, setOriginalFormData] = useState<Partial<SegmentationProfile>>(emptyProfile);
  const [showDiscardWarning, setShowDiscardWarning] = useState(false);
  const [patternTestText, setPatternTestText] = useState("");
  const [patternTestResults, setPatternTestResults] = useState<PatternTestResult[]>([]);
  const [testingPatterns, setTestingPatterns] = useState(false);

  // Testing states
  const [file, setFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [groundTruth, setGroundTruth] = useState<string>("");
  const [expectedType, setExpectedType] = useState<string>("auto");
  const [splitBySections, setSplitBySections] = useState<boolean>(false);
  const [ocrMethod, setOcrMethod] = useState<string>("auto");
  const [error, setError] = useState<string | null>(null);
  const [expandedApproaches, setExpandedApproaches] = useState<Set<string>>(new Set());
  const [selectedSegment, setSelectedSegment] = useState<{
    approach: string;
    segmentIndex: number;
    pageStart: number;
    pageEnd: number;
  } | null>(null);
  const [currentPage, setCurrentPage] = useState(1);
  const [profileSearch, setProfileSearch] = useState("");
  const [landingProfileSearch, setLandingProfileSearch] = useState("");
  const [landingProfileTypeFilter, setLandingProfileTypeFilter] = useState("all");
  const [dialogSection, setDialogSection] = useState<"basic" | "veto" | "sections" | "test">("basic");
  const [dialogSidebarCollapsed, setDialogSidebarCollapsed] = useState(false);
  const [startKeywordConfidenceDrafts, setStartKeywordConfidenceDrafts] = useState<Record<number, string>>({});
  // Selected default detection method for the current profile
  const [selectedDefaultMethod, setSelectedDefaultMethod] = useState<string | null>(null);

  // Fetch profiles
  const { data: profiles, isLoading: profilesLoading } = useQuery({
    queryKey: ["segmentation-profiles"],
    queryFn: profileApi.getProfiles,
  });

  const filteredLandingProfiles = useMemo(() => {
    if (!profiles) return [];

    const searchTerm = landingProfileSearch.trim().toLowerCase();

    return profiles.filter((profile) => {
      const matchesSearch =
        !searchTerm ||
        profile.display_name.toLowerCase().includes(searchTerm) ||
        profile.name.toLowerCase().includes(searchTerm) ||
        profile.description?.toLowerCase().includes(searchTerm);

      const matchesType =
        landingProfileTypeFilter === "all" ||
        (landingProfileTypeFilter === "builtin" && profile.is_builtin) ||
        (landingProfileTypeFilter === "custom" && !profile.is_builtin);

      return matchesSearch && matchesType;
    });
  }, [profiles, landingProfileSearch, landingProfileTypeFilter]);

  // Mutations
  const createMutation = useMutation({
    mutationFn: profileApi.createProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["segmentation-profiles"] });
      toast({ title: "Profile created", description: "The profile has been created successfully." });
      setIsDialogOpen(false);
    },
    onError: (error: Error) => {
      toast({ title: "Failed to create", description: error.message, variant: "destructive" });
    },
  });

  const updateMutation = useMutation({
    mutationFn: ({ id, data }: { id: string; data: Partial<SegmentationProfile> }) =>
      profileApi.updateProfile(id, data),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["segmentation-profiles"] });
      toast({ title: "Profile updated", description: "The profile has been updated successfully." });
      setIsDialogOpen(false);
    },
    onError: (error: Error) => {
      toast({ title: "Failed to update", description: error.message, variant: "destructive" });
    },
  });

  const deleteMutation = useMutation({
    mutationFn: profileApi.deleteProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["segmentation-profiles"] });
      toast({ title: "Profile deleted", description: "The profile has been deleted." });
      setDeleteConfirmId(null);
    },
    onError: (error: Error) => {
      toast({ title: "Failed to delete", description: error.message, variant: "destructive" });
    },
  });

  // Document profiles for select
  const documentProfiles = [
    { value: "auto", label: "Auto-detect (default)", hasSections: false },
    ...(profiles?.map((p) => ({
      value: p.name,
      label: p.display_name,
      hasSections: (p.section_patterns?.length || 0) > 0,
    })) || []),
  ];

  // Profile handlers
  const handleNewProfile = () => {
    const newProfile = { ...emptyProfile };
    setFormData(newProfile);
    setOriginalFormData(newProfile);
    setStartKeywordConfidenceDrafts({});
    setIsNewProfile(true);
    setEditingProfile(null);
    setIsDialogOpen(true);
    setPatternTestResults([]);
    setDialogSection("basic");
  };

  const handleEditProfile = (profile: SegmentationProfile) => {
    // ocr_method is now stored in the database, use it directly from the profile
    const profileData = { ...profile, ocr_method: profile.ocr_method || "auto" };
    setFormData(profileData);
    setOriginalFormData(profileData);
    setStartKeywordConfidenceDrafts({});
    setIsNewProfile(false);
    setEditingProfile(profile);
    setIsDialogOpen(true);
    setPatternTestResults([]);
    setDialogSection("basic");
  };

  // Check if form has changes
  const hasFormChanges = () => {
    return JSON.stringify(formData) !== JSON.stringify(originalFormData);
  };
  const hasInvalidStartKeywordConfidenceDraft = Object.values(startKeywordConfidenceDrafts).some((draft) => {
    const parsed = Number(draft);
    return draft === "" || !Number.isFinite(parsed) || parsed < 0 || parsed > 1;
  });

  // Handle dialog close with unsaved changes check
  const handleDialogClose = () => {
    if (hasFormChanges()) {
      setShowDiscardWarning(true);
    } else {
      setIsDialogOpen(false);
    }
  };

  const confirmDiscard = () => {
    setShowDiscardWarning(false);
    setIsDialogOpen(false);
  };

  const handleSave = () => {
    const name = formData.name?.trim() ?? "";
    const displayName = formData.display_name?.trim() ?? "";
    if (!name || !displayName) {
      toast({
        title: "Missing required fields",
        description: "Please enter a profile ID and a display name.",
        variant: "destructive",
      });
      return;
    }
    // ocr_method is now stored in the database, send full formData
    if (isNewProfile) {
      createMutation.mutate({ ...formData, name, display_name: displayName });
    } else if (editingProfile) {
      updateMutation.mutate({ id: editingProfile.id, data: { ...formData, name, display_name: displayName } });
    }
  };

  const handleTestPatterns = async () => {
    if (!patternTestText.trim() || !formData.veto_fields?.length) return;
    setTestingPatterns(true);
    try {
      const results = await profileApi.testPatterns(formData.veto_fields, patternTestText);
      setPatternTestResults(results);
    } catch {
      toast({ title: "Test failed", description: "Failed to test patterns", variant: "destructive" });
    } finally {
      setTestingPatterns(false);
    }
  };

  // Veto field management
  const addVetoField = () => {
    setFormData(prev => ({
      ...prev,
      veto_fields: [...(prev.veto_fields || []), { name: "", pattern: "", bidirectional: false, enabled: true }],
    }));
  };

  const updateVetoField = (index: number, updates: Partial<VetoField>) => {
    setFormData(prev => ({
      ...prev,
      veto_fields: prev.veto_fields?.map((f, i) => (i === index ? { ...f, ...updates } : f)),
    }));
  };

  const removeVetoField = (index: number) => {
    setFormData(prev => ({
      ...prev,
      veto_fields: prev.veto_fields?.filter((_, i) => i !== index),
    }));
  };

  // Section pattern management
  const addSectionPattern = () => {
    setFormData(prev => ({
      ...prev,
      section_patterns: [...(prev.section_patterns || []), { pattern: "", capture_group: 1 }],
    }));
  };

  const updateSectionPattern = (index: number, updates: Partial<SectionPattern>) => {
    setFormData(prev => ({
      ...prev,
      section_patterns: prev.section_patterns?.map((p, i) => (i === index ? { ...p, ...updates } : p)),
    }));
  };

  const removeSectionPattern = (index: number) => {
    setFormData(prev => ({
      ...prev,
      section_patterns: prev.section_patterns?.filter((_, i) => i !== index),
    }));
  };

  // Start keyword management
  const addStartKeyword = () => {
    setFormData(prev => ({
      ...prev,
      start_keywords: [...(prev.start_keywords || []), { pattern: "", confidence: 0.75 }],
    }));
  };

  const updateStartKeyword = (index: number, updates: Partial<StartKeyword>) => {
    setFormData(prev => ({
      ...prev,
      start_keywords: prev.start_keywords?.map((k, i) => (i === index ? { ...k, ...updates } : k)),
    }));
  };

  const removeStartKeyword = (index: number) => {
    setFormData(prev => ({
      ...prev,
      start_keywords: prev.start_keywords?.filter((_, i) => i !== index),
    }));
    setStartKeywordConfidenceDrafts(prev => {
      const shifted: Record<number, string> = {};
      Object.entries(prev).forEach(([key, value]) => {
        const i = Number(key);
        if (i < index) shifted[i] = value;
        if (i > index) shifted[i - 1] = value;
      });
      return shifted;
    });
  };

  const uploadRejectionMessage = (rejections: FileRejection[]) => {
    const code = rejections[0]?.errors[0]?.code;
    if (code === "too-many-files") return "Please upload one PDF at a time.";
    if (code === "file-invalid-type") return "Only PDF files are supported.";
    return "This file could not be accepted.";
  };

  const isPdfFile = (f: File) =>
    f.type === "application/pdf" || /\.pdf$/i.test(f.name);

  // File upload
  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length === 0) return;
    const newFile = acceptedFiles[0];
    if (!isPdfFile(newFile)) {
      setError("Only PDF files are supported.");
      return;
    }
    setFile(newFile);
    setComparison(null);
    setError(null);
    setSelectedSegment(null);
    setExpandedApproaches(new Set());
    setCurrentPage(1);
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    onDropRejected: rejections => {
      setError(uploadRejectionMessage(rejections));
    },
    accept: { "application/pdf": [".pdf"] },
    maxFiles: 1,
  });

  // Run comparison
  const runComparison = async () => {
    if (!file) return;

    setIsProcessing(true);
    setError(null);
    setSidebarView("results"); // Switch to results view

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (groundTruth) {
        formData.append("ground_truth", groundTruth);
      }
      if (expectedType && expectedType !== "auto") {
        formData.append("expected_types", expectedType);
      }
      formData.append("split_by_sections", splitBySections.toString());
      formData.append("ocr_method", ocrMethod);

      const response = await fetch(`${API_BASE_URL}/api/extract/test-segmentation`, {
        method: "POST",
        headers: getAuthHeaders(),
        body: formData,
      });

      if (!response.ok) {
        const errorData = await response.json();
        throw new Error(errorData.detail || "Failed to run segmentation comparison");
      }

      const result = await response.json();
      setComparison(result);

      // Auto-expand the best performing approach
      if (result.results.length > 0) {
        const bestApproach = result.results.reduce((best: ApproachResult, r: ApproachResult) => {
          if (r.accuracy === null) return best;
          if (best.accuracy === null) return r;
          return r.accuracy > best.accuracy ? r : best;
        }, result.results[0]);
        setExpandedApproaches(new Set([bestApproach.approach]));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Unknown error");
    } finally {
      setIsProcessing(false);
    }
  };

  const toggleApproach = (approach: string) => {
    setExpandedApproaches(prev => {
      const next = new Set(prev);
      if (next.has(approach)) {
        next.delete(approach);
      } else {
        next.add(approach);
      }
      return next;
    });
  };

  const handleSegmentClick = (approach: string, segmentIndex: number, pageStart: number, pageEnd: number) => {
    setSelectedSegment({ approach, segmentIndex, pageStart, pageEnd });
    setCurrentPage(pageStart);
  };

  const handlePageChange = (page: number) => {
    setCurrentPage(page);
  };

  const getApproachIcon = (approach: string) => {
    if (approach.includes("Fingerprint")) return <Fingerprint className="h-4 w-4" />;
    if (approach.includes("Key Field")) return <Key className="h-4 w-4" />;
    if (approach.includes("Copy")) return <Copy className="h-4 w-4" />;
    if (approach.includes("TF-IDF")) return <BarChart3 className="h-4 w-4" />;
    if (approach.includes("MiniLM")) return <Brain className="h-4 w-4" />;
    if (approach.includes("VLM")) return <Eye className="h-4 w-4" />;
    if (approach.includes("Full")) return <Zap className="h-4 w-4" />;
    return <Layers className="h-4 w-4" />;
  };

  const getAccuracyColor = (accuracy: number | null) => {
    if (accuracy === null) return "text-muted-foreground";
    if (accuracy >= 0.9) return "text-emerald-600";
    if (accuracy >= 0.7) return "text-amber-600";
    return "text-red-600";
  };

  const getAccuracyBg = (accuracy: number | null) => {
    if (accuracy === null) return "bg-muted/50";
    if (accuracy >= 0.9) return "bg-emerald-50 dark:bg-emerald-950/30 border-emerald-200 dark:border-emerald-800";
    if (accuracy >= 0.7) return "bg-amber-50 dark:bg-amber-950/30 border-amber-200 dark:border-amber-800";
    return "bg-red-50 dark:bg-red-950/30 border-red-200 dark:border-red-800";
  };

  const isSegmentSelected = (approach: string, segmentIndex: number) => {
    return selectedSegment?.approach === approach && selectedSegment?.segmentIndex === segmentIndex;
  };

  const resetTest = () => {
    setFile(null);
    setComparison(null);
    setError(null);
    setSelectedSegment(null);
    setExpandedApproaches(new Set());
    setGroundTruth("");
    setExpectedType("auto");
    setSplitBySections(false);
    setCurrentPage(1);
  };

  // Render dialogs (shared between both views)
  const renderDialogs = () => (
    <>
      {/* Edit/Create Profile Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={(open) => {
        if (!open) {
          handleDialogClose();
        } else {
          setDialogSection("basic");
        }
      }}>
        <DialogContent className="h-[600px] max-h-[90vh] min-h-0 w-[800px] max-w-[95vw] overflow-hidden p-0">
          <div className="flex h-full min-h-0 max-h-full self-stretch">
            {/* Left Sidebar Navigation - Collapsible */}
            <div className={cn(
              "border-r bg-muted/30 flex min-h-0 flex-col transition-all duration-200",
              dialogSidebarCollapsed ? "w-14 shrink-0 p-2" : "w-44 shrink-0 p-3"
            )}>
              {!dialogSidebarCollapsed && (
                <div className="mb-3 shrink-0">
                  <h2 className="font-semibold text-sm">
                    {isNewProfile ? "New Profile" : "Edit Profile"}
                  </h2>
                </div>
              )}

              <nav className="min-h-0 flex-1 space-y-0.5 overflow-y-auto overscroll-contain">
                {[
                  { id: "basic", icon: FileText, label: "Basic", badge: undefined },
                  { id: "veto", icon: Key, label: "Veto Fields", badge: formData.veto_fields?.length },
                  { id: "sections", icon: SplitSquareVertical, label: "Sections", badge: formData.section_patterns?.length },
                  { id: "test", icon: FlaskConical, label: "Test", badge: undefined },
                ].map((item) => (
                  <button
                    key={item.id}
                    onClick={() => setDialogSection(item.id as typeof dialogSection)}
                    title={dialogSidebarCollapsed ? item.label : undefined}
                    className={cn(
                      "w-full flex items-center rounded-md transition-all text-sm",
                      dialogSidebarCollapsed ? "justify-center p-2" : "gap-2 px-2.5 py-2",
                      dialogSection === item.id
                        ? "bg-primary text-primary-foreground"
                        : "hover:bg-muted text-muted-foreground hover:text-foreground"
                    )}
                  >
                    <item.icon className="h-4 w-4 shrink-0" />
                    {!dialogSidebarCollapsed && (
                      <>
                        <span className="flex-1 text-left">{item.label}</span>
                        {item.badge !== undefined && item.badge > 0 && (
                          <span className={cn(
                            "text-[10px] px-1.5 py-0.5 rounded-full",
                            dialogSection === item.id
                              ? "bg-primary-foreground/20"
                              : "bg-muted-foreground/20"
                          )}>
                            {item.badge}
                          </span>
                        )}
                      </>
                    )}
                  </button>
                ))}
              </nav>

              {/* Collapse toggle */}
              <button
                onClick={() => setDialogSidebarCollapsed(!dialogSidebarCollapsed)}
                className="mb-2 shrink-0 rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
                title={dialogSidebarCollapsed ? "Expand sidebar" : "Collapse sidebar"}
              >
                {dialogSidebarCollapsed ? (
                  <PanelLeft className="h-4 w-4 mx-auto" />
                ) : (
                  <PanelLeftClose className="h-4 w-4" />
                )}
              </button>

              {/* Bottom Actions */}
              <div className={cn("shrink-0 border-t pt-2", dialogSidebarCollapsed ? "space-y-1" : "space-y-1.5")}>
                <Button
                  onClick={handleSave}
                  disabled={
                    createMutation.isPending ||
                    updateMutation.isPending ||
                    (!isNewProfile && !hasFormChanges()) ||
                    hasInvalidStartKeywordConfidenceDraft
                  }
                  className="w-full"
                  size="sm"
                >
                  {(createMutation.isPending || updateMutation.isPending) ? (
                    <Loader2 className="h-4 w-4 animate-spin" />
                  ) : dialogSidebarCollapsed ? (
                    <Save className="h-4 w-4" />
                  ) : (
                    <>
                      <Save className="h-4 w-4 mr-2" />
                      {isNewProfile ? "Create" : "Save"}
                    </>
                  )}
                </Button>
                {!dialogSidebarCollapsed && (
                  <Button
                    variant="ghost"
                    size="sm"
                    className="w-full text-xs"
                    onClick={handleDialogClose}
                  >
                    Cancel
                  </Button>
                )}
              </div>
            </div>

            {/* Main Content Area */}
            <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-4">
              {/* Basic Info Section */}
              {dialogSection === "basic" && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-base font-semibold">Basic Information</h3>
                    <p className="text-xs text-muted-foreground">
                      Set up the profile identity
                    </p>
                  </div>

                  <div className="grid gap-3">
                    <div className="grid grid-cols-2 gap-3">
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">Profile ID</Label>
                        <Input
                          value={formData.name || ""}
                          onChange={(e) => setFormData({ ...formData, name: e.target.value.toLowerCase().replace(/\s+/g, '_') })}
                          placeholder="bill_of_entry"
                          disabled={editingProfile?.is_builtin}
                          className="font-mono h-9"
                        />
                      </div>
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">Display Name</Label>
                        <Input
                          value={formData.display_name || ""}
                          onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                          placeholder="Bill of Entry"
                          className="h-9"
                        />
                      </div>
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">Description</Label>
                      <Textarea
                        value={formData.description || ""}
                        onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                        placeholder="Describe what types of documents this profile handles..."
                        rows={2}
                        className="resize-none"
                      />
                    </div>

                    <div className="flex items-center justify-between p-3 rounded-lg bg-muted/50 border border-dashed">
                      <div className="flex items-center gap-2">
                        <SplitSquareVertical className="h-4 w-4 text-muted-foreground" />
                        <div>
                          <p className="text-sm font-medium">Section Splitting</p>
                          <p className="text-xs text-muted-foreground">
                            Split into parts (PART I, II, III)
                          </p>
                        </div>
                      </div>
                      <Switch
                        checked={formData.enable_section_splitting || false}
                        onCheckedChange={(v) => setFormData({ ...formData, enable_section_splitting: v })}
                      />
                    </div>

                    <div className="space-y-1.5">
                      <Label className="text-xs font-medium">OCR Method</Label>
                      <Select
                        value={formData.ocr_method || "auto"}
                        onValueChange={(v) => setFormData({ ...formData, ocr_method: v })}
                      >
                        <SelectTrigger className="h-9">
                          <SelectValue />
                        </SelectTrigger>
                        <SelectContent>
                          {OCR_METHODS.map((method) => (
                            <SelectItem key={method.value} value={method.value}>
                              {method.label}
                            </SelectItem>
                          ))}
                        </SelectContent>
                      </Select>
                      <p className="text-xs text-muted-foreground">
                        Text extraction method for this document type
                      </p>
                    </div>

                    {/* Default Detection Method - Pills */}
                    <div className="space-y-2">
                      <Label className="text-xs font-medium">Default Detection Method</Label>
                      <div className="flex flex-wrap gap-1.5">
                        {[
                          { value: "Heuristics Only", icon: Layers, color: "blue" },
                          { value: "Heuristics + Negative", icon: Layers, color: "indigo" },
                          { value: "Full ML-Enhanced (TF-IDF)", icon: BarChart3, color: "purple" },
                          { value: "Full ML-Enhanced (MiniLM)", icon: Brain, color: "pink" },
                          { value: "VLM Pairwise (Azure Vision)", icon: Eye, color: "cyan" },
                        ].map((method) => {
                          const isSelected = formData.default_detection_method === method.value;
                          const Icon = method.icon;
                          return (
                            <button
                              key={method.value}
                              type="button"
                              onClick={() => setFormData({
                                ...formData,
                                default_detection_method: isSelected ? null : method.value
                              })}
                              className={cn(
                                "inline-flex items-center gap-1.5 px-2.5 py-1.5 rounded-full text-xs font-medium transition-all",
                                isSelected
                                  ? "bg-emerald-100 dark:bg-emerald-900/40 text-emerald-700 dark:text-emerald-300 ring-2 ring-emerald-500"
                                  : "bg-muted hover:bg-muted/80 text-muted-foreground hover:text-foreground"
                              )}
                            >
                              <Icon className={cn(
                                "h-3 w-3",
                                isSelected ? "text-emerald-600" : `text-${method.color}-500`
                              )} />
                              {method.value
                                .replace("Full ML-Enhanced ", "")
                                .replace("VLM Pairwise (Azure Vision)", "VLM (Azure Vision)")}
                              {isSelected && <CheckCircle2 className="h-3 w-3 text-emerald-600" />}
                            </button>
                          );
                        })}
                      </div>
                      <p className="text-xs text-muted-foreground">
                        Click to select • Click again to deselect
                      </p>
                    </div>
                  </div>
                </div>
              )}

              {/* Veto Fields Section */}
              {dialogSection === "veto" && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-base font-semibold">Veto Fields</h3>
                    <p className="text-xs text-muted-foreground">
                      Prevent splitting when matching values found
                    </p>
                  </div>

                  <div className="p-2.5 rounded-lg bg-blue-50/50 dark:bg-blue-950/20 border border-blue-200 dark:border-blue-900">
                    <div className="flex gap-2">
                      <Info className="h-4 w-4 text-blue-600 dark:text-blue-400 shrink-0 mt-0.5" />
                      <p className="text-xs text-blue-700 dark:text-blue-300">
                        Same value on consecutive pages = kept together as one document
                      </p>
                    </div>
                  </div>

                  <div className="space-y-2">
                    {formData.veto_fields?.map((field, index) => (
                      <div key={index} className="group p-3 rounded-lg border bg-card">
                        <div className="flex items-center gap-3">
                          <div className="flex-1 grid grid-cols-[140px_1fr] gap-3">
                            <Input
                              value={field.name}
                              onChange={(e) => updateVetoField(index, { name: e.target.value })}
                              placeholder="Field name"
                              className="h-9 text-sm"
                            />
                            <Input
                              value={field.pattern}
                              onChange={(e) => updateVetoField(index, { pattern: e.target.value })}
                              placeholder="Regex pattern"
                              className="h-9 font-mono text-sm"
                            />
                          </div>
                          <div className="flex items-center gap-4 shrink-0 border-l pl-3">
                            <label className="flex items-center gap-1.5 cursor-pointer" title="Bidirectional matching">
                              <Switch
                                checked={field.bidirectional}
                                onCheckedChange={(v) => updateVetoField(index, { bidirectional: v })}
                              />
                              <span className="text-xs text-muted-foreground">Bi-dir</span>
                            </label>
                            <label className="flex items-center gap-1.5 cursor-pointer" title="Enable this field">
                              <Switch
                                checked={field.enabled}
                                onCheckedChange={(v) => updateVetoField(index, { enabled: v })}
                              />
                              <span className="text-xs text-muted-foreground">On</span>
                            </label>
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => removeVetoField(index)}
                            className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 text-destructive hover:text-destructive"
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    ))}

                    <Button
                      variant="outline"
                      onClick={addVetoField}
                      size="sm"
                      className="w-full border-dashed"
                    >
                      <Plus className="h-3.5 w-3.5 mr-1.5" />
                      Add Veto Field
                    </Button>
                  </div>
                </div>
              )}

              {/* Sections Section */}
              {dialogSection === "sections" && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-base font-semibold">Section Patterns</h3>
                    <p className="text-xs text-muted-foreground">
                      Detect document sections (PART I, II)
                    </p>
                  </div>

                  <div className="space-y-2">
                    {formData.section_patterns?.map((pattern, index) => (
                      <div key={index} className="group p-2.5 rounded-lg border bg-card">
                        <div className="flex items-center gap-2">
                          <div className="flex-1 grid grid-cols-3 gap-2">
                            <Input
                              value={pattern.pattern}
                              onChange={(e) => updateSectionPattern(index, { pattern: e.target.value })}
                              placeholder="Regex pattern"
                              className="h-8 font-mono text-xs col-span-2"
                            />
                            <Input
                              type="number"
                              value={pattern.capture_group}
                              onChange={(e) => updateSectionPattern(index, { capture_group: parseInt(e.target.value) || 1 })}
                              min={1}
                              placeholder="Group"
                              className="h-8 text-sm"
                            />
                          </div>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => removeSectionPattern(index)}
                            className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 text-destructive hover:text-destructive"
                          >
                            <X className="h-3.5 w-3.5" />
                          </Button>
                        </div>
                      </div>
                    ))}

                    <Button
                      variant="outline"
                      onClick={addSectionPattern}
                      size="sm"
                      className="w-full border-dashed"
                    >
                      <Plus className="h-3.5 w-3.5 mr-1.5" />
                      Add Section Pattern
                    </Button>
                  </div>

                  <div className="h-px bg-border my-3" />

                  <div>
                    <h3 className="text-sm font-semibold mb-2">Start Keywords</h3>

                    <div className="space-y-2">
                      {formData.start_keywords?.map((keyword, index) => (
                        <div key={index} className="group p-2.5 rounded-lg border bg-card">
                          {(() => {
                            const draft = startKeywordConfidenceDrafts[index];
                            const parsed = draft !== undefined ? Number(draft) : keyword.confidence;
                            const isInvalid =
                              draft !== undefined &&
                              (draft === "" || !Number.isFinite(parsed) || parsed < 0 || parsed > 1);
                            const inputValue = draft ?? String(keyword.confidence);
                            return (
                          <div className="flex items-center gap-2">
                            <div className="flex-1 grid grid-cols-3 gap-2">
                              <Input
                                value={keyword.pattern}
                                onChange={(e) => updateStartKeyword(index, { pattern: e.target.value })}
                                placeholder="Pattern"
                                className="h-8 font-mono text-xs col-span-2"
                              />
                              <Input
                                type="number"
                                value={inputValue}
                                onChange={(e) => {
                                  const rawValue = e.target.value;
                                  setStartKeywordConfidenceDrafts(prev => ({ ...prev, [index]: rawValue }));
                                  const value = Number(rawValue);
                                  if (rawValue === "" || !Number.isFinite(value) || value < 0 || value > 1) {
                                    return;
                                  }
                                  updateStartKeyword(index, { confidence: value });
                                }}
                                onBlur={() => {
                                  const draft = startKeywordConfidenceDrafts[index];
                                  if (draft === undefined) return;
                                  const parsed = Number(draft);
                                  if (draft !== "" && Number.isFinite(parsed) && parsed >= 0 && parsed <= 1) {
                                    updateStartKeyword(index, { confidence: parsed });
                                  }
                                  setStartKeywordConfidenceDrafts(prev => {
                                    const { [index]: _removed, ...rest } = prev;
                                    return rest;
                                  });
                                }}
                                min={0}
                                max={1}
                                step={0.05}
                                placeholder="Conf"
                                className={cn(
                                  "h-8 text-sm",
                                  isInvalid && "border-destructive focus-visible:ring-destructive"
                                )}
                              />
                              <span className={cn(
                                "text-[10px] leading-tight col-start-3",
                                isInvalid ? "text-destructive" : "text-muted-foreground"
                              )}>
                                Only values from 0 to 1 are allowed.
                              </span>
                            </div>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={() => removeStartKeyword(index)}
                              className="h-6 w-6 p-0 opacity-0 group-hover:opacity-100 text-destructive hover:text-destructive"
                            >
                              <X className="h-3.5 w-3.5" />
                            </Button>
                          </div>
                            );
                          })()}
                        </div>
                      ))}

                      <Button
                        variant="outline"
                        onClick={addStartKeyword}
                        size="sm"
                        className="w-full border-dashed"
                      >
                        <Plus className="h-3.5 w-3.5 mr-1.5" />
                        Add Start Keyword
                      </Button>
                    </div>
                  </div>
                </div>
              )}

              {/* Test Section */}
              {dialogSection === "test" && (
                <div className="space-y-4">
                  <div>
                    <h3 className="text-base font-semibold">Test Patterns</h3>
                    <p className="text-xs text-muted-foreground">
                      Validate patterns against sample text
                    </p>
                  </div>

                  <div className="space-y-3">
                    <div>
                      <Label className="text-xs font-medium mb-1.5 block">Sample Document Text</Label>
                      <Textarea
                        value={patternTestText}
                        onChange={(e) => setPatternTestText(e.target.value)}
                        placeholder="Paste a sample from your document here..."
                        rows={6}
                        className="font-mono text-xs resize-none"
                      />
                    </div>

                    <Button
                      onClick={handleTestPatterns}
                      disabled={testingPatterns || !patternTestText.trim() || !formData.veto_fields?.length}
                      size="sm"
                      className="w-full"
                    >
                      {testingPatterns ? (
                        <Loader2 className="h-3.5 w-3.5 mr-1.5 animate-spin" />
                      ) : (
                        <FlaskConical className="h-3.5 w-3.5 mr-1.5" />
                      )}
                      Run Pattern Test
                    </Button>

                    {patternTestResults.length > 0 && (
                      <div className="space-y-1.5">
                        <Label className="text-xs font-medium">Results</Label>
                        {patternTestResults.map((result, i) => (
                          <div key={i} className={cn(
                            "flex items-center gap-2 p-2 rounded-md text-xs",
                            result.matched
                              ? "bg-green-50 dark:bg-green-950/30"
                              : "bg-red-50 dark:bg-red-950/30"
                          )}>
                            {result.matched ? (
                              <CheckCircle2 className="h-3.5 w-3.5 text-green-600 shrink-0" />
                            ) : (
                              <XCircle className="h-3.5 w-3.5 text-red-500 shrink-0" />
                            )}
                            <span className="font-medium">{result.field_name}</span>
                            {result.matched ? (
                              <code className="bg-green-100 dark:bg-green-900/50 px-1.5 py-0.5 rounded font-mono">
                                {result.value}
                              </code>
                            ) : result.error ? (
                              <span className="text-red-600">{result.error}</span>
                            ) : (
                              <span className="text-muted-foreground">No match</span>
                            )}
                          </div>
                        ))}
                      </div>
                    )}
                  </div>
                </div>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>

      {/* Delete Confirmation */}
      <AlertDialog open={!!deleteConfirmId} onOpenChange={() => setDeleteConfirmId(null)}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Delete Profile?</AlertDialogTitle>
            <AlertDialogDescription>
              This action cannot be undone. The profile will be permanently deleted.
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Cancel</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => deleteConfirmId && deleteMutation.mutate(deleteConfirmId)}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              {deleteMutation.isPending && <Loader2 className="h-4 w-4 mr-2 animate-spin" />}
              Delete
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>

      {/* Discard Changes Warning */}
      <AlertDialog open={showDiscardWarning} onOpenChange={setShowDiscardWarning}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Discard changes?</AlertDialogTitle>
            <AlertDialogDescription>
              You have unsaved changes. Are you sure you want to close without saving?
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>Keep editing</AlertDialogCancel>
            <AlertDialogAction
              onClick={confirmDiscard}
              className="bg-destructive text-destructive-foreground hover:bg-destructive/90"
            >
              Discard
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </>
  );

  // Landing view (no file selected)
  if (!file) {
    return (
      <div className="container mx-auto py-6 px-4 max-w-6xl">
        {/* Header */}
        <div className="flex items-center gap-3 mb-8">
          <FlaskConical className="h-8 w-8 text-purple-500" />
          <div>
            <h1 className="text-2xl font-bold">Segmentation Lab</h1>
            <p className="text-sm text-muted-foreground">
              Test, compare, and configure document segmentation
            </p>
          </div>
        </div>

        {/* Upload Area */}
        <div
          {...getRootProps()}
          className={cn(
            "w-full max-w-2xl mx-auto border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors mb-8",
            isDragActive
              ? "border-primary bg-primary/5"
              : "border-muted-foreground/25 hover:border-primary/50 bg-background"
          )}
        >
          <input {...getInputProps()} id="file-upload" />
          <Upload className="h-12 w-12 mx-auto mb-3 text-muted-foreground" />
          <p className="font-semibold text-lg mb-1">Drag & drop a PDF here</p>
          <p className="text-sm text-muted-foreground mb-4">or click to select a file</p>
          <div className="flex flex-wrap justify-center gap-2">
            {[
              { icon: Layers, name: "Heuristics", color: "text-blue-500" },
              { icon: Fingerprint, name: "SimHash", color: "text-green-500" },
              { icon: BarChart3, name: "TF-IDF", color: "text-purple-500" },
              { icon: Brain, name: "MiniLM", color: "text-pink-500" },
            ].map(({ icon: Icon, name, color }) => (
              <div key={name} className="flex items-center gap-1.5 px-2 py-1 border rounded text-xs bg-muted/50">
                <Icon className={cn("h-3 w-3", color)} />
                <span>{name}</span>
              </div>
            ))}
          </div>
        </div>

        {error && (
          <div className="max-w-2xl mx-auto mb-6 rounded-md border border-destructive/30 bg-destructive/10 p-3 flex items-center gap-2 text-destructive text-sm">
            <AlertTriangle className="h-4 w-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Profiles Section */}
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-2">
            <Database className="h-4 w-4 text-muted-foreground" />
            <h2 className="font-semibold">Segmentation Profiles</h2>
            <Badge variant="secondary" className="text-xs">
              {profiles?.length || 0}
            </Badge>
          </div>
          <Button variant="outline" size="sm" onClick={handleNewProfile}>
            <Plus className="h-4 w-4 mr-1" />
            New Profile
          </Button>
        </div>

        <div className="flex items-center gap-4 mb-6">
          <div className="relative flex-1 max-w-sm">
            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
            <Input
              placeholder="Search profiles..."
              value={landingProfileSearch}
              onChange={(e) => setLandingProfileSearch(e.target.value)}
              className="pl-9"
            />
          </div>
          <Select value={landingProfileTypeFilter} onValueChange={setLandingProfileTypeFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="All Types" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              <SelectItem value="builtin">Built-in</SelectItem>
              <SelectItem value="custom">Custom</SelectItem>
            </SelectContent>
          </Select>
        </div>

        {profilesLoading ? (
          <div className="flex justify-center py-8">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        ) : filteredLandingProfiles.length > 0 ? (
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {filteredLandingProfiles.map((profile) => (
              <Card
                key={profile.id}
                className="hover:shadow-md cursor-pointer transition-shadow group"
                onClick={() => handleEditProfile(profile)}
              >
                <CardContent className="p-4">
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <span className="font-medium truncate">{profile.display_name}</span>
                        {profile.is_builtin && (
                          <Shield className="h-3.5 w-3.5 text-muted-foreground shrink-0" />
                        )}
                      </div>
                      {profile.description && (
                        <p className="text-xs text-muted-foreground line-clamp-2 mb-2">
                          {profile.description}
                        </p>
                      )}
                      <div className="flex flex-wrap gap-1.5">
                        {profile.veto_fields.length > 0 && (
                          <Badge variant="outline" className="text-[10px] h-5">
                            <Key className="h-2.5 w-2.5 mr-1" />
                            {profile.veto_fields.length} veto
                          </Badge>
                        )}
                        {profile.section_patterns.length > 0 && (
                          <Badge variant="outline" className="text-[10px] h-5">
                            <SplitSquareVertical className="h-2.5 w-2.5 mr-1" />
                            {profile.section_patterns.length} sections
                          </Badge>
                        )}
                        {profile.start_keywords.length > 0 && (
                          <Badge variant="outline" className="text-[10px] h-5">
                            <Zap className="h-2.5 w-2.5 mr-1" />
                            {profile.start_keywords.length} keywords
                          </Badge>
                        )}
                      </div>
                    </div>
                    <Pencil className="h-3.5 w-3.5 text-muted-foreground opacity-0 group-hover:opacity-100 transition-opacity shrink-0 ml-2" />
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        ) : (
          <div className="text-center py-8 text-muted-foreground text-sm">
            {profiles && profiles.length > 0
              ? "No matching profiles found. Try adjusting your filters or search terms."
              : "No profiles yet. Create one to customize document boundary detection."}
          </div>
        )}

        {/* Dialogs need to be included in this return */}
        {renderDialogs()}
      </div>
    );
  }

  // File selected view
  return (
    <div className="absolute inset-0 flex flex-col">
      {/* Header bar when file is selected */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-background shrink-0">
        <div className="flex items-center gap-2">
          <FlaskConical className="h-4 w-4 text-purple-500" />
          <span className="font-medium text-sm">Segmentation Lab</span>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="font-mono text-xs">
            {file.name}
          </Badge>
          <label
            htmlFor="header-file-upload"
            className="inline-flex items-center justify-center gap-1.5 px-2 h-7 text-xs font-medium rounded-md border border-input bg-background hover:bg-accent hover:text-accent-foreground cursor-pointer transition-colors"
          >
            <Upload className="h-3 w-3" />
            Upload
            <input
              id="header-file-upload"
              type="file"
              accept=".pdf"
              className="sr-only"
              onChange={(e) => {
                const selectedFile = e.target.files?.[0];
                if (selectedFile) {
                  if (!isPdfFile(selectedFile)) {
                    setError("Only PDF files are supported.");
                  } else {
                    onDrop([selectedFile]);
                  }
                }
                e.target.value = "";
              }}
            />
          </label>
          <Button variant="outline" size="sm" onClick={resetTest} className="h-7 text-xs">
            <RotateCcw className="h-3 w-3 mr-1" />
            New Test
          </Button>
        </div>
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Sidebar - Profiles & Results */}
        <div
          className={cn(
            "bg-background flex flex-col transition-all duration-200 shrink-0",
            rightPanelOpen ? "w-96" : "w-0 overflow-hidden"
          )}
        >
          {/* Tabs Header */}
          <div className="flex-none flex items-center h-10">
            <button
              onClick={() => setSidebarView("profiles")}
              className={cn(
                "flex-1 h-full flex items-center justify-center gap-1.5 text-sm font-medium transition-colors border-b-2",
                sidebarView === "profiles"
                  ? "border-b-primary text-foreground"
                  : "border-b-transparent text-muted-foreground hover:text-foreground"
              )}
            >
              <Database className="h-3.5 w-3.5" />
              Profiles
            </button>
            <button
              onClick={() => setSidebarView("results")}
              className={cn(
                "flex-1 h-full flex items-center justify-center gap-1.5 text-sm font-medium transition-colors border-b-2",
                sidebarView === "results"
                  ? "border-b-primary text-foreground"
                  : "border-b-transparent text-muted-foreground hover:text-foreground",
                !comparison && !isProcessing && "opacity-50"
              )}
            >
              <BarChart3 className="h-3.5 w-3.5" />
              Results
              {isProcessing && (
                <span className="relative flex h-2 w-2">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-500 opacity-75"></span>
                  <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                </span>
              )}
            </button>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => setRightPanelOpen(!rightPanelOpen)}
              className="h-10 w-8 p-0 rounded-none"
            >
              <PanelLeftClose className="h-4 w-4" />
            </Button>
          </div>

          {/* Profiles View */}
          {sidebarView === "profiles" && (
            <>
              {/* Header Actions */}
              <div className="flex-none flex items-center justify-between py-2.5 px-3">
                <div className="relative flex-1 mr-3">
                  <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                  <Input
                    value={profileSearch}
                    onChange={(e) => setProfileSearch(e.target.value)}
                    placeholder="Search..."
                    className="h-8 text-xs pl-8"
                  />
                </div>
                <div className="flex items-center gap-1.5">
                  <Button
                    size="sm"
                    onClick={runComparison}
                    className="h-8 px-3 text-xs gap-1.5 bg-emerald-600 hover:bg-emerald-700 text-white"
                    disabled={!file || isProcessing}
                  >
                    {isProcessing ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    ) : (
                      <Play className="h-3.5 w-3.5" />
                    )}
                    Run
                  </Button>
                  <Button variant="ghost" size="sm" onClick={handleNewProfile} className="h-8 w-8 p-0">
                    <Plus className="h-3.5 w-3.5" />
                  </Button>
                </div>
              </div>

          {/* Profile List */}
          <ScrollArea className="flex-1">
            <div className="p-2 pt-0 space-y-0.5">
              {/* Auto-detect option */}
              <button
                onClick={() => {
                  setExpectedType("auto");
                  setOcrMethod("auto");
                  setSplitBySections(false);
                  setSelectedDefaultMethod(null);
                }}
                className={cn(
                  "w-full text-left p-2.5 rounded-lg transition-all",
                  expectedType === "auto"
                    ? "bg-blue-50 dark:bg-blue-950/30 border-l-2 border-l-blue-500"
                    : "hover:bg-muted border-l-2 border-l-transparent"
                )}
              >
                <div className="text-sm font-medium">Auto-detect</div>
                <div className="text-xs text-muted-foreground">
                  Automatically detect document type
                </div>
              </button>

              {profilesLoading ? (
                <div className="flex justify-center py-4">
                  <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                </div>
              ) : (
                profiles
                  ?.filter(profile =>
                    !profileSearch ||
                    profile.display_name.toLowerCase().includes(profileSearch.toLowerCase()) ||
                    profile.description?.toLowerCase().includes(profileSearch.toLowerCase())
                  )
                  .map((profile) => (
                  <button
                    key={profile.id}
                    onClick={() => {
                      setExpectedType(profile.name);
                      // Use OCR method from profile (stored in database)
                      setOcrMethod(profile.ocr_method || "auto");
                      setSplitBySections(profile.enable_section_splitting);
                      // Load the default detection method from profile
                      setSelectedDefaultMethod(profile.default_detection_method || null);
                    }}
                    className={cn(
                      "w-full text-left p-2.5 rounded-lg transition-all group",
                      expectedType === profile.name
                        ? "bg-blue-50 dark:bg-blue-950/30 border-l-2 border-l-blue-500"
                        : "hover:bg-muted border-l-2 border-l-transparent"
                    )}
                  >
                    <div className="flex items-center justify-between">
                      <div className="flex items-center gap-1.5">
                        <span className="text-sm font-medium">{profile.display_name}</span>
                        {profile.is_builtin && (
                          <Shield className="h-3 w-3 text-muted-foreground" />
                        )}
                      </div>
                      <Pencil
                        className="h-3 w-3 opacity-0 group-hover:opacity-100 transition-opacity cursor-pointer text-muted-foreground hover:text-foreground"
                        onClick={(e) => {
                          e.stopPropagation();
                          handleEditProfile(profile);
                        }}
                      />
                    </div>
                    <div className="text-xs text-muted-foreground flex items-center gap-1.5">
                      <span>{profile.veto_fields.length} veto, {profile.section_patterns.length} sections</span>
                      {profile.default_detection_method && (
                        <span className="inline-flex items-center gap-0.5 px-1.5 py-0.5 rounded-full bg-emerald-100 dark:bg-emerald-900/30 text-emerald-700 dark:text-emerald-400 text-[9px]">
                          <Target className="h-2.5 w-2.5" />
                          {profile.default_detection_method
                            .replace("Full ML-Enhanced ", "")
                            .replace("Heuristics + Negative", "Heur+Neg")
                            .replace("Heuristics Only", "Heuristics")}
                        </span>
                      )}
                    </div>
                  </button>
                ))
              )}
            </div>
          </ScrollArea>
            </>
          )}

          {/* Results View */}
          {sidebarView === "results" && (
            <ScrollArea className="flex-1">
              {isProcessing ? (
                /* Processing Animation */
                <div className="flex flex-col items-center justify-center h-full min-h-[300px] p-6">
                  <div className="relative flex items-center justify-center w-14 h-14">
                    {/* Spinning segment with gradient effect */}
                    <svg
                      className="w-14 h-14 animate-spin"
                      viewBox="0 0 56 56"
                    >
                      <defs>
                        <linearGradient id="spinnerGradient" x1="0%" y1="0%" x2="100%" y2="0%">
                          <stop offset="0%" stopColor="#3b82f6" stopOpacity="1" />
                          <stop offset="60%" stopColor="#60a5fa" stopOpacity="0.6" />
                          <stop offset="100%" stopColor="#3b82f6" stopOpacity="0.1" />
                        </linearGradient>
                      </defs>
                      <circle
                        cx="28"
                        cy="28"
                        r="24"
                        fill="none"
                        stroke="url(#spinnerGradient)"
                        strokeWidth="2.5"
                        strokeLinecap="round"
                        strokeDasharray="90 60"
                      />
                    </svg>
                    {/* Inner icon */}
                    <div className="absolute inset-0 flex items-center justify-center">
                      <Layers className="h-5 w-5 text-blue-500" />
                    </div>
                  </div>
                  <div className="mt-5 text-center">
                    <p className="font-medium text-sm">Segmenting Document</p>
                    <p className="text-xs text-muted-foreground mt-1">
                      Using {expectedType === "auto" ? "Auto-detect" : profiles?.find(p => p.name === expectedType)?.display_name || expectedType}
                    </p>
                  </div>
                  <div className="mt-3 flex items-center gap-1">
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: "0ms" }} />
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: "150ms" }} />
                    <div className="w-1.5 h-1.5 rounded-full bg-blue-500 animate-bounce" style={{ animationDelay: "300ms" }} />
                  </div>
                </div>
              ) : comparison ? (
                /* Results */
                (() => {
                  const filteredResults = comparison.results.filter(
                    (result) => !["SimHash Fingerprint", "Key Field Continuity", "Copy Indicator", "TF-IDF Similarity"].includes(result.approach)
                  );
                  return (
                <div className="p-3 space-y-3">
                  {/* Summary Stats */}
                  <div className="grid grid-cols-2 gap-2">
                    <div className="bg-blue-50 dark:bg-blue-950/30 rounded-lg p-3 text-center">
                      <div className="text-2xl font-bold text-blue-600">{comparison.total_pages}</div>
                      <div className="text-xs text-muted-foreground">Pages</div>
                    </div>
                    <div className="bg-green-50 dark:bg-green-950/30 rounded-lg p-3 text-center">
                      <div className="text-2xl font-bold text-green-600">{filteredResults[0]?.segments.length || 0}</div>
                      <div className="text-xs text-muted-foreground">Segments</div>
                    </div>
                  </div>

                  <div className="flex items-center justify-between pt-2">
                    <span className="text-xs font-medium text-muted-foreground">Detection Methods</span>
                    {selectedDefaultMethod && expectedType !== "auto" && (
                      <Badge variant="outline" className="text-[9px] h-4 px-1.5 bg-emerald-50 text-emerald-700 border-emerald-200">
                        Default set
                      </Badge>
                    )}
                  </div>
                  {filteredResults.map((result, idx) => {
                    const isDefault = selectedDefaultMethod === result.approach;
                    return (
                      <Collapsible
                        key={idx}
                        open={expandedApproaches.has(result.approach)}
                        onOpenChange={() => toggleApproach(result.approach)}
                      >
                        <Card className={cn(
                          "transition-colors",
                          isDefault ? "ring-2 ring-emerald-500 bg-emerald-50/50 dark:bg-emerald-950/20" : getAccuracyBg(result.accuracy)
                        )}>
                          <CollapsibleTrigger asChild>
                            <CardHeader className="py-2 px-3 cursor-pointer hover:bg-black/5">
                              <div className="flex items-center justify-between">
                                <div className="flex items-center gap-1.5">
                                  {expandedApproaches.has(result.approach) ? (
                                    <ChevronDown className="h-3 w-3 text-muted-foreground" />
                                  ) : (
                                    <ChevronRight className="h-3 w-3 text-muted-foreground" />
                                  )}
                                  {getApproachIcon(result.approach)}
                                  <span className="font-medium text-xs">{result.approach}</span>
                                  {isDefault && (
                                    <CheckCircle2 className="h-3 w-3 text-emerald-600" />
                                  )}
                                </div>
                                <div className="flex items-center gap-1.5">
                                  <Badge variant="secondary" className="text-[10px] h-5">
                                    {result.segments.length}
                                  </Badge>
                                  {/* Toggle to set as default */}
                                  {expectedType !== "auto" && (
                                    <button
                                      onClick={(e) => {
                                        e.stopPropagation();
                                        const newMethod = isDefault ? null : result.approach;
                                        setSelectedDefaultMethod(newMethod);
                                        // Save to profile immediately
                                        const profile = profiles?.find(p => p.name === expectedType);
                                        if (profile) {
                                          updateMutation.mutate({
                                            id: profile.id,
                                            data: { ...profile, default_detection_method: newMethod },
                                          });
                                        }
                                      }}
                                      className={cn(
                                        "w-5 h-5 rounded-full border-2 flex items-center justify-center transition-all",
                                        isDefault
                                          ? "border-emerald-500 bg-emerald-500"
                                          : "border-muted-foreground/30 hover:border-emerald-500/50"
                                      )}
                                      title={isDefault ? "Remove as default" : "Set as default method"}
                                    >
                                      {isDefault && (
                                        <CheckCircle2 className="h-3 w-3 text-white" />
                                      )}
                                    </button>
                                  )}
                                </div>
                              </div>
                            </CardHeader>
                          </CollapsibleTrigger>
                          <CollapsibleContent>
                            <CardContent className="px-3 pb-2 pt-0 space-y-2">
                              {result.accuracy !== null && (
                                <div className="flex justify-between text-xs">
                                  <span>Accuracy</span>
                                  <span className={cn("font-medium", getAccuracyColor(result.accuracy))}>
                                    {(result.accuracy * 100).toFixed(1)}%
                                  </span>
                                </div>
                              )}
                              {result.metadata &&
                                typeof result.metadata.reason === "string" && (
                                  <p className="text-[10px] text-muted-foreground leading-snug">
                                    {result.metadata.reason}
                                  </p>
                                )}
                              {result.metadata &&
                                typeof result.metadata.error === "string" && (
                                  <p className="text-[10px] text-destructive/90 leading-snug">
                                    {result.metadata.error}
                                  </p>
                                )}
                              {result.metadata &&
                                typeof result.metadata.total_tokens === "number" && (
                                  <p className="text-[10px] text-muted-foreground">
                                    Vision tokens (approx.): {result.metadata.total_tokens}
                                  </p>
                                )}
                              <div className="flex flex-wrap gap-1">
                                {result.segments.map(([start, end], i) => (
                                  <Badge
                                    key={i}
                                    variant={isSegmentSelected(result.approach, i) ? "default" : "outline"}
                                    className="cursor-pointer text-[10px]"
                                    onClick={() => handleSegmentClick(result.approach, i, start, end)}
                                  >
                                    {start === end ? `P${start}` : `${start}-${end}`}
                                  </Badge>
                                ))}
                              </div>
                            </CardContent>
                          </CollapsibleContent>
                        </Card>
                      </Collapsible>
                    );
                  })}
                </div>
                  );
                })()
              ) : (
                /* No results yet */
                <div className="flex flex-col items-center justify-center h-full min-h-[200px] p-6 text-center">
                  <BarChart3 className="h-10 w-10 text-muted-foreground/30 mb-3" />
                  <p className="text-sm text-muted-foreground">No results yet</p>
                  <p className="text-xs text-muted-foreground mt-1">Select a profile and click Run</p>
                </div>
              )}
            </ScrollArea>
          )}
        </div>

        {/* Main Area - PDF Viewer */}
        <div className="flex-1 flex flex-col min-w-0">
          {/* Error */}
          {error && (
            <div className="shrink-0 border-b bg-destructive/10 p-2 flex items-center gap-2 text-destructive text-sm">
              <AlertTriangle className="h-4 w-4" />
              <span>{error}</span>
            </div>
          )}

          {/* Segment selection indicator */}
          {selectedSegment && (
            <div className="shrink-0 px-3 py-2 border-b bg-primary/5 flex items-center justify-between">
              <div className="flex items-center gap-2">
                <Target className="h-4 w-4 text-primary" />
                <span className="text-sm font-medium">
                  {selectedSegment.approach} - Segment {selectedSegment.segmentIndex + 1}
                </span>
              </div>
              <Badge>Pages {selectedSegment.pageStart}-{selectedSegment.pageEnd}</Badge>
            </div>
          )}

          {/* PDF Viewer */}
          <div className="flex-1 min-h-0 bg-neutral-100 dark:bg-neutral-900 relative">
            {/* Sidebar toggle when collapsed */}
            {!rightPanelOpen && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => setRightPanelOpen(true)}
                className="absolute top-2 left-2 z-10 h-8 w-8 p-0 bg-background/80 backdrop-blur-sm shadow-sm border"
              >
                <PanelLeft className="h-4 w-4" />
              </Button>
            )}
            <PDFViewer
              file={file}
              initialPage={currentPage}
              onPageChange={handlePageChange}
              className="h-full"
            />
          </div>
        </div>
      </div>
      {renderDialogs()}
    </div>
  );
}
