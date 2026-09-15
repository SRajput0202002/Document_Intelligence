"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useMutation, useQueryClient, useQuery } from "@tanstack/react-query";
import { useDropzone } from "react-dropzone";
import { Loader2 } from "lucide-react";

// Helper functions for file type detection
const IMAGE_EXTENSIONS = ['.jpg', '.jpeg', '.png', '.gif', '.bmp', '.webp', '.tiff', '.tif', '.heic', '.heif'];
const CONVERTIBLE_EXTENSIONS = ['.docx', '.xlsx', '.doc', '.xls', '.txt', '.rtf', '.csv'];

function isPreviewableImage(filename: string): boolean {
  const ext = filename.toLowerCase().slice(filename.lastIndexOf('.'));
  return IMAGE_EXTENSIONS.includes(ext);
}

function isPDF(filename: string): boolean {
  return filename.toLowerCase().endsWith('.pdf');
}

function needsConversion(filename: string): boolean {
  const ext = filename.toLowerCase().slice(filename.lastIndexOf('.'));
  return CONVERTIBLE_EXTENSIONS.includes(ext);
}

// Helper to format doc_type for display (snake_case to Title Case)
function formatDocType(docType: string): string {
  return docType
    .split("_")
    .map((word) => word.charAt(0).toUpperCase() + word.slice(1))
    .join(" ");
}
// Animated icons
import { ArrowLeftIcon } from "@/components/ui/arrow-left";
import { UploadIcon } from "@/components/ui/upload";
import { FileTextIcon } from "@/components/ui/file-text";
import { XIcon } from "@/components/ui/x";
import { ScanTextIcon } from "@/components/ui/scan-text";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { toast } from "@/components/ui/toast";
import { api, type SchemaInferenceResult } from "@/lib/api";
import { SchemaBuilder, type SchemaField, fieldsToJsonSchema, jsonSchemaToFields } from "@/components/schema-builder";
import { PDFViewer } from "@/components/pdf-viewer";
import { cn } from "@/lib/utils";

export default function NewSchemaPage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const [file, setFile] = useState<File | null>(null);
  const [imagePreviewUrl, setImagePreviewUrl] = useState<string | null>(null);
  const [convertedPdfBlob, setConvertedPdfBlob] = useState<Blob | null>(null);
  const [isConverting, setIsConverting] = useState(false);
  const [conversionError, setConversionError] = useState<string | null>(null);

  // Clone schema state
  const cloneId = searchParams.get("clone");
  const { data: clonedSchema, isLoading: isLoadingClone } = useQuery({
    queryKey: ["schema", cloneId],
    queryFn: () => api.getSchema(cloneId!),
    enabled: !!cloneId,
  });

  // Schema inference state
  const [isInferring, setIsInferring] = useState(false);
  const [inferredSchema, setInferredSchema] = useState<SchemaInferenceResult | null>(null);
  const [inferredFields, setInferredFields] = useState<SchemaField[]>([]);

  // Cloned schema fields state
  const [clonedFields, setClonedFields] = useState<SchemaField[]>([]);

  // Convert cloned schema to fields when loaded - instructions are now embedded in json_schema
  useEffect(() => {
    if (clonedSchema) {
      const schemaFields = clonedSchema.json_schema
        ? jsonSchemaToFields(clonedSchema.json_schema)
        : [];
      setClonedFields(schemaFields);
    }
  }, [clonedSchema]);

  // Create object URL for image preview
  useEffect(() => {
    if (file && isPreviewableImage(file.name)) {
      const url = URL.createObjectURL(file);
      setImagePreviewUrl(url);
      return () => {
        URL.revokeObjectURL(url);
        setImagePreviewUrl(null);
      };
    } else {
      setImagePreviewUrl(null);
    }
  }, [file]);

  // Convert documents (DOCX, XLSX, etc.) to PDF for preview
  useEffect(() => {
    if (file && needsConversion(file.name)) {
      setIsConverting(true);
      setConversionError(null);
      setConvertedPdfBlob(null);

      api.convertForPreview(file)
        .then((blob) => {
          setConvertedPdfBlob(blob);
          setIsConverting(false);
        })
        .catch((err) => {
          console.error("Document conversion failed:", err);
          setConversionError(err.message || "Failed to convert document");
          setIsConverting(false);
        });
    } else {
      setConvertedPdfBlob(null);
      setConversionError(null);
    }
  }, [file]);

  const onDrop = useCallback((acceptedFiles: File[]) => {
    if (acceptedFiles.length > 0) {
      setFile(acceptedFiles[0]);
      // Reset inferred data when new file is uploaded
      setInferredSchema(null);
      setInferredFields([]);
    }
  }, []);

  // Convert JSON schema to SchemaField[]
  const jsonSchemaToFields = (schema: Record<string, unknown>): SchemaField[] => {
    const properties = schema.properties as Record<string, Record<string, unknown>> || {};
    const required = (schema.required as string[]) || [];

    return Object.entries(properties).map(([name, prop], index) => {
      const field: SchemaField = {
        id: `field-${index}-${Date.now()}`,
        name,
        type: (prop.type as SchemaField["type"]) || "string",
        required: required.includes(name),
        description: prop.description as string | undefined,
      };

      // Handle nested objects
      if (prop.type === "object" && prop.properties) {
        field.children = jsonSchemaToFields(prop as Record<string, unknown>);
      }

      // Handle arrays with object items
      if (prop.type === "array" && prop.items) {
        const items = prop.items as Record<string, unknown>;
        if (items.type === "object" && items.properties) {
          field.children = jsonSchemaToFields(items);
        }
      }

      return field;
    });
  };

  // Infer schema from document
  // Uses user's settings for OCR and LLM providers (document_classifier, fallback_ocr)
  const handleInferSchema = async () => {
    if (!file) return;

    setIsInferring(true);
    try {
      // Don't pass providers - let backend use user settings
      const result = await api.inferSchema(file);
      setInferredSchema(result);

      // Convert JSON schema to SchemaField[]
      const fields = jsonSchemaToFields(result.json_schema);
      setInferredFields(fields);

      toast({
        title: "Schema generated",
        description: `Detected ${fields.length} fields from your document`,
      });
    } catch (err) {
      console.error("Schema inference failed:", err);
      toast({
        title: "Inference failed",
        description: err instanceof Error ? err.message : "Could not analyze document",
        variant: "destructive",
      });
    } finally {
      setIsInferring(false);
    }
  };

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: {
      "application/pdf": [".pdf"],
      "image/*": [".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp", ".gif"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
      "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": [".xlsx"],
      "application/msword": [".doc"],
      "application/vnd.ms-excel": [".xls"],
      "text/plain": [".txt"],
      "text/csv": [".csv"],
      "application/rtf": [".rtf"],
    },
    maxFiles: 1,
  });

  const createMutation = useMutation({
    mutationFn: ({
      name,
      docType,
      schema,
      description,
    }: {
      name: string;
      docType: string;
      schema: Record<string, unknown>;
      description?: string;
    }) => api.createSchema(name, docType, schema, description),
    onSuccess: async (created) => {
      await queryClient.invalidateQueries({ queryKey: ["schemas"] });
      await queryClient.invalidateQueries({ queryKey: ["mySchemas"] });
      if (created?.id) {
        await queryClient.invalidateQueries({ queryKey: ["schema", created.id] });
      }
      toast({ title: "Schema created", description: "Your new schema has been created." });
      router.push("/schemas");
    },
    onError: (error) => {
      toast({
        title: "Create failed",
        description: error instanceof Error ? error.message : "Unknown error",
        variant: "destructive",
      });
    },
  });

  const handleSave = (fields: SchemaField[], schemaName: string, docType: string, description?: string) => {
    // Convert docType to snake_case for API (e.g., "Bill of Entry" -> "bill_of_entry")
    const formattedDocType = docType.toLowerCase().replace(/\s+/g, '_');

    // Instructions are now embedded in json_schema via fieldsToJsonSchema
    const jsonSchema = fieldsToJsonSchema(fields);
    createMutation.mutate({
      name: schemaName,
      docType: formattedDocType,
      schema: jsonSchema as Record<string, unknown>,
      description,
    });
  };

  const handleCancel = () => {
    router.back();
  };

  // Document preview component (left side)
  const documentPreview = file ? (
    <div className="h-full flex flex-col">
      {/* File header */}
      <div className="px-4 py-3 border-b border-border bg-card">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 min-w-0">
            <FileTextIcon size={16} className="text-muted-foreground flex-shrink-0" />
            <span className="text-sm font-medium truncate">{file.name}</span>
          </div>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7 flex-shrink-0"
            onClick={() => {
              setFile(null);
              setInferredSchema(null);
              setInferredFields([]);
              setConvertedPdfBlob(null);
              setConversionError(null);
            }}
          >
            <XIcon size={16} />
          </Button>
        </div>
      </div>
      {/* Document Viewer - conditional for PDF vs Image vs Convertible */}
      <div className="flex-1 overflow-hidden">
        {isPDF(file.name) ? (
          <PDFViewer file={file} showToolbar={true} />
        ) : imagePreviewUrl ? (
          <div className="h-full flex flex-col items-center justify-center p-4 bg-muted/30 overflow-auto">
            <img
              src={imagePreviewUrl}
              alt={file.name}
              className="max-w-full max-h-full object-contain rounded-lg shadow-sm"
            />
            <p className="text-xs text-muted-foreground mt-3 text-center">
              Image preview - Will be converted to PDF for processing
            </p>
          </div>
        ) : isConverting ? (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
            <Loader2 className="h-8 w-8 animate-spin mb-3" />
            <p className="text-sm">Converting document for preview...</p>
          </div>
        ) : conversionError ? (
          <div className="h-full flex flex-col items-center justify-center text-muted-foreground p-4">
            <FileTextIcon size={48} className="mb-3 opacity-50" />
            <p className="text-sm font-medium">{file.name}</p>
            <p className="text-xs text-destructive mt-2">{conversionError}</p>
          </div>
        ) : convertedPdfBlob ? (
          <PDFViewer file={convertedPdfBlob} showToolbar={true} />
        ) : (
          <div className="h-full flex items-center justify-center text-muted-foreground">
            <p className="text-sm">Document preview not available</p>
          </div>
        )}
      </div>
    </div>
  ) : (
    <div className="h-full flex flex-col">
      {/* Upload header */}
      <div className="px-4 py-3 border-b border-border bg-card">
        <h3 className="text-sm font-medium">Reference Document</h3>
        <p className="text-xs text-muted-foreground">Optional: Upload a document to help design your schema</p>
      </div>
      {/* Dropzone */}
      <div className="flex-1 p-4">
        <div
          {...getRootProps()}
          className={cn(
            "h-full border-2 border-dashed rounded-lg flex flex-col items-center justify-center cursor-pointer transition-all",
            isDragActive
              ? "border-primary bg-primary/5"
              : "border-border hover:border-primary/50 hover:bg-muted/30"
          )}
        >
          <input {...getInputProps()} />
          <div className={cn(
            "w-12 h-12 rounded-lg flex items-center justify-center mb-4",
            isDragActive ? "bg-primary text-primary-foreground" : "bg-muted"
          )}>
            <UploadIcon size={20} />
          </div>
          <p className="text-sm font-medium mb-1">
            {isDragActive ? "Drop here" : "Drop a document here"}
          </p>
          <p className="text-xs text-muted-foreground mb-4">
            or click to browse
          </p>
          <div className="flex items-center gap-2 text-xs text-muted-foreground flex-wrap justify-center">
            <span>PDF</span>
            <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
            <span>Images</span>
            <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
            <span>DOCX, XLSX</span>
          </div>
        </div>
      </div>
    </div>
  );

  // Determine initial values - prioritize inferred, then cloned
  const getInitialFields = () => {
    if (inferredFields.length > 0) return inferredFields;
    if (clonedFields.length > 0) return clonedFields;
    return undefined;
  };

  const getInitialName = () => {
    if (inferredSchema?.schema_name) return inferredSchema.schema_name;
    if (clonedSchema) return `${clonedSchema.name} (Copy)`;
    return undefined;
  };

  const getInitialDocType = () => {
    if (inferredSchema?.document_type) return formatDocType(inferredSchema.document_type);
    if (clonedSchema?.doc_type) return formatDocType(clonedSchema.doc_type);
    return undefined;
  };

  const isCloneMode = !!cloneId;

  // Show loading while fetching clone data
  if (isCloneMode && isLoadingClone) {
    return (
      <div className="h-screen flex items-center justify-center">
        <div className="flex flex-col items-center gap-3">
          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
          <p className="text-sm text-muted-foreground">Loading schema...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="border-b border-border px-4 py-3 bg-card flex items-center justify-between flex-shrink-0">
        <div className="flex items-center gap-3">
          <Button variant="ghost" size="icon" className="h-8 w-8" onClick={handleCancel}>
            <ArrowLeftIcon size={16} />
          </Button>
          <div>
            <h1 className="text-lg font-semibold">
              {isCloneMode ? "Clone Schema" : "Create New Schema"}
            </h1>
            <p className="text-xs text-muted-foreground">
              {isCloneMode
                ? `Creating a copy of "${clonedSchema?.name}"`
                : "Define the structure of data to extract from documents"}
            </p>
          </div>
        </div>
      </div>

      {/* Main content - SchemaBuilder with optional document preview */}
      <div className="flex-1 overflow-hidden">
        <SchemaBuilder
          key={inferredFields.length > 0 ? "inferred" : clonedFields.length > 0 ? "cloned" : "empty"}
          documentPreview={documentPreview}
          onSave={handleSave}
          onCancel={handleCancel}
          initialFields={getInitialFields()}
          initialName={getInitialName()}
          initialDocType={getInitialDocType()}
          initialDescription={clonedSchema?.description}
          isLoading={isInferring}
          onGenerateSchema={file ? handleInferSchema : undefined}
          isGenerating={isInferring}
        />
      </div>
    </div>
  );
}
