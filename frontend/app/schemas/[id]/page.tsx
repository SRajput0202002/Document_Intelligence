"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import {
  SchemaBuilder,
  SchemaField,
  jsonSchemaToFields,
  fieldsToJsonSchema,
} from "@/components/schema-builder";
import { api, Schema } from "@/lib/api";
import { Loader2, CheckCircle2, XCircle } from "lucide-react";
import { toast } from "@/components/ui/toast";
import { useAuth } from "@/hooks/use-auth";
import { Button } from "@/components/ui/button";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface PageProps {
  params: { id: string };
}

// Helper to format doc_type for display (snake_case to Title Case)
function formatDocType(docType: string): string {
  return docType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

export default function EditSchemaPage({ params }: PageProps) {
  const { id } = params;
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, isAdmin } = useAuth();
  const [schema, setSchema] = useState<Schema | null>(null);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [initialFields, setInitialFields] = useState<SchemaField[]>([]);
  const [reviewDialogOpen, setReviewDialogOpen] = useState(false);
  const [reviewAction, setReviewAction] = useState<"approve" | "reject">("approve");
  const [reviewNotes, setReviewNotes] = useState("");

  // Check if this is a pending review that admin can review
  const isReviewMode = isAdmin && schema?.status === "pending_review" && schema?.owner_id !== user?.id;

  useEffect(() => {
    const fetchSchema = async () => {
      try {
        const data = await api.getSchema(id);
        setSchema(data);
        // Convert json_schema to fields - instructions are now embedded in json_schema
        const schemaFields = data.json_schema ? jsonSchemaToFields(data.json_schema) : [];
        setInitialFields(schemaFields);
      } catch (error) {
        console.error("Failed to fetch schema:", error);
        toast({
          title: "Error",
          description: "Failed to load schema",
          variant: "destructive",
        });
      } finally {
        setLoading(false);
      }
    };
    fetchSchema();
  }, [id]);

  // Review mutation
  const reviewMutation = useMutation({
    mutationFn: ({ approved, notes }: { approved: boolean; notes?: string }) =>
      api.reviewSchema(id, approved, notes),
    onSuccess: (_, variables) => {
      queryClient.invalidateQueries({ queryKey: ["schemas"] });
      queryClient.invalidateQueries({ queryKey: ["pendingSchemas"] });
      queryClient.invalidateQueries({ queryKey: ["pendingSchemaCount"] });
      toast({
        title: variables.approved ? "Schema approved" : "Schema rejected",
        description: variables.approved
          ? "The schema has been published and is now visible to all users."
          : "The schema has been rejected. The owner will be notified.",
      });
      router.push("/schemas");
    },
    onError: (error) => {
      toast({
        title: "Review failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    },
  });

  const handleApproveClick = () => {
    setReviewAction("approve");
    setReviewNotes("");
    setReviewDialogOpen(true);
  };

  const handleRejectClick = () => {
    setReviewAction("reject");
    setReviewNotes("");
    setReviewDialogOpen(true);
  };

  const handleConfirmReview = () => {
    if (!reviewNotes.trim()) {
      toast({
        title: "Notes required",
        description: "Please provide review notes",
        variant: "destructive",
      });
      return;
    }
    reviewMutation.mutate({
      approved: reviewAction === "approve",
      notes: reviewNotes,
    });
  };

  const handleSave = async (
    fields: SchemaField[],
    name: string,
    docType: string,
    description?: string
  ) => {
    setSaving(true);
    try {
      // Instructions are now embedded in json_schema, not passed separately
      const jsonSchema = fieldsToJsonSchema(fields);
      await api.updateSchema(id, {
        name,
        json_schema: jsonSchema as Record<string, unknown>,
        description: description || undefined,
      });
      await queryClient.invalidateQueries({ queryKey: ["schemas"] });
      await queryClient.invalidateQueries({ queryKey: ["mySchemas"] });
      await queryClient.invalidateQueries({ queryKey: ["schema", id] });
      toast({
        title: "Schema updated",
        description: "Your changes have been saved.",
      });
      router.push("/schemas");
    } catch (error) {
      console.error("Failed to update schema:", error);
      toast({
        title: "Update failed",
        description:
          error instanceof Error ? error.message : "Unknown error occurred",
        variant: "destructive",
      });
    } finally {
      setSaving(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center h-screen">
        <Loader2 className="w-8 h-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (!schema) {
    return (
      <div className="flex items-center justify-center h-screen">
        <div className="text-center">
          <p className="text-muted-foreground mb-4">Schema not found</p>
          <button
            onClick={() => router.push("/schemas")}
            className="text-primary hover:underline"
          >
            Return to schemas
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen">
      {isReviewMode && schema?.submit_notes && (
        <div className="px-6 pt-4">
          <div className="rounded-md border bg-muted/40 p-3">
            <p className="text-xs font-medium text-muted-foreground mb-1">Publisher Comment</p>
            <p className="text-sm">{schema.submit_notes}</p>
          </div>
        </div>
      )}
      <SchemaBuilder
        initialFields={initialFields}
        initialName={schema.name}
        initialDescription={schema.description || ""}
        initialDocType={formatDocType(schema.doc_type)}
        onSave={handleSave}
        onCancel={() => router.push("/schemas")}
        mode="edit"
        isReadOnly={schema.is_default || isReviewMode}
        isSaving={saving}
        isReviewMode={isReviewMode}
        onApprove={handleApproveClick}
        onReject={handleRejectClick}
        isReviewing={reviewMutation.isPending}
      />

      {/* Review Dialog */}
      <Dialog open={reviewDialogOpen} onOpenChange={(open) => {
        if (!open) {
          setReviewDialogOpen(false);
          setReviewNotes("");
        }
      }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>
              {reviewAction === "approve" ? "Approve Schema" : "Reject Schema"}
            </DialogTitle>
            <DialogDescription>
              {reviewAction === "approve"
                ? `You are about to approve and publish "${schema?.name}". This will make it visible to all users.`
                : `You are about to reject "${schema?.name}". The owner will be notified with your feedback.`}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="review-notes">
                Review Notes <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="review-notes"
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                placeholder={reviewAction === "approve"
                  ? "Add any notes about the approval (e.g., 'Reviewed and approved for production use')..."
                  : "Explain why this schema is being rejected and what changes are needed..."}
                rows={4}
              />
              <p className="text-xs text-muted-foreground">
                Review notes are required to {reviewAction === "approve" ? "approve" : "reject"} this schema.
              </p>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setReviewDialogOpen(false)}>
              Cancel
            </Button>
            {reviewAction === "approve" ? (
              <Button
                onClick={handleConfirmReview}
                disabled={!reviewNotes.trim() || reviewMutation.isPending}
                className="bg-green-600 hover:bg-green-700"
              >
                {reviewMutation.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                )}
                Approve & Publish
              </Button>
            ) : (
              <Button
                variant="destructive"
                onClick={handleConfirmReview}
                disabled={!reviewNotes.trim() || reviewMutation.isPending}
              >
                {reviewMutation.isPending ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <XCircle className="w-4 h-4 mr-2" />
                )}
                Reject
              </Button>
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
