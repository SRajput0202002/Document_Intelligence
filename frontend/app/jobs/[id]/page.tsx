"use client";

import { useState, useEffect } from "react";
import { useParams, useRouter, useSearchParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { Loader2, AlertCircle } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { ExtractionResultsView } from "@/components/extraction/extraction-results";
import { api } from "@/lib/api";

export default function JobResultPage() {
  const params = useParams();
  const router = useRouter();
  const searchParams = useSearchParams();
  const jobId = params.id as string;
  const fromWorkflow = searchParams.get("from") === "workflow";

  // State for document blob URL
  const [documentBlobUrl, setDocumentBlobUrl] = useState<string | null>(null);
  const [documentError, setDocumentError] = useState<string | null>(null);

  const { data: job, isLoading, error } = useQuery({
    queryKey: ["job", jobId],
    queryFn: () => api.getJob(jobId),
    enabled: !!jobId,
    // Poll every 2 seconds while job is still in progress
    refetchInterval: (query) => {
      const jobData = query.state.data;
      if (!jobData) return 2000; // Poll while loading
      // Stop polling when completed or failed
      if (jobData.status === "completed" || jobData.status === "failed") {
        return false;
      }
      // Continue polling for processing/extracting states
      return 2000;
    },
  });

  const { data: providers } = useQuery({
    queryKey: ["providers"],
    queryFn: () => api.getProviders(),
  });

  // Fetch document blob when job is loaded and has stored document
  useEffect(() => {
    let blobUrl: string | null = null;

    async function fetchDocument() {
      if (job?.has_stored_document) {
        try {
          const blob = await api.getDocumentBlob(job.id);
          blobUrl = URL.createObjectURL(blob);
          setDocumentBlobUrl(blobUrl);
          setDocumentError(null);
        } catch (err) {
          console.error("Failed to load document:", err);
          setDocumentError(err instanceof Error ? err.message : "Failed to load document");
          setDocumentBlobUrl(null);
        }
      }
    }

    fetchDocument();

    // Cleanup: revoke blob URL when component unmounts or job changes
    return () => {
      if (blobUrl) {
        URL.revokeObjectURL(blobUrl);
      }
    };
  }, [job?.id, job?.has_stored_document]);

  if (isLoading) {
    return (
      <div className="h-full flex items-center justify-center">
        <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error || !job) {
    return (
      <div className="h-full flex items-center justify-center">
        <Card className="max-w-md">
          <CardContent className="py-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center">
                <AlertCircle className="w-6 h-6 text-destructive" />
              </div>
              <div className="flex-1">
                <h3 className="font-semibold">Job Not Found</h3>
                <p className="text-sm text-muted-foreground">
                  {error instanceof Error ? error.message : "The requested job could not be found."}
                </p>
              </div>
            </div>
             <Button variant="outline" className="mt-4" onClick={() => router.push("/jobs")}>
                Back to Jobs
              </Button>
          </CardContent>
        </Card>
      </div>
    );
  }

  const isFromWorkflow = !!job.workflow_id || fromWorkflow;

  return (
    <ExtractionResultsView
      job={job}
      providers={providers ? { ocr: providers.ocr_providers || [], llm: providers.llm_providers || [] } : null}
      documentFile={documentBlobUrl}
      onBack={() => router.push(isFromWorkflow ? '/workflows' : '/jobs')}
      backButtonText={isFromWorkflow ? "Back to Workflows" : "Back to Jobs"}
      hideSaveAsWorkflow={fromWorkflow}
    />
  );
}
