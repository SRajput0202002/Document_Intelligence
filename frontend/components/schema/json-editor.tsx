"use client";

import { useCallback, useRef, useState, useEffect } from "react";
import Editor, { OnMount, OnChange } from "@monaco-editor/react";
import { useTheme } from "next-themes";
import { AlertCircle } from "lucide-react";
import { CircleCheckIcon } from "@/components/ui/circle-check";
import { CopyIcon } from "@/components/ui/copy";
import { DownloadIcon } from "@/components/ui/download";
import { UploadIcon } from "@/components/ui/upload";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";

interface JsonSchemaEditorProps {
  schema: Record<string, unknown>;
  onChange: (schema: Record<string, unknown>) => void;
  readOnly?: boolean;
}

export function JsonSchemaEditor({
  schema,
  onChange,
  readOnly = false,
}: JsonSchemaEditorProps) {
  const { theme } = useTheme();
  const editorRef = useRef<unknown>(null);
  const [isValid, setIsValid] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // Track editor content independently so users can type invalid JSON
  const [editorContent, setEditorContent] = useState(() => JSON.stringify(schema, null, 2));
  const lastExternalSchemaRef = useRef<string>(JSON.stringify(schema));

  // Sync editor content when schema prop changes from external source
  useEffect(() => {
    const newSchemaStr = JSON.stringify(schema, null, 2);
    const currentSchemaStr = JSON.stringify(schema);

    // Only update if the schema changed externally (not from our own onChange)
    if (currentSchemaStr !== lastExternalSchemaRef.current) {
      setEditorContent(newSchemaStr);
      setIsValid(true);
      setError(null);
      lastExternalSchemaRef.current = currentSchemaStr;
    }
  }, [schema]);

  const handleEditorMount: OnMount = (editor) => {
    editorRef.current = editor;
  };

  const handleChange: OnChange = useCallback(
    (value) => {
      if (!value) return;

      // Always update local content so user can type freely
      setEditorContent(value);

      try {
        const parsed = JSON.parse(value);
        setIsValid(true);
        setError(null);
        // Update the external schema and track it
        lastExternalSchemaRef.current = JSON.stringify(parsed);
        onChange(parsed);
      } catch (e) {
        setIsValid(false);
        setError(e instanceof Error ? e.message : "Invalid JSON");
      }
    },
    [onChange]
  );

  const handleCopy = async () => {
    const content = JSON.stringify(schema, null, 2);
    await navigator.clipboard.writeText(content);
  };

  const handleDownload = () => {
    const content = JSON.stringify(schema, null, 2);
    const blob = new Blob([content], { type: "application/json" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "schema.json";
    a.click();
    URL.revokeObjectURL(url);
  };

  const handleUpload = () => {
    const input = document.createElement("input");
    input.type = "file";
    input.accept = ".json";
    input.onchange = async (e) => {
      const file = (e.target as HTMLInputElement).files?.[0];
      if (!file) return;

      try {
        const text = await file.text();
        const parsed = JSON.parse(text);
        onChange(parsed);
        setIsValid(true);
        setError(null);
      } catch (err) {
        setError("Failed to parse uploaded file");
        setIsValid(false);
      }
    };
    input.click();
  };

  return (
    <div className="h-full flex flex-col">
      {/* Toolbar */}
      <div className="flex items-center justify-between px-4 py-2 border-b bg-muted/30">
        <div className="flex items-center gap-2">
          {isValid ? (
            <Badge variant="outline" className="text-green-600 border-green-600">
              <CircleCheckIcon size={12} className="mr-1" />
              Valid JSON
            </Badge>
          ) : (
            <Badge variant="outline" className="text-red-600 border-red-600">
              <AlertCircle className="h-3 w-3 mr-1" />
              Invalid JSON
            </Badge>
          )}
          {error && (
            <span className="text-xs text-red-500 max-w-[300px] truncate">
              {error}
            </span>
          )}
        </div>
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="sm"
            onClick={handleCopy}
            title="Copy to clipboard"
          >
            <CopyIcon size={16} />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={handleDownload}
            title="Download JSON"
          >
            <DownloadIcon size={16} />
          </Button>
          {!readOnly && (
            <Button
              variant="ghost"
              size="sm"
              onClick={handleUpload}
              title="Upload JSON"
            >
              <UploadIcon size={16} />
            </Button>
          )}
        </div>
      </div>

      {/* Editor */}
      <div className="flex-1 min-h-0">
        <Editor
          height="100%"
          defaultLanguage="json"
          value={editorContent}
          theme={theme === "dark" ? "vs-dark" : "light"}
          onChange={handleChange}
          onMount={handleEditorMount}
          options={{
            readOnly,
            minimap: { enabled: false },
            fontSize: 13,
            lineNumbers: "on",
            scrollBeyondLastLine: false,
            automaticLayout: true,
            tabSize: 2,
            formatOnPaste: true,
            formatOnType: true,
            folding: true,
            foldingHighlight: true,
            bracketPairColorization: { enabled: true },
            wordWrap: "on",
            scrollbar: {
              vertical: "auto",
              horizontal: "auto",
            },
          }}
        />
      </div>
    </div>
  );
}
