"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, FileSpreadsheet } from "lucide-react";
import * as XLSX from "xlsx";
import { cn } from "@/lib/utils";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

export interface ExcelViewerProps {
  /** Excel file as File, Blob, or URL string */
  file: File | Blob | string | null;
  className?: string;
}

type WorkbookData = {
  sheetNames: string[];
  sheets: Record<string, (string | number)[][]>;
};

function getWorkbookFromBlob(blob: Blob): Promise<WorkbookData> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = (e) => {
      try {
        const data = e.target?.result;
        if (!data || !(data instanceof ArrayBuffer)) {
          reject(new Error("Failed to read file"));
          return;
        }
        const workbook = XLSX.read(data, { type: "array" });
        const sheetNames = workbook.SheetNames;
        const sheets: Record<string, (string | number)[][]> = {};
        for (const name of sheetNames) {
          const sheet = workbook.Sheets[name];
          const rows = XLSX.utils.sheet_to_json<string | number[]>(sheet, {
            header: 1,
            defval: "",
          }) as (string | number)[][];
          sheets[name] = rows;
        }
        resolve({ sheetNames, sheets });
      } catch (err) {
        reject(err);
      }
    };
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsArrayBuffer(blob);
  });
}

export function ExcelViewer({ file, className }: ExcelViewerProps) {
  const [workbook, setWorkbook] = useState<WorkbookData | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [activeSheet, setActiveSheet] = useState<string | null>(null);

  const loadFile = useCallback(async (source: File | Blob | string) => {
    setLoading(true);
    setError(null);
    try {
      let blob: Blob;
      if (typeof source === "string") {
        const res = await fetch(source);
        if (!res.ok) throw new Error("Failed to fetch file");
        blob = await res.blob();
      } else {
        blob = source;
      }
      const data = await getWorkbookFromBlob(blob);
      setWorkbook(data);
      setActiveSheet(
        data.sheetNames.length > 0 ? data.sheetNames[0] : null
      );
    } catch (err) {
      setError(
        err instanceof Error ? err.message : "Failed to load workbook"
      );
      setWorkbook(null);
      setActiveSheet(null);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!file) {
      setWorkbook(null);
      setActiveSheet(null);
      setLoading(false);
      setError(null);
      return;
    }
    loadFile(file);
  }, [file, loadFile]);

  if (!file) {
    return (
      <div
        className={cn(
          "flex h-full min-h-[200px] items-center justify-center text-muted-foreground",
          className
        )}
      >
        <div className="text-center">
          <FileSpreadsheet className="mx-auto h-12 w-12 opacity-50" />
          <p className="mt-2 text-sm">No file selected</p>
        </div>
      </div>
    );
  }

  if (loading) {
    return (
      <div
        className={cn(
          "flex h-full min-h-[200px] items-center justify-center text-muted-foreground",
          className
        )}
      >
        <div className="text-center">
          <Loader2 className="mx-auto h-10 w-10 animate-spin opacity-70" />
          <p className="mt-2 text-sm">Loading workbook…</p>
        </div>
      </div>
    );
  }

  if (error || !workbook) {
    return (
      <div
        className={cn(
          "flex h-full min-h-[200px] items-center justify-center text-destructive",
          className
        )}
      >
        <div className="text-center">
          <FileSpreadsheet className="mx-auto h-12 w-12 opacity-50" />
          <p className="mt-2 text-sm">{error ?? "Failed to load workbook"}</p>
        </div>
      </div>
    );
  }

  if (workbook.sheetNames.length === 0) {
    return (
      <div
        className={cn(
          "flex h-full min-h-[200px] items-center justify-center text-muted-foreground",
          className
        )}
      >
        <div className="text-center">
          <FileSpreadsheet className="mx-auto h-12 w-12 opacity-50" />
          <p className="mt-2 text-sm">Workbook has no sheets</p>
        </div>
      </div>
    );
  }

  const rows = activeSheet ? workbook.sheets[activeSheet] ?? [] : [];
  const maxCols =
    rows.length > 0
      ? Math.max(...rows.map((r) => r.length))
      : 0;

  return (
    <div className={cn("flex h-full flex-col overflow-hidden", className)}>
      <Tabs
        value={activeSheet ?? ""}
        onValueChange={(v) => setActiveSheet(v)}
        className="flex h-full flex-col overflow-hidden"
      >
        <TabsList className="flex-none w-full justify-start overflow-x-auto rounded-none border-b bg-muted/30 px-2">
          {workbook.sheetNames.map((name) => {
            const sheetRows = workbook.sheets[name] ?? [];
            const rowCount = Math.max(0, sheetRows.length - 1); // exclude header
            const colCount =
              rowCount > 0 ? Math.max(...sheetRows.map((r) => r.length)) : 0;
            return (
              <TabsTrigger
                key={name}
                value={name}
                className="rounded-b-none border-b-2 border-transparent data-[state=active]:border-primary data-[state=active]:bg-background"
              >
                {name} ({rowCount}×{colCount})
              </TabsTrigger>
            );
          })}
        </TabsList>
        <TabsContent
          value={activeSheet ?? ""}
          className="mt-0 flex-1 overflow-hidden data-[state=inactive]:hidden"
        >
          <div className="h-full w-full overflow-auto">
            <div className="min-w-max p-2">
              {rows.length === 0 ? (
                <div className="flex h-32 items-center justify-center text-sm text-muted-foreground">
                  No data in this sheet
                </div>
              ) : (
                <Table>
                  <TableHeader>
                    <TableRow>
                      {(rows[0].length >= maxCols ? rows[0] : [...rows[0], ...Array(maxCols - rows[0].length).fill("")]).map(
                        (cell, colIndex) => (
                          <TableHead
                            key={colIndex}
                            className="whitespace-nowrap border bg-muted/50 px-3 py-2 text-xs font-medium"
                          >
                            {String(cell ?? "")}
                          </TableHead>
                        )
                      )}
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {rows.slice(1).map((row, rowIndex) => (
                      <TableRow key={rowIndex}>
                        {(row.length >= maxCols ? row : [...row, ...Array(maxCols - row.length).fill("")]).map(
                          (cell, colIndex) => (
                            <TableCell
                              key={colIndex}
                              className="whitespace-nowrap border px-3 py-1.5 text-xs"
                            >
                              {cell !== undefined && cell !== null
                                ? String(cell)
                                : ""}
                            </TableCell>
                          )
                        )}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              )}
            </div>
          </div>
        </TabsContent>
      </Tabs>
    </div>
  );
}
