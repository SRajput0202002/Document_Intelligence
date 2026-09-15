"use client";

import { useState, useCallback } from "react";
import { useDropzone } from "react-dropzone";
import { Document, Page, pdfjs } from "react-pdf";
import {
  ChevronLeft,
  ChevronRight,
  ZoomIn,
  ZoomOut,
  Loader2,
} from "lucide-react";
import { UploadIcon } from "@/components/ui/upload";
import { FileTextIcon } from "@/components/ui/file-text";
import { XIcon } from "@/components/ui/x";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { ScrollArea } from "@/components/ui/scroll-area";
import { cn, formatBytes } from "@/lib/utils";

// Configure PDF.js worker
pdfjs.GlobalWorkerOptions.workerSrc = `//unpkg.com/pdfjs-dist@${pdfjs.version}/build/pdf.worker.min.mjs`;

interface DocumentViewerProps {
  file: File | null;
  onFileSelect: (file: File) => void;
  onClear: () => void;
  disabled?: boolean;
}

export function DocumentViewer({
  file,
  onFileSelect,
  onClear,
  disabled = false,
}: DocumentViewerProps) {
  const [numPages, setNumPages] = useState<number>(0);
  const [currentPage, setCurrentPage] = useState<number>(1);
  const [scale, setScale] = useState<number>(1.0);
  const [loading, setLoading] = useState<boolean>(false);

  const onDrop = useCallback(
    (acceptedFiles: File[]) => {
      if (acceptedFiles.length > 0 && !disabled) {
        onFileSelect(acceptedFiles[0]);
        setCurrentPage(1);
        setScale(1.0);
      }
    },
    [onFileSelect, disabled]
  );

  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    onDrop,
    accept: { "application/pdf": [".pdf"] },
    multiple: false,
    disabled,
  });

  const onDocumentLoadSuccess = ({ numPages }: { numPages: number }) => {
    setNumPages(numPages);
    setLoading(false);
  };

  const onDocumentLoadStart = () => {
    setLoading(true);
  };

  const goToPrevPage = () => setCurrentPage((p) => Math.max(1, p - 1));
  const goToNextPage = () => setCurrentPage((p) => Math.min(numPages, p + 1));
  const zoomIn = () => setScale((s) => Math.min(2.0, s + 0.2));
  const zoomOut = () => setScale((s) => Math.max(0.5, s - 0.2));

  const handleClear = () => {
    setNumPages(0);
    setCurrentPage(1);
    setScale(1.0);
    onClear();
  };

  return (
    <Card className="flex flex-col h-full">
      <CardHeader className="flex-none py-3 px-4">
        <div className="flex items-center justify-between">
          <CardTitle className="text-lg flex items-center gap-2">
            <FileTextIcon size={20} />
            Document
          </CardTitle>
          {file && (
            <Button
              variant="ghost"
              size="icon"
              onClick={handleClear}
              disabled={disabled}
            >
              <XIcon size={16} />
            </Button>
          )}
        </div>
      </CardHeader>
      <CardContent className="flex-1 p-4 pt-0 min-h-0">
        {!file ? (
          <div
            {...getRootProps()}
            className={cn(
              "flex flex-col items-center justify-center h-full border-2 border-dashed rounded-lg cursor-pointer transition-colors",
              isDragActive
                ? "border-primary bg-primary/5"
                : "border-muted-foreground/25 hover:border-primary/50",
              disabled && "opacity-50 cursor-not-allowed"
            )}
          >
            <input {...getInputProps()} />
            <UploadIcon size={48} className="text-muted-foreground mb-4" />
            <p className="text-lg font-medium text-center">
              {isDragActive ? "Drop PDF here" : "Drag & drop PDF"}
            </p>
            <p className="text-sm text-muted-foreground mt-1">
              or click to browse
            </p>
          </div>
        ) : (
          <div className="flex flex-col h-full">
            {/* File info */}
            <div className="flex-none flex items-center justify-between text-sm text-muted-foreground mb-2">
              <span className="truncate max-w-[200px]" title={file.name}>
                {file.name}
              </span>
              <span>{formatBytes(file.size)}</span>
            </div>

            {/* PDF viewer */}
            <ScrollArea className="flex-1 border rounded-md">
              <div className="flex justify-center p-4">
                <Document
                  file={file}
                  onLoadSuccess={onDocumentLoadSuccess}
                  onLoadStart={onDocumentLoadStart}
                  loading={
                    <div className="flex items-center justify-center h-[400px]">
                      <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                    </div>
                  }
                  error={
                    <div className="flex items-center justify-center h-[400px] text-destructive">
                      Failed to load PDF
                    </div>
                  }
                >
                  <div className="pdf-page-container">
                    <Page
                      pageNumber={currentPage}
                      scale={scale}
                      loading={
                        <div className="flex items-center justify-center h-[400px]">
                          <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                        </div>
                      }
                      renderTextLayer={false}
                      renderAnnotationLayer={false}
                    />
                  </div>
                </Document>
              </div>
            </ScrollArea>

            {/* Controls */}
            <div className="flex-none flex items-center justify-between mt-2 gap-2">
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon"
                  onClick={zoomOut}
                  disabled={scale <= 0.5}
                >
                  <ZoomOut className="h-4 w-4" />
                </Button>
                <span className="text-sm w-14 text-center">
                  {Math.round(scale * 100)}%
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={zoomIn}
                  disabled={scale >= 2.0}
                >
                  <ZoomIn className="h-4 w-4" />
                </Button>
              </div>

              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="icon"
                  onClick={goToPrevPage}
                  disabled={currentPage <= 1}
                >
                  <ChevronLeft className="h-4 w-4" />
                </Button>
                <span className="text-sm w-20 text-center">
                  {loading ? "-" : `${currentPage} / ${numPages}`}
                </span>
                <Button
                  variant="outline"
                  size="icon"
                  onClick={goToNextPage}
                  disabled={currentPage >= numPages}
                >
                  <ChevronRight className="h-4 w-4" />
                </Button>
              </div>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
