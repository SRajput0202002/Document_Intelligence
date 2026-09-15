"use client";

import { useState, useCallback, useEffect } from "react";
import { useDropzone } from "react-dropzone";
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
} from "lucide-react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";
import {
  Collapsible,
  CollapsibleContent,
  CollapsibleTrigger,
} from "@/components/ui/collapsible";
import { PDFViewer } from "@/components/pdf-viewer";
import { getAuthHeaders } from "@/hooks/use-auth";

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8001";

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

// Fallback document profiles (used if API fails)
const DEFAULT_DOCUMENT_PROFILES = [
  { value: "", label: "Auto-detect (default)" },
  { value: "shipping_bill", label: "Indian Shipping Bill" },
  { value: "invoice", label: "Commercial Invoice" },
  { value: "telecom_bill", label: "Telecom Bill" },
  { value: "bill_of_entry", label: "Bill of Entry" },
];

// OCR methods available
const OCR_METHODS = [
  { value: "auto", label: "Auto (PyMuPDF → Tesseract → Mistral)" },
  { value: "mistral", label: "Mistral API (Best quality)" },
  { value: "pymupdf", label: "PyMuPDF (Fast, digital PDFs)" },
  { value: "tesseract", label: "Tesseract (Scanned docs)" },
];

interface SegmentationProfile {
  id: string;
  name: string;
  display_name: string;
  section_patterns: { pattern: string; capture_group: number }[];
  enable_section_splitting: boolean;
}

export default function SegmentationTestPage() {
  const [file, setFile] = useState<File | null>(null);
  const [isProcessing, setIsProcessing] = useState(false);
  const [comparison, setComparison] = useState<ComparisonResult | null>(null);
  const [groundTruth, setGroundTruth] = useState<string>("");
  const [expectedType, setExpectedType] = useState<string>("");
  const [splitBySections, setSplitBySections] = useState<boolean>(false);
  const [ocrMethod, setOcrMethod] = useState<string>("auto");
  const [documentProfiles, setDocumentProfiles] = useState<{ value: string; label: string; hasSections?: boolean }[]>(DEFAULT_DOCUMENT_PROFILES);

  // Load segmentation profiles from API
  useEffect(() => {
    const loadProfiles = async () => {
      try {
        const response = await fetch(`${API_BASE_URL}/api/segmentation-profiles`);
        if (response.ok) {
          const profiles: SegmentationProfile[] = await response.json();
          const profileOptions = [
            { value: "", label: "Auto-detect (default)", hasSections: false },
            ...profiles.map((p) => ({
              value: p.name,
              label: p.display_name,
              hasSections: (p.section_patterns?.length || 0) > 0,
            })),
          ];
          setDocumentProfiles(profileOptions);
        }
      } catch (error) {
        console.error("Failed to load segmentation profiles:", error);
        // Keep using default profiles
      }
    };
    loadProfiles();
  }, []);
  const [error, setError] = useState<string | null>(null);
  const [expandedApproaches, setExpandedApproaches] = useState<Set<string>>(new Set());
  const [selectedSegment, setSelectedSegment] = useState<{
    approach: string;
    segmentIndex: number;
    pageStart: number;
    pageEnd: number;
  } | null>(null);
  const [currentPage, setCurrentPage] = useState(1);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      const newFile = acceptedFiles[0];
      setFile(newFile);
      setComparison(null);
      setError(null);
      setSelectedSegment(null);
      setExpandedApproaches(new Set());
      setCurrentPage(1);
    }
  }, []);

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    maxFiles: 1,
  });

  const runComparison = async () => {
    if (!file) return;

    setIsProcessing(true);
    setError(null);

    try {
      const formData = new FormData();
      formData.append("file", file);
      if (groundTruth) {
        formData.append("ground_truth", groundTruth);
      }
      if (expectedType) {
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
    if (accuracy >= 0.9) return "bg-emerald-50 border-emerald-200";
    if (accuracy >= 0.7) return "bg-amber-50 border-amber-200";
    return "bg-red-50 border-red-200";
  };

  const isSegmentSelected = (approach: string, segmentIndex: number) => {
    return selectedSegment?.approach === approach && selectedSegment?.segmentIndex === segmentIndex;
  };

  return (
    <div className="h-[calc(100vh-4rem)] flex flex-col">
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b bg-background">
        <div>
          <h1 className="text-lg font-bold flex items-center gap-2">
            <Layers className="h-5 w-5" />
            Segmentation Test Lab
          </h1>
          <p className="text-xs text-muted-foreground">
            Compare ML-enhanced segmentation approaches side-by-side
          </p>
        </div>
        {file && (
          <div className="flex items-center gap-2">
            <Badge variant="outline" className="font-mono text-xs">
              {file.name}
            </Badge>
            {comparison && (
              <Badge variant="secondary" className="text-xs">
                {comparison.total_pages} pages
              </Badge>
            )}
            <Button
              variant="outline"
              size="sm"
              onClick={() => {
                setFile(null);
                setComparison(null);
                setError(null);
                setSelectedSegment(null);
                setExpandedApproaches(new Set());
                setGroundTruth("");
                setExpectedType("");
                setSplitBySections(false);
                setCurrentPage(1);
              }}
              className="ml-2"
            >
              <RotateCcw className="h-4 w-4 mr-1" />
              New Document
            </Button>
          </div>
        )}
      </div>

      {/* Main Content */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left Panel - Approaches */}
        <div className="w-1/2 border-r flex flex-col bg-muted/20 min-h-0">
          {/* Summary Stats */}
          {comparison && (
            <div className="grid grid-cols-4 gap-2 p-3 border-b">
              <div className="bg-background rounded-lg p-2 text-center border">
                <div className="text-xs text-muted-foreground">Pages</div>
                <div className="text-lg font-bold">{comparison.total_pages}</div>
              </div>
              <div className="bg-background rounded-lg p-2 text-center border">
                <div className="text-xs text-muted-foreground">OCR</div>
                <div className="text-sm font-bold capitalize">{comparison.ocr_method}</div>
              </div>
              <div className="bg-background rounded-lg p-2 text-center border">
                <div className="text-xs text-muted-foreground">Approaches</div>
                <div className="text-lg font-bold">{comparison.results.length}</div>
              </div>
              <div className="bg-background rounded-lg p-2 text-center border">
                <div className="text-xs text-muted-foreground">Ground Truth</div>
                <div className="text-lg font-bold">
                  {comparison.ground_truth_segments?.length || "N/A"}
                </div>
              </div>
            </div>
          )}

          {/* Configuration (when no comparison yet) */}
          {!comparison && file && !isProcessing && (
            <div className="p-3 border-b space-y-3">
              {/* OCR Method */}
              <div>
                <label className="text-xs font-medium mb-1 block">
                  OCR Method
                </label>
                <select
                  value={ocrMethod}
                  onChange={(e) => setOcrMethod(e.target.value)}
                  className="w-full px-2 py-1.5 border rounded text-sm bg-background"
                >
                  {OCR_METHODS.map((method) => (
                    <option key={method.value} value={method.value}>
                      {method.label}
                    </option>
                  ))}
                </select>
              </div>

              {/* Document Type */}
              <div>
                <label className="text-xs font-medium mb-1 block">
                  Expected Document Type
                </label>
                <select
                  value={expectedType}
                  onChange={(e) => {
                    setExpectedType(e.target.value);
                    // Auto-enable section splitting if profile has section patterns
                    const selectedProfile = documentProfiles.find(p => p.value === e.target.value);
                    if (selectedProfile?.hasSections) {
                      setSplitBySections(true);
                    }
                  }}
                  className="w-full px-2 py-1.5 border rounded text-sm bg-background"
                >
                  {documentProfiles.map((profile) => (
                    <option key={profile.value} value={profile.value}>
                      {profile.label}
                      {profile.hasSections ? " (has sections)" : ""}
                    </option>
                  ))}
                </select>
              </div>

              {/* Section Splitting Toggle */}
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  id="splitBySections"
                  checked={splitBySections}
                  onChange={(e) => setSplitBySections(e.target.checked)}
                  className="rounded"
                />
                <label htmlFor="splitBySections" className="text-xs">
                  Split by sections (PART I, II, III...)
                </label>
              </div>

              {/* Info about section splitting */}
              {splitBySections && (
                <div className="text-[10px] text-muted-foreground bg-blue-50 border border-blue-200 rounded p-2">
                  Section splitting enabled. Each PART section will be detected as a separate segment.
                </div>
              )}

              {/* Ground Truth */}
              <div>
                <label className="text-xs font-medium mb-1 block">
                  Ground Truth (optional)
                </label>
                <input
                  type="text"
                  value={groundTruth}
                  onChange={(e) => setGroundTruth(e.target.value)}
                  placeholder='e.g., "1,1" "2,3" for 2 segments'
                  className="w-full px-2 py-1.5 border rounded text-sm"
                />
                <p className="text-[10px] text-muted-foreground mt-1">
                  Specify segments as &quot;start,end&quot; pairs
                </p>
              </div>
              <Button onClick={runComparison} className="w-full" size="sm">
                <Zap className="h-4 w-4 mr-2" />
                Run Comparison
              </Button>
            </div>
          )}

          {/* Processing State */}
          {isProcessing && (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center">
                <Loader2 className="h-8 w-8 animate-spin mx-auto mb-3 text-primary" />
                <p className="text-sm font-medium">Running comparison...</p>
                <p className="text-xs text-muted-foreground">Testing all approaches</p>
              </div>
            </div>
          )}

          {/* Error */}
          {error && (
            <div className="p-3">
              <div className="flex items-start gap-2 text-destructive p-3 border border-destructive/20 rounded-lg bg-destructive/5 text-sm">
                <AlertTriangle className="h-4 w-4 flex-shrink-0 mt-0.5" />
                <span>{error}</span>
              </div>
            </div>
          )}

          {/* Approach Results */}
          {comparison && (
            <div className="flex-1 overflow-y-auto">
              <div className="p-2 space-y-2">
                {/* Ground Truth if provided */}
                {comparison.ground_truth_segments && (
                  <Card className="border-emerald-200 bg-emerald-50/50">
                    <CardHeader className="py-2 px-3">
                      <CardTitle className="text-xs flex items-center gap-2">
                        <CheckCircle2 className="h-3.5 w-3.5 text-emerald-600" />
                        Ground Truth
                      </CardTitle>
                    </CardHeader>
                    <CardContent className="px-3 pb-2">
                      <div className="flex flex-wrap gap-1.5">
                        {comparison.ground_truth_segments.map(([start, end], i) => (
                          <Badge
                            key={i}
                            variant="outline"
                            className="cursor-pointer hover:bg-emerald-100 border-emerald-300 text-xs"
                            onClick={() => handleSegmentClick("Ground Truth", i, start, end)}
                          >
                            Seg {i + 1}: {start === end ? `Page ${start}` : `${start}-${end}`}
                          </Badge>
                        ))}
                      </div>
                    </CardContent>
                  </Card>
                )}

                {/* Approach Results */}
                {comparison.results.map((result, idx) => (
                  <Collapsible
                    key={idx}
                    open={expandedApproaches.has(result.approach)}
                    onOpenChange={() => toggleApproach(result.approach)}
                  >
                    <Card className={`transition-colors ${getAccuracyBg(result.accuracy)}`}>
                      <CollapsibleTrigger asChild>
                        <CardHeader className="py-2 px-3 cursor-pointer hover:bg-black/5">
                          <div className="flex items-center justify-between">
                            <div className="flex items-center gap-1.5">
                              {expandedApproaches.has(result.approach) ? (
                                <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                              ) : (
                                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground" />
                              )}
                              {getApproachIcon(result.approach)}
                              <span className="font-medium text-sm">{result.approach}</span>
                            </div>
                            <div className="flex items-center gap-2">
                              <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                                <Clock className="h-2.5 w-2.5" />
                                {result.processing_time_ms.toFixed(0)}ms
                              </span>
                              {result.segments.length > 0 && (
                                <Badge variant="secondary" className="text-[10px] h-5">
                                  {result.segments.length} segments
                                </Badge>
                              )}
                            </div>
                          </div>
                        </CardHeader>
                      </CollapsibleTrigger>

                      <CollapsibleContent>
                        <CardContent className="px-3 pb-3 pt-0 space-y-3">
                          {/* Accuracy Metrics */}
                          {result.accuracy !== null && (
                            <div className="space-y-2">
                              <div className="flex justify-between text-xs">
                                <span>Accuracy (F1)</span>
                                <span className={`font-medium ${getAccuracyColor(result.accuracy)}`}>
                                  {(result.accuracy * 100).toFixed(1)}%
                                </span>
                              </div>
                              <Progress value={result.accuracy * 100} className="h-1.5" />
                              <div className="grid grid-cols-3 gap-1.5">
                                <div className="text-center p-1.5 rounded bg-emerald-100 border border-emerald-200">
                                  <div className="text-sm font-bold text-emerald-700">
                                    {result.true_positives}
                                  </div>
                                  <div className="text-[9px] text-emerald-600">TP</div>
                                </div>
                                <div className="text-center p-1.5 rounded bg-red-100 border border-red-200">
                                  <div className="text-sm font-bold text-red-700">
                                    {result.false_positives}
                                  </div>
                                  <div className="text-[9px] text-red-600">FP</div>
                                </div>
                                <div className="text-center p-1.5 rounded bg-amber-100 border border-amber-200">
                                  <div className="text-sm font-bold text-amber-700">
                                    {result.false_negatives}
                                  </div>
                                  <div className="text-[9px] text-amber-600">FN</div>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* Detected Segments */}
                          {result.segments.length > 0 && (
                            <div>
                              <h4 className="text-xs font-medium mb-1.5 flex items-center gap-1.5">
                                <Eye className="h-3 w-3" />
                                Detected Segments (click to preview)
                              </h4>
                              <div className="flex flex-wrap gap-1.5">
                                {result.segments.map(([start, end], i) => (
                                  <Badge
                                    key={i}
                                    variant={isSegmentSelected(result.approach, i) ? "default" : "outline"}
                                    className={`cursor-pointer transition-all text-xs ${
                                      isSegmentSelected(result.approach, i)
                                        ? "ring-2 ring-primary ring-offset-1"
                                        : "hover:bg-primary/10"
                                    }`}
                                    onClick={() => handleSegmentClick(result.approach, i, start, end)}
                                  >
                                    Seg {i + 1}: {start === end ? `Page ${start}` : `${start}-${end}`}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          )}

                          {/* Boundaries */}
                          {result.boundaries.length > 0 && (
                            <div>
                              <h4 className="text-xs font-medium mb-1.5">Boundaries Detected</h4>
                              <div className="flex flex-wrap gap-1.5">
                                {result.boundaries.map((b, i) => (
                                  <Badge
                                    key={i}
                                    variant="secondary"
                                    className="cursor-pointer hover:bg-secondary/80 text-xs"
                                    onClick={() => setCurrentPage(b)}
                                  >
                                    After page {b}
                                    {result.confidence_scores?.[b] && (
                                      <span className="ml-1 opacity-70">
                                        ({(result.confidence_scores[b] * 100).toFixed(0)}%)
                                      </span>
                                    )}
                                  </Badge>
                                ))}
                              </div>
                            </div>
                          )}

                          {typeof result.metadata?.reason === "string" && (
                            <p className="text-xs text-muted-foreground leading-snug">
                              {result.metadata.reason}
                            </p>
                          )}
                          {typeof result.metadata?.total_tokens === "number" && (
                            <p className="text-xs text-muted-foreground">
                              Vision tokens (approx.): {result.metadata.total_tokens}
                            </p>
                          )}

                          {/* No segments detected (skip message if skipped approach already explained reason) */}
                          {result.segments.length === 0 &&
                            result.boundaries.length === 0 &&
                            typeof result.metadata?.reason !== "string" && (
                              <p className="text-xs text-muted-foreground italic">
                                No segments or boundaries detected
                              </p>
                            )}

                          {/* Error if any */}
                          {result.metadata?.error && (
                            <div className="text-xs text-destructive flex items-center gap-1.5">
                              <XCircle className="h-3 w-3" />
                              {String(result.metadata.error)}
                            </div>
                          )}
                        </CardContent>
                      </CollapsibleContent>
                    </Card>
                  </Collapsible>
                ))}
              </div>
            </div>
          )}

          {/* Empty state when no file */}
          {!file && (
            <div className="flex-1 flex items-center justify-center p-4">
              <div className="text-center max-w-xs">
                <Layers className="h-10 w-10 mx-auto mb-3 text-muted-foreground" />
                <h3 className="font-semibold mb-1">Ready to Test</h3>
                <p className="text-xs text-muted-foreground mb-4">
                  Upload a multi-document PDF to compare segmentation approaches.
                </p>
                <div className="grid grid-cols-2 gap-2 text-left">
                  {[
                    { icon: Layers, name: "Heuristics" },
                    { icon: Fingerprint, name: "SimHash" },
                    { icon: Key, name: "Key Fields" },
                    { icon: BarChart3, name: "TF-IDF" },
                    { icon: Brain, name: "MiniLM" },
                    { icon: Zap, name: "Full ML" },
                    { icon: Eye, name: "VLM (Azure)" },
                  ].map(({ icon: Icon, name }) => (
                    <div key={name} className="flex items-center gap-1.5 p-1.5 border rounded text-xs">
                      <Icon className="h-3.5 w-3.5 text-primary flex-shrink-0" />
                      <span>{name}</span>
                    </div>
                  ))}
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Right Panel - PDF Preview */}
        <div className="w-1/2 flex flex-col bg-neutral-100 min-h-0">
          {!file ? (
            <div className="flex-1 flex items-center justify-center p-6">
              <div
                {...getRootProps()}
                className={`w-full max-w-lg border-2 border-dashed rounded-xl p-10 text-center cursor-pointer transition-colors ${
                  isDragActive
                    ? "border-primary bg-primary/5"
                    : "border-muted-foreground/25 hover:border-primary/50 bg-background"
                }`}
              >
                <input {...getInputProps()} />
                <Upload className="h-12 w-12 mx-auto mb-4 text-muted-foreground" />
                <p className="font-medium text-lg">Drag & drop a PDF here</p>
                <p className="text-sm text-muted-foreground mt-1">or click to select a file</p>
              </div>
            </div>
          ) : (
            <>
              {/* PDF Viewer Header with selection info */}
              {selectedSegment && (
                <div className="px-4 py-2 border-b bg-primary/5 flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Target className="h-4 w-4 text-primary" />
                    <span className="text-sm font-medium">
                      {selectedSegment.approach} - Segment {selectedSegment.segmentIndex + 1}
                    </span>
                  </div>
                  <Badge>
                    Pages {selectedSegment.pageStart} - {selectedSegment.pageEnd}
                  </Badge>
                </div>
              )}

              {/* PDF Viewer */}
              <div className="flex-1 min-h-0">
                <PDFViewer
                  file={file}
                  initialPage={currentPage}
                  onPageChange={handlePageChange}
                  className="h-full"
                />
              </div>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
