"use client";

import { useState, useMemo } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import {
  Layout,
  Edit2,
  Trash2,
  FileJson,
  Loader2,
  Star,
  Send,
  RefreshCw,
  Clock,
  CheckCircle2,
  XCircle,
  Globe,
  User,
  Copy,
} from "lucide-react";

// Animated icons
import { PlusIcon } from "@/components/ui/plus";
import { SearchIcon } from "@/components/ui/search";
import { LayersIcon } from "@/components/ui/layers";
import { FileTextIcon } from "@/components/ui/file-text";
import { SparklesIcon } from "@/components/ui/sparkles";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";
import { toast } from "@/components/ui/toast";
import { api, type Schema, type SchemaStatus } from "@/lib/api";
import { formatDate, cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";

// Helper to format doc_type for display
function formatDocType(docType: string): string {
  return docType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}

// Helper to get status badge props
function getStatusBadge(status: SchemaStatus) {
  switch (status) {
    case "draft":
      return { label: "Draft", variant: "outline" as const, icon: Edit2 };
    case "pending_review":
      return { label: "Pending Review", variant: "secondary" as const, icon: Clock };
    case "published":
      return { label: "Published", variant: "default" as const, icon: Globe };
    case "rejected":
      return { label: "Rejected", variant: "destructive" as const, icon: XCircle };
    default:
      return { label: status, variant: "outline" as const, icon: Edit2 };
  }
}

export default function SchemasPage() {
  const router = useRouter();
  const queryClient = useQueryClient();
  const { user, isAdmin } = useAuth();
  const [docTypeFilter, setDocTypeFilter] = useState<string>("all");
  const [searchQuery, setSearchQuery] = useState("");
  const [myDocTypeFilter, setMyDocTypeFilter] = useState<string>("all");
  const [mySearchQuery, setMySearchQuery] = useState("");
  const [deleteSchema, setDeleteSchema] = useState<Schema | null>(null);
  const [publishSchema, setPublishSchema] = useState<Schema | null>(null);
  const [publishComment, setPublishComment] = useState("");
  const [reviewSchema, setReviewSchema] = useState<Schema | null>(null);
  const [reviewNotes, setReviewNotes] = useState("");

  const { data: schemas, isLoading } = useQuery({
    queryKey: ["schemas"],
    queryFn: () => api.listSchemas(),
  });

  const { data: mySchemas } = useQuery({
    queryKey: ["mySchemas"],
    queryFn: () => api.getMySchemas(),
    enabled: !!user,
  });

  // Fetch pending schemas for admin review
  const { data: pendingSchemas } = useQuery({
    queryKey: ["pendingSchemas"],
    queryFn: () => api.getPendingSchemas(),
    enabled: isAdmin,
  });

  // Get unique doc types from schemas
  const docTypes = useMemo(() => {
    if (!schemas) return [];
    const types = new Set(schemas.map((s) => s.doc_type));
    return Array.from(types).sort();
  }, [schemas]);

  // Filter published schemas for display
  const filteredPublishedSchemas = useMemo(() => {
    if (!schemas) return [];
    return schemas.filter((schema) => {
      // Only show published schemas
      if (schema.status !== "published") return false;
      const matchesType = docTypeFilter === "all" || schema.doc_type === docTypeFilter;
      const matchesSearch =
        !searchQuery ||
        schema.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
        schema.doc_type.toLowerCase().includes(searchQuery.toLowerCase()) ||
        schema.description?.toLowerCase().includes(searchQuery.toLowerCase());
      return matchesType && matchesSearch;
    });
  }, [schemas, docTypeFilter, searchQuery]);

  const deleteMutation = useMutation({
    mutationFn: (schemaId: string) => api.deleteSchema(schemaId),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schemas"] });
      queryClient.invalidateQueries({ queryKey: ["mySchemas"] });
      toast({ title: "Schema deleted", description: "The schema has been deleted." });
      setDeleteSchema(null);
    },
    onError: (error) => {
      toast({
        title: "Delete failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    },
  });

  const publishMutation = useMutation({
    mutationFn: ({ schemaId, comment }: { schemaId: string; comment: string }) =>
      api.publishSchema(schemaId, comment),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["schemas"] });
      queryClient.invalidateQueries({ queryKey: ["mySchemas"] });
      toast({
        title: "Schema submitted",
        description: "Your schema has been submitted for admin review.",
      });
      setPublishSchema(null);
      setPublishComment("");
    },
    onError: (error) => {
      toast({
        title: "Publish failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    },
  });

  const reviewMutation = useMutation({
    mutationFn: ({ schemaId, approved, notes }: { schemaId: string; approved: boolean; notes?: string }) =>
      api.reviewSchema(schemaId, approved, notes),
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
      setReviewSchema(null);
      setReviewNotes("");
    },
    onError: (error) => {
      toast({
        title: "Review failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    },
  });

  // Clone handler - navigates to new schema page with cloned data
  const handleCloneSchema = (schema: Schema) => {
    toast({
      title: "Schema copied",
      description: "Edit and save to create your copy.",
    });
    // Navigate to new schema page with clone parameter
    router.push(`/schemas/new?clone=${schema.id}`);
  };

  // Filter my schemas (owned by user, NOT published - draft/pending/rejected only)
  const myNonPublishedSchemas = useMemo(() => {
    if (!mySchemas) return [];
    return mySchemas.filter((schema) => schema.status !== "published");
  }, [mySchemas]);

  // Get unique doc types from my non-published schemas
  const myDocTypes = useMemo(() => {
    if (!myNonPublishedSchemas.length) return [];
    const types = new Set(myNonPublishedSchemas.map((s) => s.doc_type));
    return Array.from(types).sort();
  }, [myNonPublishedSchemas]);

  // Filter my non-published schemas for display
  const filteredMySchemas = useMemo(() => {
    return myNonPublishedSchemas.filter((schema) => {
      const matchesType = myDocTypeFilter === "all" || schema.doc_type === myDocTypeFilter;
      const matchesSearch =
        !mySearchQuery ||
        schema.name.toLowerCase().includes(mySearchQuery.toLowerCase()) ||
        schema.doc_type.toLowerCase().includes(mySearchQuery.toLowerCase()) ||
        schema.description?.toLowerCase().includes(mySearchQuery.toLowerCase());
      return matchesType && matchesSearch;
    });
  }, [myNonPublishedSchemas, myDocTypeFilter, mySearchQuery]);

  // Published schemas - ALL published schemas (including user's own)
  const publishedSchemas = useMemo(() => {
    if (!schemas) return [];
    return schemas.filter((schema) => schema.status === "published");
  }, [schemas]);

  // Helper to render a schema card
  const renderSchemaCard = (schema: Schema, showPublishAction: boolean = false) => {
    const statusBadge = getStatusBadge(schema.status);
    const StatusIcon = statusBadge.icon;
    const isOwner = user && schema.owner_id === user.id;
    const canPublish = isOwner && (schema.status === "draft" || schema.status === "rejected");
    // For published schemas, only admin can edit/delete
    const canEdit = schema.status === "published" ? isAdmin : (isOwner || isAdmin);
    const canDelete = schema.status === "published" ? isAdmin : (isOwner || isAdmin);

    return (
      <Card
        key={schema.id}
        className={cn(
          "relative transition-all cursor-pointer hover:shadow-md",
          schema.is_default && "border-primary/20"
        )}
        onClick={() => router.push(`/schemas/${schema.id}`)}
      >
        {/* Action buttons - pill group at top right */}
        <div className="absolute top-2 right-2 flex items-center bg-muted/80 rounded-full px-1 py-0.5 z-10" onClick={(e) => e.stopPropagation()}>
          {showPublishAction && canPublish && (
            <button
              className="p-1 rounded-full hover:bg-background/80 transition-colors"
              onClick={(e) => { e.stopPropagation(); setPublishSchema(schema); }}
              title={schema.status === "rejected" ? "Resubmit for Review" : "Submit for Review"}
            >
              {schema.status === "rejected" ? (
                <RefreshCw className="h-3 w-3 text-amber-500" />
              ) : (
                <Send className="h-3 w-3 text-primary" />
              )}
            </button>
          )}
          <button
            className="p-1 rounded-full hover:bg-background/80 transition-colors"
            onClick={(e) => { e.stopPropagation(); handleCloneSchema(schema); }}
            title="Clone Schema"
          >
            <Copy className="h-3 w-3 text-muted-foreground" />
          </button>
          {canEdit && (
            <Link href={`/schemas/${schema.id}`} onClick={(e) => e.stopPropagation()}>
              <button className="p-1 rounded-full hover:bg-background/80 transition-colors" title="Edit Schema">
                <Edit2 className="h-3 w-3 text-muted-foreground" />
              </button>
            </Link>
          )}
          {!schema.is_default && canDelete && (
            <button
              className="p-1 rounded-full hover:bg-background/80 transition-colors"
              onClick={(e) => { e.stopPropagation(); setDeleteSchema(schema); }}
              title="Delete Schema"
            >
              <Trash2 className="h-3 w-3 text-destructive/70" />
            </button>
          )}
        </div>

        <CardHeader className="pb-3">
          <div className="space-y-1.5">
            <CardTitle className="text-base flex items-center gap-2 pr-20">
              <Layout className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              <span className="truncate" title={schema.name}>{schema.name}</span>
            </CardTitle>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className="text-xs">{formatDocType(schema.doc_type)}</Badge>
              {schema.is_default && (
                <Badge variant="secondary" className="text-xs">
                  Default
                </Badge>
              )}
              {showPublishAction && !schema.is_default && (
                <Badge variant={statusBadge.variant} className="text-xs flex items-center gap-1">
                  <StatusIcon className="h-3 w-3" />
                  {statusBadge.label}
                </Badge>
              )}
              {!showPublishAction && !isOwner && schema.owner && (
                <Badge variant="outline" className="text-xs font-normal bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/30 dark:text-purple-300 dark:border-purple-800">
                  <User className="h-3 w-3 mr-1" />
                  {schema.owner.display_name || schema.owner.username || "Unknown"}
                </Badge>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
            {schema.description || "No description"}
          </p>
          {schema.review_notes && schema.status === "rejected" && (
            <p className="text-xs text-destructive bg-destructive/10 rounded p-2 mb-3">
              Feedback: {schema.review_notes}
            </p>
          )}
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <LayersIcon size={12} />
              {schema.parts_config?.length || 0} parts
            </span>
            {schema.created_at && (
              <span>{formatDate(schema.created_at)}</span>
            )}
          </div>
        </CardContent>
      </Card>
    );
  };

  // Helper to render a pending schema card for admin review
  const renderPendingSchemaCard = (schema: Schema) => {
    return (
      <Card
        key={schema.id}
        className="relative transition-all cursor-pointer hover:shadow-md border-yellow-200 dark:border-yellow-800"
        onClick={() => router.push(`/schemas/${schema.id}`)}
      >
        {/* Needs Review Banner */}
        <div className="absolute top-0 left-0 right-0 bg-yellow-100 dark:bg-yellow-900/30 px-3 py-1.5 rounded-t-lg border-b border-yellow-200 dark:border-yellow-800">
          <div className="flex items-center justify-between">
            <span className="text-xs font-medium text-yellow-700 dark:text-yellow-400 flex items-center gap-1">
              <Clock className="h-3 w-3" />
              Needs your review
            </span>
            <button
              className="text-xs font-medium text-primary hover:underline"
              onClick={(e) => { e.stopPropagation(); setReviewSchema(schema); }}
            >
              Review
            </button>
          </div>
        </div>

        <CardHeader className="pb-3 pt-10">
          <div className="space-y-1.5">
            <CardTitle className="text-base flex items-center gap-2">
              <Layout className="h-4 w-4 text-muted-foreground flex-shrink-0" />
              <span className="truncate" title={schema.name}>{schema.name}</span>
            </CardTitle>
            <div className="flex flex-wrap items-center gap-1.5">
              <Badge variant="outline" className="text-xs">{formatDocType(schema.doc_type)}</Badge>
              <Badge variant="secondary" className="text-xs flex items-center gap-1 border-yellow-500 text-yellow-600 bg-yellow-50 dark:bg-yellow-950/30">
                <Clock className="h-3 w-3" />
                Pending
              </Badge>
              {schema.owner && (
                <Badge variant="outline" className="text-xs font-normal bg-purple-50 text-purple-700 border-purple-200 dark:bg-purple-950/30 dark:text-purple-300 dark:border-purple-800">
                  <User className="h-3 w-3 mr-1" />
                  {schema.owner.display_name || schema.owner.username || "Unknown"}
                </Badge>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <p className="text-sm text-muted-foreground line-clamp-2 mb-3">
            {schema.description || "No description"}
          </p>
          <div className="flex items-center justify-between text-xs text-muted-foreground">
            <span className="flex items-center gap-1">
              <LayersIcon size={12} />
              {schema.parts_config?.length || 0} parts
            </span>
            {schema.created_at && (
              <span>{formatDate(schema.created_at)}</span>
            )}
          </div>
        </CardContent>
      </Card>
    );
  };

  return (
    <div className="container mx-auto py-6 px-4 max-w-6xl">
      <div className="flex items-center justify-between mb-6">
        <div>
          <h1 className="text-2xl font-bold">Schemas</h1>
          <p className="text-muted-foreground">
            Define extraction schemas for any document type
          </p>
        </div>
        <Button onClick={() => router.push("/schemas/new")}>
          <PlusIcon size={16} className="mr-2" />
          New Schema
        </Button>
      </div>

      {/* Stats - Clean professional monochrome design */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3 mb-6">
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">{schemas?.length || 0}</div>
                <p className="text-xs text-muted-foreground">Total Schemas</p>
              </div>
              <LayersIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">{docTypes.length}</div>
                <p className="text-xs text-muted-foreground">Document Types</p>
              </div>
              <FileTextIcon size={20} className="text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">
                  {schemas?.filter((s) => s.is_default).length || 0}
                </div>
                <p className="text-xs text-muted-foreground">Default Schemas</p>
              </div>
              <Star className="w-5 h-5 text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
        <Card className="bg-card/50">
          <CardContent className="p-4">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-2xl font-semibold">{myNonPublishedSchemas?.length || 0}</div>
                <p className="text-xs text-muted-foreground">My Schemas</p>
              </div>
              <User className="w-5 h-5 text-muted-foreground/50" />
            </div>
          </CardContent>
        </Card>
      </div>

      {/* Pending Review Section - Only visible to admins */}
      {isAdmin && pendingSchemas && pendingSchemas.length > 0 && (
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-4">
            <Clock className="h-5 w-5 text-yellow-600" />
            <h2 className="text-lg font-semibold">Pending Review</h2>
            <Badge variant="secondary" className="bg-yellow-100 text-yellow-700">
              {pendingSchemas.length}
            </Badge>
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {pendingSchemas.map((schema) => renderPendingSchemaCard(schema))}
          </div>
        </div>
      )}

      {/* My Schemas Section - only non-published schemas */}
      {user && myNonPublishedSchemas && myNonPublishedSchemas.length > 0 && (
        <div className="mb-8">
          <div className="flex items-center gap-2 mb-4">
            <User className="h-5 w-5 text-muted-foreground" />
            <h2 className="text-lg font-semibold">My Schemas</h2>
            <Badge variant="secondary" className="text-xs">
              {myNonPublishedSchemas.length}
            </Badge>
          </div>

          {/* Filters */}
          <div className="flex items-center gap-4 mb-6">
            <div className="relative flex-1 max-w-sm">
              <SearchIcon size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
              <Input
                placeholder="Search my schemas..."
                value={mySearchQuery}
                onChange={(e) => setMySearchQuery(e.target.value)}
                className="pl-9"
              />
            </div>
            <Select value={myDocTypeFilter} onValueChange={setMyDocTypeFilter}>
              <SelectTrigger className="w-[180px]">
                <SelectValue placeholder="All Types" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">All Types</SelectItem>
                {myDocTypes.map((type) => (
                  <SelectItem key={type} value={type}>
                    {formatDocType(type)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>

          {filteredMySchemas.length === 0 ? (
            <Card>
              <CardContent className="flex flex-col items-center justify-center py-12">
                <div className="w-14 h-14 rounded-full bg-muted flex items-center justify-center mb-3">
                  <FileJson className="h-7 w-7 text-muted-foreground" />
                </div>
                <h3 className="text-base font-semibold mb-1">No matching schemas found</h3>
                <p className="text-sm text-muted-foreground text-center">
                  Try adjusting your filters or search terms
                </p>
              </CardContent>
            </Card>
          ) : (
            <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
              {filteredMySchemas.map((schema) => renderSchemaCard(schema, true))}
            </div>
          )}
        </div>
      )}

      {/* Published Schemas Section */}
      <div>
        <div className="flex items-center gap-2 mb-4">
          <Globe className="h-5 w-5 text-blue-500" />
          <h2 className="text-lg font-semibold">Published Schemas</h2>
          <Badge variant="secondary" className="text-xs bg-blue-100 text-blue-700">
            {publishedSchemas.length}
          </Badge>
        </div>

        {/* Filters */}
        <div className="flex items-center gap-4 mb-6">
          <div className="relative flex-1 max-w-sm">
            <SearchIcon size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
            <Input
              placeholder="Search schemas..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              className="pl-9"
            />
          </div>
          <Select value={docTypeFilter} onValueChange={setDocTypeFilter}>
            <SelectTrigger className="w-[180px]">
              <SelectValue placeholder="All Types" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">All Types</SelectItem>
              {docTypes.map((type) => (
                <SelectItem key={type} value={type}>
                  {formatDocType(type)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>

        {/* Schema Grid */}
        {isLoading ? (
          <div className="flex items-center justify-center py-12">
            <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          </div>
        ) : filteredPublishedSchemas.length === 0 ? (
          <Card>
            <CardContent className="flex flex-col items-center justify-center py-16">
              <div className="w-16 h-16 rounded-full bg-muted flex items-center justify-center mb-4">
                <FileJson className="h-8 w-8 text-muted-foreground" />
              </div>
              <h3 className="text-lg font-semibold mb-1">No published schemas found</h3>
              <p className="text-sm text-muted-foreground mb-6 text-center max-w-sm">
                {searchQuery || docTypeFilter !== "all"
                  ? "Try adjusting your filters or search terms"
                  : "No schemas have been published yet"}
              </p>
            </CardContent>
          </Card>
        ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
            {filteredPublishedSchemas.map((schema) => renderSchemaCard(schema, false))}
          </div>
        )}
      </div>

      {/* Delete Confirmation Dialog */}
      <Dialog open={!!deleteSchema} onOpenChange={() => setDeleteSchema(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Schema</DialogTitle>
            <DialogDescription>
              Are you sure you want to delete "{deleteSchema?.name}"? This action
              cannot be undone.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setDeleteSchema(null)}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => deleteSchema && deleteMutation.mutate(deleteSchema.id)}
              disabled={deleteMutation.isPending}
            >
              {deleteMutation.isPending && (
                <Loader2 className="h-4 w-4 animate-spin mr-2" />
              )}
              Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Publish Confirmation Dialog */}
      <Dialog open={!!publishSchema} onOpenChange={(open) => {
        if (!open) {
          setPublishSchema(null);
          setPublishComment("");
        }
      }}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {publishSchema?.status === "rejected" ? "Resubmit Schema for Review" : "Submit Schema for Review"}
            </DialogTitle>
            <DialogDescription>
              You are about to submit <span className="font-medium">{publishSchema?.name}</span> for admin review.
              Once approved, this schema will be published and visible to all users.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="publish-comment">
                Comments <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="publish-comment"
                placeholder="Describe what this schema does and why it should be published..."
                value={publishComment}
                onChange={(e) => setPublishComment(e.target.value)}
                rows={3}
                autoFocus
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => {
              setPublishSchema(null);
              setPublishComment("");
            }}>
              Cancel
            </Button>
            <Button
              onClick={() =>
                publishSchema &&
                publishMutation.mutate({
                  schemaId: publishSchema.id,
                  comment: publishComment.trim(),
                })
              }
              disabled={!publishComment.trim() || publishMutation.isPending}
            >
              {publishMutation.isPending ? (
                <>
                  <Loader2 className="h-4 w-4 animate-spin mr-2" />
                  Submitting...
                </>
              ) : (
                <>
                  <Send className="h-4 w-4 mr-2" />
                  {publishSchema?.status === "rejected" ? "Resubmit" : "Submit for Review"}
                </>
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Review Schema Dialog - Admin only */}
      <Dialog open={!!reviewSchema} onOpenChange={(open) => {
        if (!open) {
          setReviewSchema(null);
          setReviewNotes("");
        }
      }}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Review Schema</DialogTitle>
            <DialogDescription>
              Review and approve or reject "{reviewSchema?.name}"
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            {reviewSchema && (
              <div className="space-y-3">
                <div className="flex items-center gap-2">
                  <Layout className="h-4 w-4 text-muted-foreground" />
                  <span className="font-medium">{reviewSchema.name}</span>
                  <Badge variant="outline">{formatDocType(reviewSchema.doc_type)}</Badge>
                </div>
                <p className="text-sm text-muted-foreground">
                  {reviewSchema.description || "No description provided"}
                </p>
                {reviewSchema.owner && (
                  <p className="text-xs text-muted-foreground">
                    Submitted by: <span className="font-medium">{reviewSchema.owner.display_name || reviewSchema.owner.username}</span>
                  </p>
                )}
                {reviewSchema.submit_notes && (
                  <div className="rounded-md border bg-muted/40 p-3">
                    <p className="text-xs font-medium text-muted-foreground mb-1">Publisher Comment</p>
                    <p className="text-sm">{reviewSchema.submit_notes}</p>
                  </div>
                )}
              </div>
            )}
            <div className="space-y-2">
              <Label htmlFor="review-notes">
                Review Notes <span className="text-red-500">*</span>
              </Label>
              <Textarea
                id="review-notes"
                value={reviewNotes}
                onChange={(e) => setReviewNotes(e.target.value)}
                placeholder="Add feedback or notes for the schema owner (required)..."
                rows={3}
              />
              <p className="text-xs text-muted-foreground">
                Review notes are required to approve or reject a schema.
              </p>
            </div>
          </div>
          <DialogFooter className="gap-2 sm:gap-0">
            <Button variant="outline" onClick={() => {
              setReviewSchema(null);
              setReviewNotes("");
            }}>
              Cancel
            </Button>
            <Button
              variant="destructive"
              onClick={() => reviewSchema && reviewMutation.mutate({
                schemaId: reviewSchema.id,
                approved: false,
                notes: reviewNotes,
              })}
              disabled={reviewMutation.isPending || !reviewNotes.trim()}
            >
              {reviewMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <XCircle className="h-4 w-4 mr-1" />
              Reject
            </Button>
            <Button
              onClick={() => reviewSchema && reviewMutation.mutate({
                schemaId: reviewSchema.id,
                approved: true,
                notes: reviewNotes,
              })}
              disabled={reviewMutation.isPending || !reviewNotes.trim()}
            >
              {reviewMutation.isPending && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
              <CheckCircle2 className="h-4 w-4 mr-1" />
              Approve & Publish
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
