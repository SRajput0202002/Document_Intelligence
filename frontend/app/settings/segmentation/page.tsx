"use client";

import { useState, useEffect } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Plus,
  Pencil,
  Trash2,
  ChevronLeft,
  Loader2,
  CheckCircle2,
  XCircle,
  Copy,
  FlaskConical,
  FileText,
  Shield,
  Layers,
  Save,
  RotateCcw,
} from "lucide-react";
import Link from "next/link";

import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Textarea } from "@/components/ui/textarea";
import { toast } from "@/components/ui/toast";
import { formatApiErrorDetail } from "@/lib/format-api-error";
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

interface SupportingField {
  name: string;
  pattern: string;
}

interface SegmentationProfile {
  id: string;
  name: string;
  display_name: string;
  description: string | null;
  veto_fields: VetoField[];
  section_patterns: SectionPattern[];
  start_keywords: StartKeyword[];
  supporting_fields: SupportingField[];
  continuity_patterns: string[];
  enable_section_splitting: boolean;
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

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

// API functions
const api = {
  getProfiles: async (): Promise<SegmentationProfile[]> => {
    const res = await fetch(`${API_BASE}/api/segmentation-profiles`);
    if (!res.ok) throw new Error("Failed to fetch profiles");
    return res.json();
  },

  createProfile: async (profile: Partial<SegmentationProfile>): Promise<SegmentationProfile> => {
    const res = await fetch(`${API_BASE}/api/segmentation-profiles`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(formatApiErrorDetail(error.detail, "Failed to create profile"));
    }
    return res.json();
  },

  updateProfile: async (id: string, profile: Partial<SegmentationProfile>): Promise<SegmentationProfile> => {
    const res = await fetch(`${API_BASE}/api/segmentation-profiles/${id}`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(profile),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(formatApiErrorDetail(error.detail, "Failed to update profile"));
    }
    return res.json();
  },

  deleteProfile: async (id: string): Promise<void> => {
    const res = await fetch(`${API_BASE}/api/segmentation-profiles/${id}`, {
      method: "DELETE",
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({}));
      throw new Error(formatApiErrorDetail(error.detail, "Failed to delete profile"));
    }
  },

  testPatterns: async (patterns: VetoField[], sampleText: string): Promise<PatternTestResult[]> => {
    const res = await fetch(`${API_BASE}/api/segmentation-profiles/test-patterns-bulk`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ patterns, sample_text: sampleText }),
    });
    if (!res.ok) throw new Error("Failed to test patterns");
    const data = await res.json();
    return data.results;
  },
};

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
};

export default function SegmentationProfilesPage() {
  const queryClient = useQueryClient();
  const [editingProfile, setEditingProfile] = useState<SegmentationProfile | null>(null);
  const [isDialogOpen, setIsDialogOpen] = useState(false);
  const [isNewProfile, setIsNewProfile] = useState(false);
  const [deleteConfirmId, setDeleteConfirmId] = useState<string | null>(null);
  const [formData, setFormData] = useState<Partial<SegmentationProfile>>(emptyProfile);
  const [testText, setTestText] = useState("");
  const [testResults, setTestResults] = useState<PatternTestResult[]>([]);
  const [testing, setTesting] = useState(false);

  // Fetch profiles
  const { data: profiles, isLoading, error } = useQuery({
    queryKey: ["segmentation-profiles"],
    queryFn: api.getProfiles,
  });

  // Mutations
  const createMutation = useMutation({
    mutationFn: api.createProfile,
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
      api.updateProfile(id, data),
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
    mutationFn: api.deleteProfile,
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["segmentation-profiles"] });
      toast({ title: "Profile deleted", description: "The profile has been deleted." });
      setDeleteConfirmId(null);
    },
    onError: (error: Error) => {
      toast({ title: "Failed to delete", description: error.message, variant: "destructive" });
    },
  });

  // Open dialog for new profile
  const handleNewProfile = () => {
    setFormData({ ...emptyProfile });
    setIsNewProfile(true);
    setEditingProfile(null);
    setIsDialogOpen(true);
    setTestResults([]);
  };

  // Open dialog for editing
  const handleEditProfile = (profile: SegmentationProfile) => {
    setFormData({ ...profile });
    setIsNewProfile(false);
    setEditingProfile(profile);
    setIsDialogOpen(true);
    setTestResults([]);
  };

  // Save profile
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
    if (isNewProfile) {
      createMutation.mutate({ ...formData, name, display_name: displayName });
    } else if (editingProfile) {
      updateMutation.mutate({ id: editingProfile.id, data: { ...formData, name, display_name: displayName } });
    }
  };

  // Test patterns
  const handleTestPatterns = async () => {
    if (!testText.trim() || !formData.veto_fields?.length) return;
    setTesting(true);
    try {
      const results = await api.testPatterns(formData.veto_fields, testText);
      setTestResults(results);
    } catch (error) {
      toast({ title: "Test failed", description: "Failed to test patterns", variant: "destructive" });
    } finally {
      setTesting(false);
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
  };

  if (isLoading) {
    return (
      <div className="container mx-auto py-6 px-4 max-w-5xl">
        <div className="flex items-center justify-center h-64">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
        </div>
      </div>
    );
  }

  if (error) {
    return (
      <div className="container mx-auto py-6 px-4 max-w-5xl">
        <div className="flex flex-col items-center justify-center h-64 gap-4">
          <XCircle className="h-12 w-12 text-destructive" />
          <p className="text-destructive">Failed to load segmentation profiles</p>
        </div>
      </div>
    );
  }

  return (
    <div className="container mx-auto py-6 px-4 max-w-5xl">
      {/* Header */}
      <div className="flex items-center justify-between mb-6">
        <div className="flex items-center gap-4">
          <Link href="/settings">
            <Button variant="ghost" size="sm">
              <ChevronLeft className="h-4 w-4 mr-1" />
              Settings
            </Button>
          </Link>
          <div>
            <h1 className="text-2xl font-bold">Segmentation Profiles</h1>
            <p className="text-muted-foreground">
              Configure document boundary detection patterns
            </p>
          </div>
        </div>
        <Button onClick={handleNewProfile}>
          <Plus className="h-4 w-4 mr-2" />
          New Profile
        </Button>
      </div>

      {/* Profile List */}
      <div className="space-y-3">
        {profiles?.map((profile) => (
          <Card key={profile.id} className="hover:shadow-md transition-shadow">
            <CardContent className="flex items-center justify-between p-4">
              <div className="flex-1">
                <div className="flex items-center gap-2">
                  <h3 className="font-medium">{profile.display_name}</h3>
                  {profile.is_builtin && (
                    <Badge variant="secondary" className="text-xs">
                      <Shield className="h-3 w-3 mr-1" />
                      System
                    </Badge>
                  )}
                </div>
                <p className="text-sm text-muted-foreground mt-1">{profile.description}</p>
                <div className="flex gap-4 mt-2 text-xs text-muted-foreground">
                  <span className="flex items-center gap-1">
                    <FileText className="h-3 w-3" />
                    {profile.veto_fields.length} veto fields
                  </span>
                  <span className="flex items-center gap-1">
                    <Layers className="h-3 w-3" />
                    {profile.section_patterns.length} section patterns
                  </span>
                  <span>{profile.start_keywords.length} keywords</span>
                </div>
              </div>
              <div className="flex gap-2">
                <Button variant="outline" size="sm" onClick={() => handleEditProfile(profile)}>
                  <Pencil className="h-4 w-4 mr-1" />
                  Edit
                </Button>
                {!profile.is_builtin && (
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => setDeleteConfirmId(profile.id)}
                    className="text-destructive hover:text-destructive"
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                )}
              </div>
            </CardContent>
          </Card>
        ))}

        {profiles?.length === 0 && (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-12">
              <FileText className="h-12 w-12 text-muted-foreground mb-4" />
              <p className="text-muted-foreground">No segmentation profiles found</p>
              <Button className="mt-4" onClick={handleNewProfile}>
                Create your first profile
              </Button>
            </CardContent>
          </Card>
        )}
      </div>

      {/* Edit/Create Dialog */}
      <Dialog open={isDialogOpen} onOpenChange={setIsDialogOpen}>
        <DialogContent className="max-w-4xl max-h-[90vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>
              {isNewProfile ? "Create Profile" : `Edit: ${editingProfile?.display_name}`}
            </DialogTitle>
            <DialogDescription>
              Configure patterns for document boundary detection
            </DialogDescription>
          </DialogHeader>

          <Tabs defaultValue="basic" className="mt-4">
            <TabsList className="grid w-full grid-cols-4">
              <TabsTrigger value="basic">Basic Info</TabsTrigger>
              <TabsTrigger value="veto">Veto Fields</TabsTrigger>
              <TabsTrigger value="sections">Sections</TabsTrigger>
              <TabsTrigger value="test">Test</TabsTrigger>
            </TabsList>

            {/* Basic Info Tab */}
            <TabsContent value="basic" className="space-y-4 mt-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label>Name (ID)</Label>
                  <Input
                    value={formData.name || ""}
                    onChange={(e) => setFormData({ ...formData, name: e.target.value })}
                    placeholder="my_document_type"
                    disabled={editingProfile?.is_builtin}
                  />
                  <p className="text-xs text-muted-foreground">
                    Unique identifier (lowercase, underscores)
                  </p>
                </div>
                <div className="space-y-2">
                  <Label>Display Name</Label>
                  <Input
                    value={formData.display_name || ""}
                    onChange={(e) => setFormData({ ...formData, display_name: e.target.value })}
                    placeholder="My Document Type"
                  />
                </div>
              </div>
              <div className="space-y-2">
                <Label>Description</Label>
                <Textarea
                  value={formData.description || ""}
                  onChange={(e) => setFormData({ ...formData, description: e.target.value })}
                  placeholder="Describe what documents this profile handles..."
                  rows={3}
                />
              </div>
              <div className="flex items-center gap-2">
                <Switch
                  checked={formData.enable_section_splitting || false}
                  onCheckedChange={(v) => setFormData({ ...formData, enable_section_splitting: v })}
                />
                <Label>Enable section splitting by default</Label>
              </div>
            </TabsContent>

            {/* Veto Fields Tab */}
            <TabsContent value="veto" className="space-y-4 mt-4">
              <p className="text-sm text-muted-foreground">
                Veto fields identify unique document identifiers. If the same value is found
                on consecutive pages, they are considered the same document (boundary suppressed).
              </p>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-32">Field Name</TableHead>
                    <TableHead>Regex Pattern</TableHead>
                    <TableHead className="w-24 text-center">Bidirectional</TableHead>
                    <TableHead className="w-20 text-center">Enabled</TableHead>
                    <TableHead className="w-16"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {formData.veto_fields?.map((field, index) => (
                    <TableRow key={index}>
                      <TableCell>
                        <Input
                          value={field.name}
                          onChange={(e) => updateVetoField(index, { name: e.target.value })}
                          placeholder="be_number"
                          className="h-8"
                        />
                      </TableCell>
                      <TableCell>
                        <Input
                          value={field.pattern}
                          onChange={(e) => updateVetoField(index, { pattern: e.target.value })}
                          placeholder="BE\s*No[.\s:=]*(\d{7,})"
                          className="h-8 font-mono text-xs"
                        />
                      </TableCell>
                      <TableCell className="text-center">
                        <Switch
                          checked={field.bidirectional}
                          onCheckedChange={(v) => updateVetoField(index, { bidirectional: v })}
                        />
                      </TableCell>
                      <TableCell className="text-center">
                        <Switch
                          checked={field.enabled}
                          onCheckedChange={(v) => updateVetoField(index, { enabled: v })}
                        />
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => removeVetoField(index)}
                          className="h-8 w-8 p-0 text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <Button variant="outline" onClick={addVetoField}>
                <Plus className="h-4 w-4 mr-2" />
                Add Veto Field
              </Button>
            </TabsContent>

            {/* Sections Tab */}
            <TabsContent value="sections" className="space-y-4 mt-4">
              <p className="text-sm text-muted-foreground">
                Section patterns detect PART headers (e.g., PART I, PART II) for splitting
                documents into sections while keeping them as part of the same logical document.
              </p>

              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Regex Pattern</TableHead>
                    <TableHead className="w-32">Capture Group</TableHead>
                    <TableHead className="w-16"></TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {formData.section_patterns?.map((pattern, index) => (
                    <TableRow key={index}>
                      <TableCell>
                        <Input
                          value={pattern.pattern}
                          onChange={(e) => updateSectionPattern(index, { pattern: e.target.value })}
                          placeholder="PART\s*[-:]?\s*([IVX]+|\d+)"
                          className="h-8 font-mono text-xs"
                        />
                      </TableCell>
                      <TableCell>
                        <Input
                          type="number"
                          value={pattern.capture_group}
                          onChange={(e) => updateSectionPattern(index, { capture_group: parseInt(e.target.value) || 1 })}
                          min={1}
                          className="h-8 w-20"
                        />
                      </TableCell>
                      <TableCell>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => removeSectionPattern(index)}
                          className="h-8 w-8 p-0 text-destructive"
                        >
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>

              <Button variant="outline" onClick={addSectionPattern}>
                <Plus className="h-4 w-4 mr-2" />
                Add Section Pattern
              </Button>

              <div className="border-t pt-4 mt-4">
                <h4 className="font-medium mb-2">Start Keywords</h4>
                <p className="text-sm text-muted-foreground mb-4">
                  Keywords that indicate the start of a new document of this type.
                </p>

                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Regex Pattern</TableHead>
                      <TableHead className="w-32">Confidence</TableHead>
                      <TableHead className="w-16"></TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {formData.start_keywords?.map((keyword, index) => (
                      <TableRow key={index}>
                        <TableCell>
                          <Input
                            value={keyword.pattern}
                            onChange={(e) => updateStartKeyword(index, { pattern: e.target.value })}
                            placeholder="\bBILL\s+OF\s+ENTRY\b"
                            className="h-8 font-mono text-xs"
                          />
                        </TableCell>
                        <TableCell>
                          <Input
                            type="number"
                            value={keyword.confidence}
                            onChange={(e) => updateStartKeyword(index, { confidence: parseFloat(e.target.value) || 0.75 })}
                            min={0}
                            max={1}
                            step={0.05}
                            className="h-8 w-20"
                          />
                        </TableCell>
                        <TableCell>
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => removeStartKeyword(index)}
                            className="h-8 w-8 p-0 text-destructive"
                          >
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>

                <Button variant="outline" onClick={addStartKeyword} className="mt-2">
                  <Plus className="h-4 w-4 mr-2" />
                  Add Keyword
                </Button>
              </div>
            </TabsContent>

            {/* Test Tab */}
            <TabsContent value="test" className="space-y-4 mt-4">
              <div className="space-y-2">
                <Label>Sample Text</Label>
                <Textarea
                  value={testText}
                  onChange={(e) => setTestText(e.target.value)}
                  placeholder="Paste sample document text to test patterns..."
                  rows={6}
                  className="font-mono text-sm"
                />
              </div>

              <Button
                onClick={handleTestPatterns}
                disabled={testing || !testText.trim() || !formData.veto_fields?.length}
              >
                {testing ? (
                  <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                ) : (
                  <FlaskConical className="h-4 w-4 mr-2" />
                )}
                Test Veto Field Patterns
              </Button>

              {testResults.length > 0 && (
                <div className="space-y-2 mt-4">
                  <h4 className="font-medium">Results:</h4>
                  <div className="space-y-1">
                    {testResults.map((result, i) => (
                      <div key={i} className="flex items-center gap-2 text-sm">
                        {result.matched ? (
                          <CheckCircle2 className="h-4 w-4 text-green-500" />
                        ) : (
                          <XCircle className="h-4 w-4 text-red-500" />
                        )}
                        <span className="font-medium">{result.field_name}:</span>
                        {result.matched ? (
                          <code className="bg-green-100 dark:bg-green-900/30 px-2 py-0.5 rounded text-xs">
                            {result.value}
                          </code>
                        ) : result.error ? (
                          <span className="text-destructive text-xs">{result.error}</span>
                        ) : (
                          <span className="text-muted-foreground">no match</span>
                        )}
                      </div>
                    ))}
                  </div>
                </div>
              )}
            </TabsContent>
          </Tabs>

          <DialogFooter className="mt-6">
            <Button variant="outline" onClick={() => setIsDialogOpen(false)}>
              Cancel
            </Button>
            <Button
              onClick={handleSave}
              disabled={createMutation.isPending || updateMutation.isPending}
            >
              {(createMutation.isPending || updateMutation.isPending) && (
                <Loader2 className="h-4 w-4 mr-2 animate-spin" />
              )}
              <Save className="h-4 w-4 mr-2" />
              {isNewProfile ? "Create Profile" : "Save Changes"}
            </Button>
          </DialogFooter>
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
    </div>
  );
}
