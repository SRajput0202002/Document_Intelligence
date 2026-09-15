"use client";

import { useState, useCallback, useEffect, useMemo } from "react";
import dynamic from "next/dynamic";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  DragEndEvent,
  DragStartEvent,
  DragOverlay,
  defaultDropAnimationSideEffects,
} from "@dnd-kit/core";
import {
  arrayMove,
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import {
  Trash2,
  GripVertical,
  Type,
  Hash,
  ToggleLeft,
  List,
  Braces,
  Calendar,
  Save,
  Code,
  AlertCircle,
  Loader2,
  ChevronsUpDown,
  Sparkles,
  FileSearch,
  Brain,
  Wand2,
  Zap,
  MessageSquareText,
  CheckCircle2,
  XCircle,
  QrCode,
  PenLine,
} from "lucide-react";

// Animated icons
import { PlusIcon } from "@/components/ui/plus";
import { ChevronDownIcon } from "@/components/ui/chevron-down";
import { CheckIcon } from "@/components/ui/check";
import { XIcon } from "@/components/ui/x";
import { EyeIcon } from "@/components/ui/eye";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { UploadIcon } from "@/components/ui/upload";
import { ScanTextIcon } from "@/components/ui/scan-text";

// Dynamically import Monaco Editor to avoid SSR issues
const MonacoEditor = dynamic(() => import("@monaco-editor/react"), {
  ssr: false,
  loading: () => (
    <div className="flex-1 flex items-center justify-center bg-muted/30">
      <div className="flex flex-col items-center gap-3">
        <div className="w-6 h-6 border-2 border-primary border-t-transparent rounded-full animate-spin" />
        <span className="text-muted-foreground text-sm">Loading editor...</span>
      </div>
    </div>
  ),
});
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Switch } from "@/components/ui/switch";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { ScrollArea } from "@/components/ui/scroll-area";
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
import { Textarea } from "@/components/ui/textarea";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { cn } from "@/lib/utils";
import { toast } from "@/components/ui/toast";

const DOCUMENT_TYPE_SUGGESTIONS = [
  "Invoice",
  "Bill of Entry",
  "Shipping Bill",
  "Purchase Order",
  "Receipt",
  "Contract",
];

export interface SchemaField {
  id: string;
  name: string;
  type: "string" | "number" | "boolean" | "array" | "object" | "date" | "instruction" | "barcode" | "signature";
  required: boolean;
  description?: string;
  children?: SchemaField[];
  isExpanded?: boolean;
}

interface SchemaBuilderProps {
  initialFields?: SchemaField[];
  initialName?: string;
  initialDescription?: string;
  initialDocType?: string;
  onSave: (fields: SchemaField[], schemaName: string, docType: string, description?: string) => void;
  onCancel: () => void;
  documentPreview?: React.ReactNode;
  mode?: "create" | "edit";
  isLoading?: boolean;
  isReadOnly?: boolean;
  isSaving?: boolean;
  onGenerateSchema?: () => void;
  isGenerating?: boolean;
  // Review mode props for admin reviewing pending schemas
  isReviewMode?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
  isReviewing?: boolean;
}

const fieldTypeIcons: Record<SchemaField["type"], React.ReactNode> = {
  string: <Type className="w-3.5 h-3.5" />,
  number: <Hash className="w-3.5 h-3.5" />,
  boolean: <ToggleLeft className="w-3.5 h-3.5" />,
  array: <List className="w-3.5 h-3.5" />,
  object: <Braces className="w-3.5 h-3.5" />,
  date: <Calendar className="w-3.5 h-3.5" />,
  instruction: <MessageSquareText className="w-3.5 h-3.5" />,
  barcode: <QrCode className="w-3.5 h-3.5" />,
  signature: <PenLine className="w-3.5 h-3.5" />,
};

const fieldTypeColors: Record<SchemaField["type"], string> = {
  string: "text-blue-600 bg-blue-50",
  number: "text-emerald-600 bg-emerald-50",
  boolean: "text-violet-600 bg-violet-50",
  array: "text-amber-600 bg-amber-50",
  object: "text-rose-600 bg-rose-50",
  date: "text-cyan-600 bg-cyan-50",
  instruction: "text-orange-600 bg-orange-50",
  barcode: "text-indigo-600 bg-indigo-50",
  signature: "text-fuchsia-600 bg-fuchsia-50",
};

function generateId(): string {
  return Math.random().toString(36).substr(2, 9);
}

// Reserved JSON Schema keywords that should not be treated as fields
const RESERVED_SCHEMA_KEYS = new Set([
  "$schema", "$id", "$ref", "definitions", "$defs", "type", "required",
  "description", "title", "default", "examples", "enum", "const",
  "allOf", "anyOf", "oneOf", "not", "if", "then", "else",
  "x-section-structure", "x-metadata", "additionalProperties",
  "minProperties", "maxProperties", "propertyNames", "patternProperties"
]);

// Extract fields from x-section-structure.fields array (custom format)
function extractFieldsFromSectionStructure(sectionStructure: Record<string, unknown>): SchemaField[] {
  const fieldNames = sectionStructure.fields as string[] | undefined;
  if (!fieldNames || !Array.isArray(fieldNames)) return [];

  return fieldNames.map((name) => ({
    id: generateId(),
    name: name,
    type: "string" as const, // Default to string since no type info is provided
    required: false,
    isExpanded: true,
  }));
}

// Convert custom_instructions string to an instruction field with children
export function instructionsToFields(customInstructions: string | undefined | null): SchemaField | null {
  if (!customInstructions) return null;

  const instructionLines = customInstructions
    .split("\n")
    .filter(line => line.trim());

  if (instructionLines.length === 0) return null;

  // Create children for each instruction line
  const children: SchemaField[] = instructionLines.map(instruction => ({
    id: generateId(),
    name: instruction.trim(),
    type: "string" as const,
    required: false,
    isExpanded: true,
  }));

  // Return the parent instruction field
  return {
    id: generateId(),
    name: "custom_instructions",
    type: "instruction" as const,
    required: false,
    isExpanded: true,
    children,
  };
}

// Convert JSON Schema back to SchemaField array
export function jsonSchemaToFields(
  schema: Record<string, unknown>,
  parentRequired: string[] = [],
  warnings: string[] = [],
  path: string = "root"
): SchemaField[] {
  const properties = schema.properties as Record<string, unknown> | undefined;
  const required = (schema.required as string[]) || parentRequired;

  // If there's a "properties" key, use it
  if (properties && typeof properties === "object") {
    const fields: SchemaField[] = [];
    for (const [name, propValue] of Object.entries(properties)) {
      const prop = propValue as Record<string, unknown>;
      const field = parsePropertyToField(name, prop, required.includes(name), warnings, `${path}.${name}`);
      if (field) fields.push(field);
    }
    return fields;
  }

  // Otherwise, look for direct object keys that might be field definitions
  const fields: SchemaField[] = [];
  for (const [name, value] of Object.entries(schema)) {
    // Skip reserved keys and non-objects
    if (RESERVED_SCHEMA_KEYS.has(name)) continue;
    if (typeof value !== "object" || value === null) continue;

    const prop = value as Record<string, unknown>;

    // Check if this looks like a field definition
    if (prop.type || prop.properties || prop.items || hasNestedFields(prop)) {
      const field = parsePropertyToField(name, prop, required.includes(name), warnings, `${path}.${name}`);
      if (field) fields.push(field);
    }
  }
  return fields;
}

// Check if an object has nested fields (properties that look like schema definitions)
function hasNestedFields(obj: Record<string, unknown>): boolean {
  for (const [key, value] of Object.entries(obj)) {
    if (RESERVED_SCHEMA_KEYS.has(key)) continue;
    if (typeof value === "object" && value !== null) {
      const v = value as Record<string, unknown>;
      if (v.type || v.properties || v.items) return true;
    }
  }
  return false;
}

// Parse a single property into a SchemaField
function parsePropertyToField(
  name: string,
  prop: Record<string, unknown>,
  isRequired: boolean,
  warnings: string[],
  path: string
): SchemaField | null {
  // Check if this is an instruction field (has x-field-type: "instruction")
  if (prop["x-field-type"] === "instruction") {
    const items = prop.items as Record<string, unknown> | undefined;
    const itemProps = items?.properties as Record<string, unknown> | undefined;

    const instructionChildren: SchemaField[] = [];
    if (itemProps) {
      for (const [, propValue] of Object.entries(itemProps)) {
        const instrProp = propValue as Record<string, unknown>;
        const displayName = instrProp["x-display-name"] as string;
        if (displayName) {
          instructionChildren.push({
            id: generateId(),
            name: displayName,
            type: "string",
            required: false,
            isExpanded: true,
          });
        }
      }
    }

    return {
      id: generateId(),
      name: "Instructions",
      type: "instruction",
      required: false,
      isExpanded: true,
      children: instructionChildren,
    };
  }

  // Barcode / signature special fields
  if (prop["x-field-type"] === "barcode") {
    return {
      id: generateId(),
      name: (prop["x-display-name"] as string) || name,
      type: "barcode",
      required: isRequired,
      description: prop.description as string | undefined,
      isExpanded: false,
    };
  }
  if (prop["x-field-type"] === "signature") {
    return {
      id: generateId(),
      name: (prop["x-display-name"] as string) || name,
      type: "signature",
      required: isRequired,
      description: prop.description as string | undefined,
      isExpanded: false,
    };
  }

  const rawType = (prop.type as string) || (prop.properties ? "object" : (prop.items ? "array" : "object"));
  let type: SchemaField["type"] = rawType === "integer" ? "number" : (rawType as SchemaField["type"]);

  // Validate type
  if (!["string", "number", "boolean", "array", "object", "date", "instruction", "barcode", "signature"].includes(type)) {
    warnings.push(
      `"${path}" has invalid type "${rawType}". Defaulted to "string". Allowed types: string, number, boolean, array, object, date, barcode, signature.`
    );
    type = "string";
  }

  const field: SchemaField = {
    id: generateId(),
    name,
    type,
    required: isRequired,
    description: prop.description as string | undefined,
    isExpanded: true,
  };

  // Handle nested objects
  if (type === "object") {
    // First check if there's a "properties" key
    if (prop.properties) {
      field.children = jsonSchemaToFields(prop as Record<string, unknown>, [], warnings, path);
    }
    // Check for custom x-section-structure with fields array
    else if (prop["x-section-structure"]) {
      const sectionStructure = prop["x-section-structure"] as Record<string, unknown>;
      const childFields = extractFieldsFromSectionStructure(sectionStructure);
      if (childFields.length > 0) {
        field.children = childFields;
      }
    }
    // Look for nested field definitions directly in the object
    else {
      const nestedFields = jsonSchemaToFields(prop as Record<string, unknown>, [], warnings, path);
      if (nestedFields.length > 0) {
        field.children = nestedFields;
      }
    }
  }

  // Handle arrays
  if (type === "array" && prop.items) {
    const items = prop.items as Record<string, unknown>;
    if (items.type === "object" || items.properties) {
      field.children = jsonSchemaToFields(items, [], warnings, `${path}[]`);
    } else if (hasNestedFields(items)) {
      field.children = jsonSchemaToFields(items, [], warnings, `${path}[]`);
    }
  }

  return field;
}

// Count all properties in a JSON schema
function countJsonSchemaProperties(schema: Record<string, unknown>): number {
  let count = 0;
  const countProperties = (obj: Record<string, unknown>): void => {
    const properties = obj.properties as Record<string, unknown> | undefined;
    if (properties) {
      for (const [, propValue] of Object.entries(properties)) {
        count++;
        const prop = propValue as Record<string, unknown>;
        if (prop.type === "object") {
          if (prop.properties) {
            countProperties(prop as Record<string, unknown>);
          } else if (prop["x-section-structure"]) {
            // Count fields from x-section-structure
            const sectionStructure = prop["x-section-structure"] as Record<string, unknown>;
            const fields = sectionStructure.fields as string[] | undefined;
            if (fields && Array.isArray(fields)) {
              count += fields.length;
            }
          }
        }
        if (prop.type === "array" && prop.items) {
          const items = prop.items as Record<string, unknown>;
          if (items.properties) {
            countProperties(items as Record<string, unknown>);
          }
        }
      }
    }
    // Also check for non-standard schema structures
    for (const [key, value] of Object.entries(obj)) {
      if (RESERVED_SCHEMA_KEYS.has(key)) continue;
      if (typeof value !== "object" || value === null) continue;
      const prop = value as Record<string, unknown>;
      if (prop.type === "object" && prop["x-section-structure"]) {
        count++; // Count the object field itself
        const sectionStructure = prop["x-section-structure"] as Record<string, unknown>;
        const fields = sectionStructure.fields as string[] | undefined;
        if (fields && Array.isArray(fields)) {
          count += fields.length;
        }
      }
    }
  };
  countProperties(schema);
  return count;
}

// Extract instruction fields and combine them into a string
export function extractInstructions(fieldsList: SchemaField[]): string {
  const instructions: string[] = [];

  // Find instruction type fields and extract their children's names as instructions
  fieldsList.forEach(field => {
    if (field.type === "instruction" && field.children) {
      field.children.forEach(child => {
        if (child.name?.trim()) {
          instructions.push(child.name.trim());
        }
      });
    }
  });

  return instructions.join("\n");
}

// Convert SchemaField array to JSON Schema (includes instruction fields with special marker)
export function fieldsToJsonSchema(fieldsList: SchemaField[], parentPath: string = ""): object {
  const properties: Record<string, object> = {};
  const required: string[] = [];
  const usedNames = new Set<string>();

  fieldsList.forEach((field, index) => {
    // Handle instruction fields specially - store with marker for runtime extraction
    if (field.type === "instruction") {
      const instructionProps: Record<string, object> = {};
      field.children?.forEach((child, childIndex) => {
        if (child.name?.trim()) {
          instructionProps[`instruction_${childIndex + 1}`] = {
            type: "string",
            "x-display-name": child.name.trim(),
          };
        }
      });

      if (Object.keys(instructionProps).length > 0) {
        properties["_instructions"] = {
          type: "array",
          "x-field-type": "instruction",
          items: {
            type: "object",
            properties: instructionProps,
          },
        };
      }
      return; // Skip normal processing for instruction fields
    }

    // Barcode: array of decoded codes (filled by feature pipeline, not LLM)
    if (field.type === "barcode") {
      let fieldName = field.name?.trim() || `barcode_field_${index + 1}`;
      let uniqueName = fieldName;
      let dupCounter = 1;
      while (usedNames.has(uniqueName)) {
        uniqueName = `${fieldName}_${dupCounter}`;
        dupCounter++;
      }
      usedNames.add(uniqueName);
      properties[uniqueName] = {
        type: "array",
        "x-field-type": "barcode",
        "x-display-name": field.name?.trim() || uniqueName,
        ...(field.description ? { description: field.description } : {}),
        items: {
          type: "object",
          properties: {
            kind: { type: "string" },
            value: { type: "string" },
            page: { type: "number" },
            polygon: { type: "array" },
            confidence: { type: "number" },
          },
        },
      };
      if (field.required) required.push(uniqueName);
      return;
    }

    // Signature: presence + crop payload (filled by feature pipeline, not LLM)
    if (field.type === "signature") {
      let fieldName = field.name?.trim() || `signature_field_${index + 1}`;
      let uniqueName = fieldName;
      let dupCounter = 1;
      while (usedNames.has(uniqueName)) {
        uniqueName = `${fieldName}_${dupCounter}`;
        dupCounter++;
      }
      usedNames.add(uniqueName);
      properties[uniqueName] = {
        type: "object",
        "x-field-type": "signature",
        "x-display-name": field.name?.trim() || uniqueName,
        "x-signature-mode": "both",
        ...(field.description ? { description: field.description } : {}),
        properties: {
          present: { type: "boolean" },
          signature_type: { type: "string" },
          page: { type: "number" },
          polygon: { type: "array" },
          confidence: { type: "number" },
          image_base64: { type: "string" },
        },
      };
      if (field.required) required.push(uniqueName);
      return;
    }

    let fieldName = field.name?.trim();
    if (!fieldName) {
      const baseName = `${field.type}_field`;
      let generatedName = `${baseName}_${index + 1}`;
      let counter = 1;
      while (usedNames.has(generatedName)) {
        generatedName = `${baseName}_${index + 1}_${counter}`;
        counter++;
      }
      fieldName = generatedName;
    }

    let uniqueName = fieldName;
    let dupCounter = 1;
    while (usedNames.has(uniqueName)) {
      uniqueName = `${fieldName}_${dupCounter}`;
      dupCounter++;
    }
    usedNames.add(uniqueName);

    let propDef: Record<string, unknown> = { type: field.type };

    if (field.description) {
      propDef.description = field.description;
    }

    if (field.type === "object" && field.children) {
      const nested = fieldsToJsonSchema(field.children, `${parentPath}${uniqueName}.`);
      propDef = { ...propDef, ...(nested as Record<string, unknown>) };
    }

    if (field.type === "array" && field.children && field.children.length > 0) {
      const itemSchema = fieldsToJsonSchema(field.children, `${parentPath}${uniqueName}.items.`);
      propDef.items = {
        type: "object",
        ...(itemSchema as Record<string, unknown>),
      };
    }

    properties[uniqueName] = propDef;

    if (field.required) {
      required.push(uniqueName);
    }
  });

  return {
    type: "object",
    properties,
    ...(required.length > 0 ? { required } : {}),
  };
}

// Check if JSON text contains a valid non-empty schema
function isValidNonEmptyJson(jsonText: string): boolean {
  try {
    const parsed = JSON.parse(jsonText);
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      return false;
    }
    const keys = Object.keys(parsed);
    if (keys.length === 0) return false;
    if (parsed.properties || parsed.type) return true;
    for (const key of keys) {
      const value = parsed[key];
      if (typeof value === "object" && value !== null) {
        if (value.type || value.properties || value.items) return true;
      }
    }
    return keys.length > 0;
  } catch {
    return false;
  }
}

// AI Generation Animation Messages
const GENERATION_MESSAGES = [
  { icon: FileSearch, text: "Scanning document structure..." },
  { icon: Brain, text: "Analyzing content patterns..." },
  { icon: Sparkles, text: "Identifying key fields..." },
  { icon: Wand2, text: "Generating optimal schema..." },
  { icon: Zap, text: "Finalizing extraction rules..." },
];

// Magical AI Generation Animation Component
function AIGenerationAnimation() {
  const [messageIndex, setMessageIndex] = useState(0);
  const [particles, setParticles] = useState<Array<{ id: number; x: number; y: number; delay: number }>>([]);

  // Rotate through messages
  useEffect(() => {
    const interval = setInterval(() => {
      setMessageIndex((prev) => (prev + 1) % GENERATION_MESSAGES.length);
    }, 2500);
    return () => clearInterval(interval);
  }, []);

  // Generate floating particles
  useEffect(() => {
    const newParticles = Array.from({ length: 12 }, (_, i) => ({
      id: i,
      x: Math.random() * 100,
      y: Math.random() * 100,
      delay: Math.random() * 2,
    }));
    setParticles(newParticles);
  }, []);

  const currentMessage = GENERATION_MESSAGES[messageIndex];
  const IconComponent = currentMessage.icon;

  return (
    <div className="flex flex-col items-center justify-center px-6 py-12 relative overflow-hidden">
      {/* Floating particles */}
      <div className="absolute inset-0 pointer-events-none">
        {particles.map((particle) => (
          <div
            key={particle.id}
            className="absolute w-1 h-1 rounded-full bg-primary/30"
            style={{
              left: `${particle.x}%`,
              top: `${particle.y}%`,
              animation: `float-particle 4s ease-in-out infinite`,
              animationDelay: `${particle.delay}s`,
            }}
          />
        ))}
      </div>

      {/* Main animated icon area */}
      <div className="relative mb-6">
        {/* Outer rotating ring */}
        <div
          className="absolute -inset-8 rounded-full border border-dashed border-primary/20"
          style={{ animation: "spin 12s linear infinite" }}
        />

        {/* Middle rotating ring - reverse */}
        <div
          className="absolute -inset-5 rounded-full border border-primary/30"
          style={{ animation: "spin 8s linear infinite reverse" }}
        />

        {/* Pulsing glow behind icon */}
        <div
          className="absolute -inset-3 rounded-full bg-primary/10 blur-xl"
          style={{ animation: "ai-pulse-glow 2.5s ease-in-out infinite" }}
        />

        {/* Main icon - Braces {} for schema with animated effects */}
        <div className="relative">
          <div
            className="relative"
            style={{ animation: "icon-bounce 2.5s ease-in-out infinite" }}
          >
            {/* Main icon - using Braces for schema generation */}
            <Braces className="w-14 h-14 text-primary" />

            {/* Orbiting dot 1 */}
            <div
              className="absolute w-2 h-2 rounded-full bg-primary/80"
              style={{
                animation: "orbit 3s linear infinite",
                top: "50%",
                left: "50%",
                transformOrigin: "-14px 0",
              }}
            />

            {/* Orbiting dot 2 */}
            <div
              className="absolute w-1.5 h-1.5 rounded-full bg-violet-500/80"
              style={{
                animation: "orbit 4s linear infinite reverse",
                top: "50%",
                left: "50%",
                transformOrigin: "-20px 0",
              }}
            />
          </div>
        </div>
      </div>

      {/* Text content */}
      <div className="relative z-10 text-center">
        <h4
          className="text-lg font-semibold mb-3 bg-gradient-to-r from-foreground via-primary to-foreground bg-clip-text text-transparent"
          style={{
            backgroundSize: "200% 100%",
            animation: "gradient-shift 3s ease-in-out infinite"
          }}
        >
          Generating Schema
        </h4>

        {/* Animated message carousel */}
        <div className="h-10 flex flex-col items-center justify-center overflow-hidden mb-4">
          <div
            className="flex items-center gap-2 transition-all duration-500 ease-out"
            key={messageIndex}
            style={{ animation: "slide-up-fade 0.5s ease-out" }}
          >
            <IconComponent className="w-4 h-4 text-primary/70" />
            <span className="text-sm text-muted-foreground">{currentMessage.text}</span>
          </div>
        </div>

        {/* Progress indicator dots */}
        <div className="flex items-center justify-center gap-1.5 mb-5">
          {GENERATION_MESSAGES.map((_, i) => (
            <div
              key={i}
              className={cn(
                "h-1.5 rounded-full transition-all duration-500",
                i === messageIndex
                  ? "bg-primary w-5"
                  : i < messageIndex
                  ? "bg-primary/60 w-1.5"
                  : "bg-muted-foreground/20 w-1.5"
              )}
            />
          ))}
        </div>

        {/* Shimmer loading bar */}
        <div className="w-44 h-1 bg-muted rounded-full overflow-hidden mx-auto">
          <div
            className="h-full w-1/2 bg-gradient-to-r from-transparent via-primary to-transparent rounded-full"
            style={{
              animation: "shimmer 1.5s ease-in-out infinite",
            }}
          />
        </div>
      </div>

    </div>
  );
}

// Sortable Field Item Component
function SortableFieldItem({
  field,
  onUpdate,
  onDelete,
  onAddChild,
  depth = 0,
  isDragging = false,
}: {
  field: SchemaField;
  onUpdate: (field: SchemaField) => void;
  onDelete: () => void;
  onAddChild?: () => void;
  depth?: number;
  isDragging?: boolean;
}) {
  const [isEditing, setIsEditing] = useState(!field.name && field.type !== "instruction");
  const canHaveChildren = field.type === "object" || field.type === "array" || field.type === "instruction";
  const hasChildren = field.children && field.children.length > 0;

  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging: isSortableDragging,
  } = useSortable({ id: field.id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };

  const isCurrentlyDragging = isDragging || isSortableDragging;

  // Calculate indentation based on depth
  const indentPx = depth * 24;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={cn(
        "group relative",
        isCurrentlyDragging && "z-50 opacity-0"
      )}
    >
      {/* Indentation and connection line for nested items */}
      <div
        className={cn(
          "border rounded-lg bg-card transition-all",
          "hover:shadow-sm",
          "shadow-sm",
          field.type === "instruction"
            ? "border-orange-300 bg-orange-50/50"
            : "border-border hover:border-border"
        )}
        style={{ marginLeft: `${indentPx}px` }}
      >
        {/* Vertical connection line for nested items */}
        {depth > 0 && (
          <div
            className="absolute top-0 bottom-0 w-0.5 bg-muted-foreground/20"
            style={{ left: `${indentPx - 12}px` }}
          />
        )}

        <div className="flex items-center gap-2 px-3 py-2">
          {/* Drag Handle */}
          <button
            {...attributes}
            {...listeners}
            className={cn(
              "p-1 rounded cursor-grab active:cursor-grabbing",
              "text-muted-foreground/40 hover:text-muted-foreground hover:bg-muted",
              "focus:outline-none",
              isCurrentlyDragging && "cursor-grabbing text-primary"
            )}
          >
            <GripVertical className="w-4 h-4" />
          </button>

          {/* Expand/Collapse for arrays and objects - always show if can have children */}
          {canHaveChildren && (
            <button
              onClick={() => onUpdate({ ...field, isExpanded: !field.isExpanded })}
              className={cn(
                "p-0.5 rounded hover:bg-muted transition-colors",
                hasChildren ? "text-muted-foreground hover:text-foreground" : "text-muted-foreground/40"
              )}
            >
              <ChevronDownIcon size={16} className={cn(
                "transition-transform duration-200",
                !field.isExpanded && "-rotate-90"
              )} />
            </button>
          )}

          {/* Type Icon Badge */}
          <div className={cn(
            "w-7 h-7 rounded flex items-center justify-center flex-shrink-0",
            fieldTypeColors[field.type]
          )}>
            {fieldTypeIcons[field.type]}
          </div>

          {/* Field Name / Edit */}
          {field.type === "instruction" ? (
            // Instruction field - fixed title, no editable name
            <div className="flex-1 flex items-center gap-2 min-w-0">
              <span className="font-medium text-sm text-orange-700">
                Custom Instructions
              </span>
              <span className="text-[10px] text-orange-600/70">
                {field.children?.length || 0} {(field.children?.length || 0) === 1 ? 'instruction' : 'instructions'}
              </span>
            </div>
          ) : isEditing ? (
            <div className="flex-1 flex items-center gap-2">
              <Input
                value={field.name}
                onChange={(e) => onUpdate({ ...field, name: e.target.value })}
                placeholder="Field name"
                className="h-7 text-sm flex-1 focus-visible:ring-1 focus-visible:ring-offset-0"
                autoFocus
                onKeyDown={(e) => {
                  if (e.key === "Enter" && field.name) {
                    setIsEditing(false);
                  }
                }}
              />

              {/*
               * FIX 1 — Type switcher: auto-expand and initialize children for array/object types.
               *
               * BUG: When a user changed a field's type to "array" or "object" via this dropdown,
               * the field was updated with only { type: newType }. This meant:
               *   - isExpanded was NOT set to true, so the children panel stayed hidden.
               *   - children was NOT initialized, so the empty-state "Add nested field" prompt
               *     never appeared until the user manually clicked the chevron.
               * Conversely, switching away from array/object left stale children behind, which
               * would silently appear if the user switched back.
               *
               * FIX: When switching TO array/object, force isExpanded=true and ensure children
               * is at least an empty array so the UI shows the add-child prompt immediately.
               * When switching AWAY from array/object, clear children and collapse.
               * FIX 1 END
               */}
              <Select
                value={field.type}
                onValueChange={(v) => {
                  const newType = v as SchemaField["type"];
                  const updates: Partial<SchemaField> = { type: newType };

                  if (newType === "instruction") {
                    // Instruction type: special setup with one empty instruction child
                    updates.isExpanded = true;
                    updates.name = "custom_instructions";
                    updates.children = [{
                      id: generateId(),
                      name: "",
                      type: "string",
                      required: false,
                    }];
                  } else if (newType === "barcode" || newType === "signature") {
                    updates.children = undefined;
                    updates.isExpanded = false;
                    if (!field.name?.trim()) {
                      updates.name = newType === "barcode" ? "barcodes" : "signature";
                    }
                  } else if (newType === "array" || newType === "object") {
                    // FIX 1: Container types (array/object) must auto-expand so the
                    // children panel is visible immediately after switching type.
                    // Only initialize children to [] if there are none yet — preserves
                    // existing children if the user switches between array and object.
                    updates.isExpanded = true;
                    if (!field.children || field.children.length === 0) {
                      updates.children = [];
                    }
                  } else {
                    // FIX 1: Switching to a scalar type — clear any stale children
                    // that were left over from a previous array/object type, and
                    // collapse the field so there is no leftover expanded state.
                    updates.children = undefined;
                    updates.isExpanded = false;
                  }

                  onUpdate({ ...field, ...updates });
                }}
              >
                <SelectTrigger className="h-7 w-28 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="string">String</SelectItem>
                  <SelectItem value="number">Number</SelectItem>
                  <SelectItem value="boolean">Boolean</SelectItem>
                  <SelectItem value="date">Date</SelectItem>
                  <SelectItem value="array">Array</SelectItem>
                  <SelectItem value="object">Object</SelectItem>
                  <SelectItem value="barcode">
                    <span className="inline-flex items-center gap-1 text-indigo-600 bg-indigo-50 border border-indigo-200 px-1.5 py-0.5 rounded-full text-xs">
                      <QrCode className="w-3 h-3" />
                      Barcode
                    </span>
                  </SelectItem>
                  <SelectItem value="signature">
                    <span className="inline-flex items-center gap-1 text-fuchsia-600 bg-fuchsia-50 border border-fuchsia-200 px-1.5 py-0.5 rounded-full text-xs">
                      <PenLine className="w-3 h-3" />
                      Signature
                    </span>
                  </SelectItem>
                  <SelectItem value="instruction">
                    <span className="inline-flex items-center gap-1 text-orange-600 bg-orange-50 border border-orange-200 px-1.5 py-0.5 rounded-full text-xs">
                      <MessageSquareText className="w-3 h-3" />
                      Instruction
                    </span>
                  </SelectItem>
                </SelectContent>
              </Select>
              <Button
                size="sm"
                variant="ghost"
                className="h-6 w-6 p-0"
                onClick={() => setIsEditing(false)}
              >
                <CheckIcon size={14} className="text-green-600" />
              </Button>
            </div>
          ) : (
            <div
              className="flex-1 flex items-center gap-2 cursor-pointer min-w-0"
              onClick={() => setIsEditing(true)}
            >
              <span className={cn(
                "font-medium text-sm truncate",
                field.name ? "text-foreground" : "text-muted-foreground italic"
              )}>
                {field.name || "Field name"}
              </span>
              <Badge variant="outline" className="text-[10px] font-normal px-1.5 py-0">
                {field.type}
              </Badge>
              {/* Show child count for arrays/objects */}
              {canHaveChildren && hasChildren && (field.type === "array" || field.type === "object") && (
                <span className="text-[10px] text-muted-foreground">
                  ({field.children!.length} {field.children!.length === 1 ? 'item' : 'items'})
                </span>
              )}
            </div>
          )}

          {/* Actions */}
          <div className="flex items-center gap-1 flex-shrink-0">
            {/* Required Toggle - not for instruction type */}
            {field.type !== "instruction" && (
              <div className="flex items-center gap-1 px-1.5">
                <Switch
                  checked={field.required}
                  onCheckedChange={(checked) => onUpdate({ ...field, required: checked })}
                  className="scale-[0.65]"
                />
                <span className="text-[10px] text-muted-foreground w-6">
                  {field.required ? "Req" : "Opt"}
                </span>
              </div>
            )}

            {/* Add Child - not for instruction type (has its own Add button) */}
            {canHaveChildren && field.type !== "instruction" && (
              <Button
                size="sm"
                variant="ghost"
                className="h-6 w-6 p-0 text-muted-foreground hover:text-foreground"
                onClick={onAddChild}
              >
                <PlusIcon size={14} />
              </Button>
            )}

            {/* Delete */}
            <Button
              size="sm"
              variant="ghost"
              className={cn(
                "h-6 w-6 p-0",
                field.type === "instruction"
                  ? "text-orange-400 hover:text-orange-600"
                  : "text-muted-foreground hover:text-destructive"
              )}
              onClick={onDelete}
            >
              <Trash2 className="w-3.5 h-3.5" />
            </Button>
          </div>
        </div>

        {/* Children - collapsible section */}
        {canHaveChildren && field.isExpanded && field.type !== "instruction" && (
          <div className={cn(
            "overflow-hidden transition-all duration-200",
            field.isExpanded ? "max-h-[2000px] opacity-100" : "max-h-0 opacity-0"
          )}>
            {hasChildren ? (
              <div className="pb-2 space-y-1.5 border-t border-border/50 mt-1 pt-2 px-1">
                {/*
                 * FIX 2 — Nested child "+" button adds to wrong parent.
                 *
                 * BUG: The onAddChild prop passed to each nested SortableFieldItem
                 * was closing over `field` (the current parent) and appending a new
                 * child to field.children. This means clicking "+" on a nested
                 * array/object (e.g. "ship" inside "Laytime") would add a sibling
                 * to "ship" inside Laytime's children, instead of adding a child
                 * INSIDE "ship" itself.
                 *
                 * Example of the broken behaviour:
                 *   Laytime (object)
                 *     └─ ship (array)   ← clicking + here added to Laytime.children
                 *
                 * FIX: onAddChild for a child item must append to that CHILD's own
                 * children array (making it a grandchild), not to the current
                 * field's children array. We do this by cloning the child with the
                 * new grandchild appended, then replacing it at its index in
                 * field.children before calling onUpdate.
                 * FIX 2 END
                 */}
                {field.children!.map((child, index) => (
                  <SortableFieldItem
                    key={child.id}
                    field={child}
                    onUpdate={(updated) => {
                      const newChildren = [...(field.children || [])];
                      newChildren[index] = updated;
                      onUpdate({ ...field, children: newChildren });
                    }}
                    onDelete={() => {
                      const newChildren = field.children?.filter((_, i) => i !== index);
                      onUpdate({ ...field, children: newChildren });
                    }}
                    onAddChild={() => {
                      // FIX 2: Add a new field as a child OF this child (grandchild),
                      // not as a sibling of this child inside the parent.
                      const newGrandchild: SchemaField = {
                        id: generateId(),
                        name: "",
                        type: "string",
                        required: false,
                        isExpanded: true,
                      };
                      const updatedChild: SchemaField = {
                        ...child,
                        isExpanded: true, // ensure the child expands to reveal the new grandchild
                        children: [...(child.children || []), newGrandchild],
                      };
                      const newChildren = [...(field.children || [])];
                      newChildren[index] = updatedChild;
                      onUpdate({ ...field, children: newChildren });
                    }}
                    depth={depth + 1}
                  />
                ))}
              </div>
            ) : (
              /* Empty state for arrays/objects with no children */
              <div className="pb-2 border-t border-border/50 mt-1 pt-2 px-3">
                <div
                  className="flex items-center justify-center py-3 px-4 border border-dashed border-muted-foreground/30 rounded-md bg-muted/20 cursor-pointer hover:bg-muted/40 hover:border-muted-foreground/50 transition-colors"
                  onClick={onAddChild}
                  style={{ marginLeft: `${(depth + 1) * 24}px` }}
                >
                  <PlusIcon size={14} className="mr-2 text-muted-foreground" />
                  <span className="text-xs text-muted-foreground">
                    Add {field.type === "array" ? "array item fields" : "nested field"}
                  </span>
                </div>
              </div>
            )}
          </div>
        )}

        {/* Instruction children - simple text inputs */}
        {field.type === "instruction" && field.isExpanded && (
          <div className="border-t border-orange-200/50 mt-1 pt-2 pb-2 px-3 bg-orange-50/30">
            <div className="space-y-2" style={{ marginLeft: `${(depth + 1) * 24}px` }}>
              {field.children?.map((child, index) => (
                <div key={child.id} className="flex items-center gap-2">
                  <Input
                    value={child.name}
                    onChange={(e) => {
                      const newChildren = [...(field.children || [])];
                      newChildren[index] = { ...child, name: e.target.value };
                      onUpdate({ ...field, children: newChildren });
                    }}
                    placeholder="Enter instruction for AI..."
                    className="h-8 text-sm flex-1 bg-white focus-visible:ring-1 focus-visible:ring-offset-0 focus-visible:ring-orange-400"
                  />
                  <button
                    onClick={() => {
                      const newChildren = field.children?.filter((_, i) => i !== index);
                      onUpdate({ ...field, children: newChildren });
                    }}
                    className="p-1.5 rounded-full hover:bg-orange-100 text-muted-foreground hover:text-orange-600 transition-colors"
                  >
                    <XIcon size={14} />
                  </button>
                </div>
              ))}
              <button
                onClick={() => {
                  const newChild: SchemaField = {
                    id: generateId(),
                    name: "",
                    type: "string",
                    required: false,
                  };
                  onUpdate({
                    ...field,
                    children: [...(field.children || []), newChild],
                  });
                }}
                className="flex items-center gap-1.5 text-xs text-orange-600 hover:text-orange-700 py-1.5 px-2 rounded hover:bg-orange-100 transition-colors"
              >
                <PlusIcon size={12} />
                Add Instruction
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// Drag Overlay Item (shown while dragging)
function DragOverlayItem({ field }: { field: SchemaField }) {
  return (
    <div className="border rounded-lg bg-card shadow-lg border-primary/50">
      <div className="flex items-center gap-2 px-3 py-2">
        <div className="p-1 text-primary">
          <GripVertical className="w-4 h-4" />
        </div>
        <div className={cn(
          "w-7 h-7 rounded flex items-center justify-center",
          fieldTypeColors[field.type]
        )}>
          {fieldTypeIcons[field.type]}
        </div>
        <span className="font-medium text-sm">
          {field.name || "Unnamed"}
        </span>
        <Badge variant="outline" className="text-[10px] font-normal px-1.5 py-0">
          {field.type}
        </Badge>
      </div>
    </div>
  );
}

export function SchemaBuilder({
  initialFields = [],
  initialName = "",
  initialDescription = "",
  initialDocType = "",
  onSave,
  onCancel,
  documentPreview,
  mode = "create",
  isLoading = false,
  isReadOnly = false,
  isSaving = false,
  onGenerateSchema,
  isGenerating = false,
  isReviewMode = false,
  onApprove,
  onReject,
  isReviewing = false,
}: SchemaBuilderProps) {
  const [fields, setFields] = useState<SchemaField[]>(initialFields);
  const [viewMode, setViewMode] = useState<"visual" | "json">("visual");
  const [saveDialogOpen, setSaveDialogOpen] = useState(false);
  const [schemaName, setSchemaName] = useState(initialName);
  const [schemaDescription, setSchemaDescription] = useState(initialDescription);
  const [docType, setDocType] = useState(initialDocType);
  const [docTypeDropdownOpen, setDocTypeDropdownOpen] = useState(false);
  const [customDocTypeInput, setCustomDocTypeInput] = useState("");
  const [activeId, setActiveId] = useState<string | null>(null);
  const [hasChanges, setHasChanges] = useState(false);

  // Update fields when initialFields change (for edit mode)
  useEffect(() => {
    if (initialFields.length > 0) {
      setFields(initialFields);
    }
  }, [initialFields]);

  // Update form values when initial values change (for edit mode)
  useEffect(() => {
    if (initialName) setSchemaName(initialName);
    if (initialDescription) setSchemaDescription(initialDescription);
    if (initialDocType) setDocType(initialDocType);
  }, [initialName, initialDescription, initialDocType]);

  // JSON editor state
  const [jsonText, setJsonText] = useState<string>("");
  const [jsonError, setJsonError] = useState<string | null>(null);
  const [jsonWarnings, setJsonWarnings] = useState<string[]>([]);
  const [lastSyncedFields, setLastSyncedFields] = useState<string>("");
  const [isEditingJson, setIsEditingJson] = useState(false);

  // DnD sensors
  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: {
        distance: 8,
      },
    }),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  // Get active field for drag overlay
  const activeField = useMemo(() => {
    if (!activeId) return null;
    return fields.find(f => f.id === activeId) || null;
  }, [activeId, fields]);

  // Field IDs for sortable context
  const fieldIds = useMemo(() => fields.map(f => f.id), [fields]);

  // Sync JSON text when fields change
  useEffect(() => {
    if (isEditingJson) return;
    const currentFieldsJson = JSON.stringify(fields);
    if (currentFieldsJson === lastSyncedFields) return;
    const schema = fieldsToJsonSchema(fields);
    const newJsonText = JSON.stringify(schema, null, 2);
    setJsonText(newJsonText);
    setJsonError(null);
    setJsonWarnings([]);
    setLastSyncedFields(currentFieldsJson);
  }, [fields, isEditingJson, lastSyncedFields]);

  // Initialize on mount
  useEffect(() => {
    const schema = fieldsToJsonSchema(fields);
    setJsonText(JSON.stringify(schema, null, 2));
    setJsonWarnings([]);
    setLastSyncedFields(JSON.stringify(fields));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Reset editing flag when switching to visual mode
  useEffect(() => {
    if (viewMode === "visual") {
      setIsEditingJson(false);
    }
  }, [viewMode]);

  // Drag handlers
  const handleDragStart = (event: DragStartEvent) => {
    setActiveId(event.active.id as string);
  };

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    setActiveId(null);

    if (over && active.id !== over.id) {
      setFields((items) => {
        const oldIndex = items.findIndex(i => i.id === active.id);
        const newIndex = items.findIndex(i => i.id === over.id);
        return arrayMove(items, oldIndex, newIndex);
      });
    }
  };

  const addField = useCallback(() => {
    const newField: SchemaField = {
      id: generateId(),
      name: "",
      type: "string",
      required: false,
      isExpanded: true,
    };
    setFields([...fields, newField]);
  }, [fields]);

  const updateField = useCallback((index: number, updated: SchemaField) => {
    setFields((prev) => {
      const newFields = [...prev];
      newFields[index] = updated;
      return newFields;
    });
  }, []);

  const deleteField = useCallback((index: number) => {
    setFields((prev) => prev.filter((_, i) => i !== index));
  }, []);

  const addChildToField = useCallback((index: number) => {
    setFields((prev) => {
      const newFields = [...prev];
      const field = newFields[index];
      const newChild: SchemaField = {
        id: generateId(),
        name: "",
        type: "string",
        required: false,
      };
      newFields[index] = {
        ...field,
        children: [...(field.children || []), newChild],
        isExpanded: true,
      };
      return newFields;
    });
  }, []);

  const handleSaveClick = () => {
    setSaveDialogOpen(true);
  };

  const handleConfirmSave = () => {
    if (!schemaName.trim() || !docType.trim()) return;
    if (viewMode === "json" && jsonWarnings.length > 0) {
      toast({
        title: "Schema type warnings",
        description: `${jsonWarnings.length} invalid field type(s) were defaulted to string.`,
      });
    }
    // Instructions are now embedded in json_schema via fieldsToJsonSchema, not passed separately
    onSave(fields, schemaName.trim(), docType.trim(), schemaDescription.trim() || undefined);
    setSaveDialogOpen(false);
    // Only clear values in create mode (edit mode will navigate away)
    if (mode === "create") {
      setSchemaName("");
      setSchemaDescription("");
      setDocType("");
    }
  };

  const handleDialogClose = () => {
    setSaveDialogOpen(false);
    // In edit mode, restore initial values; in create mode, clear them
    if (mode === "edit") {
      setSchemaName(initialName);
      setSchemaDescription(initialDescription);
      setDocType(initialDocType);
      setCustomDocTypeInput("");
    } else {
      setSchemaName("");
      setSchemaDescription("");
      setDocType("");
      setCustomDocTypeInput("");
    }
  };

  const applyCustomDocType = () => {
    const trimmed = customDocTypeInput.trim();
    if (!trimmed) return;
    setDocType(trimmed);
    setDocTypeDropdownOpen(false);
  };

  const fieldCount = (() => {
    if (viewMode === "json" && jsonText && !jsonError) {
      try {
        const parsed = JSON.parse(jsonText);
        const jsonCount = countJsonSchemaProperties(parsed);
        if (jsonCount > 0) return jsonCount;
      } catch { /* fall through */ }
    }
    // Exclude instruction fields from count (they're not data extraction fields)
    return fields.filter(f => f.type !== "instruction").length;
  })();

  return (
    <TooltipProvider>
      <div className="h-full flex bg-background relative">
        {/* Left Side - Document Preview */}
        {documentPreview && (
          <div className="w-1/2 h-full border-r border-border flex flex-col bg-card">
            <div className="flex-1 overflow-hidden h-full">
              {documentPreview}
            </div>
          </div>
        )}

        {/* Right Side - Schema Builder */}
        <div className={cn(
          "flex flex-col h-full bg-background",
          documentPreview ? "w-1/2" : "w-full"
        )}>
          {/* Header */}
          <div className="px-4 py-3 border-b border-border bg-card flex items-center justify-between">
            <div className="flex items-center gap-3">
              <div className="w-8 h-8 rounded-md bg-muted flex items-center justify-center">
                <Braces className="w-4 h-4 text-muted-foreground" />
              </div>
              <div>
                <h3 className="text-sm font-semibold">Schema Builder</h3>
                <p className="text-xs text-muted-foreground">
                  {fieldCount} {fieldCount === 1 ? 'field' : 'fields'} defined
                </p>
              </div>
            </div>

            <div className="flex items-center gap-2">
              {/* Generate Schema from Document Button */}
              {onGenerateSchema && (
                <Tooltip>
                  <TooltipTrigger asChild>
                    <Button
                      variant={isGenerating ? "default" : "outline"}
                      size="icon"
                      className={cn(
                        "h-8 w-8 relative overflow-hidden transition-all duration-300",
                        isGenerating && "bg-primary text-primary-foreground",
                        !isGenerating && fields.length === 0 && "ring-2 ring-primary/50 ring-offset-2 ring-offset-background"
                      )}
                      onClick={onGenerateSchema}
                      disabled={isGenerating}
                    >
                      {isGenerating ? (
                        <>
                          <div className="absolute inset-0 bg-gradient-to-r from-transparent via-white/20 to-transparent animate-shimmer" />
                          <Loader2 className="w-4 h-4 animate-spin relative z-10" />
                        </>
                      ) : (
                        <Wand2 className="w-4 h-4" />
                      )}
                    </Button>
                  </TooltipTrigger>
                  <TooltipContent>
                    <p className="text-xs">{isGenerating ? "Generating schema..." : "Auto-generate schema with AI"}</p>
                  </TooltipContent>
                </Tooltip>
              )}
              {/* JSON Upload Button */}
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    size="icon"
                    className="h-8 w-8"
                    onClick={() => document.getElementById('json-upload-input')?.click()}
                  >
                    <UploadIcon size={16} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent>
                  <p className="text-xs">Import JSON Schema</p>
                </TooltipContent>
              </Tooltip>
              <input
                id="json-upload-input"
                type="file"
                accept=".json,application/json"
                className="hidden"
                onChange={(e) => {
                  const file = e.target.files?.[0];
                  if (file) {
                    const reader = new FileReader();
                    reader.onload = (event) => {
                      try {
                        const json = JSON.parse(event.target?.result as string);
                        const warnings: string[] = [];
                        const newFields = jsonSchemaToFields(json, [], warnings);
                        if (newFields.length > 0) {
                          setFields(newFields);
                          setJsonText(JSON.stringify(json, null, 2));
                          setJsonError(null);
                          setJsonWarnings(warnings);
                        }
                      } catch (err) {
                        setJsonWarnings([]);
                        setJsonError(err instanceof Error ? err.message : "Invalid JSON file");
                      }
                    };
                    reader.readAsText(file);
                  }
                  // Reset input so same file can be uploaded again
                  e.target.value = '';
                }}
              />

              <Tabs value={viewMode} onValueChange={(v) => setViewMode(v as "visual" | "json")}>
                <TabsList className="h-8">
                  <TabsTrigger value="visual" className="text-xs h-7 px-3">
                    <EyeIcon size={14} className="mr-1.5" />
                    Visual
                  </TabsTrigger>
                  <TabsTrigger value="json" className="text-xs h-7 px-3">
                    <Code className="w-3.5 h-3.5 mr-1.5" />
                    JSON
                  </TabsTrigger>
                </TabsList>
              </Tabs>

              {/* Close button - shown in review mode */}
              {isReviewMode && (
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-9 w-9 ml-2 bg-red-100 hover:bg-red-200 dark:bg-red-900/30 dark:hover:bg-red-900/50"
                  onClick={onCancel}
                  title="Close"
                >
                  <XIcon size={16} className="text-red-600" />
                </Button>
              )}
            </div>
          </div>

          {/* Content */}
          <div className="flex-1 overflow-hidden">
            {/* Show AI Generation Animation when generating */}
            {isGenerating ? (
              <div className="h-full flex items-center justify-center">
                <AIGenerationAnimation />
              </div>
            ) : viewMode === "visual" ? (
              <ScrollArea className="h-full">
                <div className="p-4 pb-24">
                  {fields.length === 0 ? (
                    <div className="flex flex-col items-center justify-center py-16 px-4">
                      <div className="w-14 h-14 rounded-lg bg-muted flex items-center justify-center mb-4">
                        <Braces className="w-7 h-7 text-muted-foreground" />
                      </div>
                      <h4 className="text-base font-medium mb-1">No fields yet</h4>
                      <p className="text-sm text-muted-foreground mb-6 text-center max-w-xs">
                        Start building your schema by adding fields. Drag to reorder.
                      </p>
                      <div className="flex flex-col sm:flex-row gap-3">
                        <Button onClick={addField} variant="outline">
                          <PlusIcon size={16} className="mr-2" />
                          Add Field Manually
                        </Button>
                        {onGenerateSchema && (
                          <Button onClick={onGenerateSchema}>
                            <Wand2 className="w-4 h-4 mr-2" />
                            Auto-Generate Schema
                          </Button>
                        )}
                      </div>
                    </div>
                  ) : (
                    <DndContext
                      sensors={sensors}
                      collisionDetection={closestCenter}
                      onDragStart={handleDragStart}
                      onDragEnd={handleDragEnd}
                    >
                      <SortableContext items={fieldIds} strategy={verticalListSortingStrategy}>
                        <div className="space-y-2">
                          {fields.map((field, index) => (
                            <SortableFieldItem
                              key={field.id}
                              field={field}
                              onUpdate={(updated) => updateField(index, updated)}
                              onDelete={() => deleteField(index)}
                              onAddChild={() => addChildToField(index)}
                            />
                          ))}
                        </div>
                      </SortableContext>

                      <DragOverlay
                        dropAnimation={{
                          sideEffects: defaultDropAnimationSideEffects({
                            styles: {
                              active: {
                                opacity: "0.5",
                              },
                            },
                          }),
                        }}
                      >
                        {activeField ? <DragOverlayItem field={activeField} /> : null}
                      </DragOverlay>
                    </DndContext>
                  )}

                  {fields.length > 0 && (
                    <Button
                      variant="outline"
                      className="w-full h-10 mt-3 border-dashed"
                      onClick={addField}
                    >
                      <PlusIcon size={16} className="mr-2" />
                      Add Field
                    </Button>
                  )}
                </div>
              </ScrollArea>
            ) : (
              <div className="h-full flex flex-col relative bg-card">
                {/* JSON validation indicator */}
                <div className="absolute top-3 right-3 z-10">
                  {jsonError ? (
                    <Badge variant="destructive" className="text-xs">
                      <AlertCircle className="w-3 h-3 mr-1" />
                      Invalid
                    </Badge>
                  ) : jsonWarnings.length > 0 ? (
                    <Badge variant="outline" className="text-xs border-amber-500 text-amber-700 bg-amber-50">
                      <AlertCircle className="w-3 h-3 mr-1" />
                      Valid with warnings
                    </Badge>
                  ) : (
                    <Badge variant="secondary" className="text-xs bg-green-100 text-green-700">
                      <CircleCheckIcon size={12} className="mr-1" />
                      Valid
                    </Badge>
                  )}
                </div>

                <MonacoEditor
                  height="100%"
                  defaultLanguage="json"
                  value={jsonText}
                  onChange={(value) => {
                    const newText = value || "";
                    setJsonText(newText);
                    setIsEditingJson(true);
                    try {
                      const parsed = JSON.parse(newText);
                      setJsonError(null);
                      const warnings: string[] = [];
                      const newFields = jsonSchemaToFields(parsed, [], warnings);
                      setFields(newFields);
                      setJsonWarnings(warnings);
                      setLastSyncedFields(JSON.stringify(newFields));
                    } catch (err) {
                      setJsonWarnings([]);
                      setJsonError(err instanceof Error ? err.message : "Invalid JSON");
                    }
                  }}
                  theme="vs"
                  options={{
                    minimap: { enabled: false },
                    fontSize: 12,
                    lineHeight: 20,
                    padding: { top: 40, bottom: 80 },
                    scrollBeyondLastLine: false,
                    wordWrap: "on",
                    automaticLayout: true,
                    tabSize: 2,
                    formatOnPaste: true,
                    formatOnType: true,
                    scrollbar: {
                      verticalScrollbarSize: 6,
                      horizontalScrollbarSize: 6,
                    },
                    overviewRulerBorder: false,
                    hideCursorInOverviewRuler: true,
                    renderLineHighlight: "gutter",
                    folding: true,
                    lineNumbers: "on",
                    glyphMargin: false,
                    lineDecorationsWidth: 8,
                    lineNumbersMinChars: 3,
                  }}
                />
                {!jsonError && jsonWarnings.length > 0 ? (
                  <div className="absolute bottom-3 left-3 right-3 z-10 rounded-md border border-amber-500/40 bg-amber-50 px-3 py-2 text-xs text-amber-800">
                    {jsonWarnings[0]}
                    {jsonWarnings.length > 1 ? ` (+${jsonWarnings.length - 1} more)` : ""}
                  </div>
                ) : null}
              </div>
            )}
          </div>
        </div>

        {/* Floating Action Buttons */}
        {!isLoading && (
          isReviewMode ? (
            /* Review mode: Show Approve/Reject buttons - horizontal like workflow */
            <div className="fixed bottom-6 right-6 flex items-center gap-2 z-50">
              <Button
                variant="outline"
                onClick={onReject}
                disabled={isReviewing}
                className="border-red-300 text-red-600 hover:bg-red-50 hover:text-red-700 shadow-lg"
              >
                <XCircle className="w-4 h-4 mr-2" />
                Reject
              </Button>
              <Button
                onClick={onApprove}
                disabled={isReviewing}
                className="bg-green-600 hover:bg-green-700 shadow-lg"
              >
                {isReviewing ? (
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                ) : (
                  <CheckCircle2 className="w-4 h-4 mr-2" />
                )}
                Approve
              </Button>
            </div>
          ) : (
            /* Normal mode: Show Save/Cancel buttons - vertical */
            <div className="fixed bottom-6 right-6 flex flex-col gap-2 z-[100]">
              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    onClick={handleSaveClick}
                    disabled={(fields.length === 0 && !isValidNonEmptyJson(jsonText)) || isReadOnly || isSaving}
                    size="icon"
                    className="w-12 h-12 rounded-xl shadow-lg"
                  >
                    {isSaving ? (
                      <Loader2 className="w-5 h-5 animate-spin" />
                    ) : (
                      <Save className="w-5 h-5" />
                    )}
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="left">
                  <p className="text-xs">{mode === "edit" ? "Update Schema" : "Save Schema"}</p>
                </TooltipContent>
              </Tooltip>

              <Tooltip>
                <TooltipTrigger asChild>
                  <Button
                    variant="outline"
                    onClick={onCancel}
                    size="icon"
                    className="w-12 h-12 rounded-xl shadow-lg bg-background"
                    disabled={isSaving}
                  >
                    <XIcon size={20} />
                  </Button>
                </TooltipTrigger>
                <TooltipContent side="left">
                  <p className="text-xs">Cancel</p>
                </TooltipContent>
              </Tooltip>
            </div>
          )
        )}
      </div>

      {/* Save Schema Dialog */}
      <Dialog open={saveDialogOpen} onOpenChange={handleDialogClose}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{mode === "edit" ? "Update Schema" : "Save Schema"}</DialogTitle>
            <DialogDescription>
              {mode === "edit"
                ? "Update the schema name and description."
                : "Give your schema a name to save it for future use."}
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-4">
            <div className="space-y-2">
              <Label htmlFor="schema-name" className="text-sm font-medium">
                Schema Name <span className="text-destructive">*</span>
              </Label>
              <Input
                id="schema-name"
                value={schemaName}
                onChange={(e) => setSchemaName(e.target.value)}
                placeholder="e.g., Invoice Schema, Bill of Entry"
                className="focus-visible:ring-1 focus-visible:ring-offset-0"
                autoFocus
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="doc-type" className="text-sm font-medium">
                Document Type <span className="text-destructive">*</span>
              </Label>
              {mode === "edit" ? (
                <Input
                  id="doc-type"
                  value={docType}
                  disabled
                  className="bg-muted cursor-not-allowed"
                />
              ) : (
                <DropdownMenu open={docTypeDropdownOpen} onOpenChange={setDocTypeDropdownOpen}>
                  <DropdownMenuTrigger asChild>
                    <Button
                      variant="outline"
                      className="w-full justify-between font-normal h-10"
                    >
                      <span className={cn(!docType && "text-muted-foreground")}>
                        {docType || "Select document type..."}
                      </span>
                      <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
                    </Button>
                  </DropdownMenuTrigger>
                  <DropdownMenuContent className="w-[--radix-dropdown-menu-trigger-width]" align="start">
                    {DOCUMENT_TYPE_SUGGESTIONS.map((type) => (
                      <DropdownMenuItem
                        key={type}
                        onClick={() => {
                          setDocType(type);
                          setCustomDocTypeInput("");
                        }}
                        className="cursor-pointer"
                      >
                        <CheckIcon size={16} className={cn("mr-2", docType === type ? "opacity-100" : "opacity-0")} />
                        {type}
                      </DropdownMenuItem>
                    ))}
                    <div className="px-2 py-2 border-t">
                      <div className="relative">
                        <Input
                          placeholder="Or type custom..."
                          value={customDocTypeInput}
                          onChange={(e) => setCustomDocTypeInput(e.target.value)}
                          className="h-8 text-sm pr-9 focus-visible:ring-1 focus-visible:ring-offset-0"
                          onClick={(e) => e.stopPropagation()}
                          onKeyDown={(e) => {
                            if (e.key === "Enter") {
                              e.preventDefault();
                              e.stopPropagation();
                              applyCustomDocType();
                            }
                          }}
                        />
                        <Button
                          type="button"
                          variant="ghost"
                          size="icon"
                          className="absolute right-1 top-1/2 h-6 w-6 -translate-y-1/2"
                          onClick={(e) => {
                            e.preventDefault();
                            e.stopPropagation();
                            applyCustomDocType();
                          }}
                          disabled={!customDocTypeInput.trim()}
                        >
                          <PlusIcon size={12} />
                        </Button>
                      </div>
                    </div>
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
              <p className="text-xs text-muted-foreground">
                {mode === "edit"
                  ? "Document type cannot be changed after creation"
                  : "Select from list or type a custom document type"}
              </p>
            </div>
            <div className="space-y-2">
              <Label htmlFor="schema-description" className="text-sm font-medium">
                Description <span className="text-muted-foreground font-normal">(optional)</span>
              </Label>
              <Textarea
                id="schema-description"
                value={schemaDescription}
                onChange={(e) => setSchemaDescription(e.target.value)}
                placeholder="Describe what this schema is used for..."
                className="resize-none focus-visible:ring-1 focus-visible:ring-offset-0"
                rows={3}
              />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={handleDialogClose} disabled={isSaving}>
              Cancel
            </Button>
            <Button onClick={handleConfirmSave} disabled={!schemaName.trim() || !docType.trim() || isSaving}>
              {isSaving ? (
                <>
                  <Loader2 className="w-4 h-4 mr-2 animate-spin" />
                  {mode === "edit" ? "Updating..." : "Saving..."}
                </>
              ) : (
                mode === "edit" ? "Update Schema" : "Save Schema"
              )}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </TooltipProvider>
  );
}

export default SchemaBuilder;
