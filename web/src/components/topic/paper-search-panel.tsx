"use client";

import { useState, useCallback } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Search,
  Download,
  Loader2,
  CheckSquare,
  Square,
  Link as LinkIcon,
  AlertCircle,
  CheckCircle2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";

// ---------------------------------------------------------------------------
// API stubs — will be replaced when api.ts adds these functions
// ---------------------------------------------------------------------------

interface SearchResult {
  title: string;
  authors: string | null;
  year: number | null;
  venue: string | null;
  arxiv_id: string | null;
  doi: string | null;
  source: string | null;
}

interface WriteResponse {
  status: string;
  summary: string;
  output: unknown;
  next_actions: string[];
  artifacts: unknown[];
  recovery_hint: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function searchPapers(params: {
  query: string;
  topic_id: number;
  max_results?: number;
}): Promise<WriteResponse> {
  const res = await fetch(`${API_BASE}/api/papers/search`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

async function ingestPaper(params: {
  source: string;
  topic_id: number;
  relevance?: string;
}): Promise<WriteResponse> {
  const res = await fetch(`${API_BASE}/api/papers/ingest`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface PaperSearchPanelProps {
  topicId: number;
}

export function PaperSearchPanel({ topicId }: PaperSearchPanelProps) {
  // Search state
  const [query, setQuery] = useState("");
  const [results, setResults] = useState<SearchResult[]>([]);
  const [selected, setSelected] = useState<Set<number>>(new Set());

  // Import-by-ID state
  const [importId, setImportId] = useState("");

  // Feedback messages
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  // Search mutation
  const searchMut = useMutation({
    mutationFn: () =>
      searchPapers({ query, topic_id: topicId, max_results: 30 }),
    onSuccess: (data) => {
      const items = Array.isArray(data.output) ? data.output : [];
      setResults(items as SearchResult[]);
      setSelected(new Set());
      setFeedback({
        type: "success",
        message: data.summary || `Found ${items.length} papers`,
      });
    },
    onError: (err: Error) => {
      setFeedback({ type: "error", message: err.message });
    },
  });

  // Ingest selected mutation
  const ingestMut = useMutation({
    mutationFn: async () => {
      const items = Array.from(selected).map((idx) => results[idx]);
      const responses: WriteResponse[] = [];
      for (const item of items) {
        const source =
          item.arxiv_id ?? item.doi ?? item.title ?? "unknown";
        const resp = await ingestPaper({
          source,
          topic_id: topicId,
          relevance: "medium",
        });
        responses.push(resp);
      }
      return responses;
    },
    onSuccess: (responses) => {
      setSelected(new Set());
      setFeedback({
        type: "success",
        message: `Ingested ${responses.length} paper(s)`,
      });
    },
    onError: (err: Error) => {
      setFeedback({ type: "error", message: err.message });
    },
  });

  // Import-by-ID mutation
  const importMut = useMutation({
    mutationFn: () =>
      ingestPaper({ source: importId.trim(), topic_id: topicId, relevance: "high" }),
    onSuccess: (data) => {
      setImportId("");
      setFeedback({
        type: "success",
        message: data.summary || "Paper imported successfully",
      });
    },
    onError: (err: Error) => {
      setFeedback({ type: "error", message: err.message });
    },
  });

  // Selection helpers
  const toggleSelect = useCallback(
    (idx: number) => {
      setSelected((prev) => {
        const next = new Set(prev);
        if (next.has(idx)) next.delete(idx);
        else next.add(idx);
        return next;
      });
    },
    []
  );

  const toggleAll = useCallback(() => {
    if (selected.size === results.length) {
      setSelected(new Set());
    } else {
      setSelected(new Set(results.map((_, i) => i)));
    }
  }, [selected.size, results]);

  const handleSearch = (e: React.FormEvent) => {
    e.preventDefault();
    if (!query.trim()) return;
    searchMut.mutate();
  };

  const handleImport = (e: React.FormEvent) => {
    e.preventDefault();
    if (!importId.trim()) return;
    importMut.mutate();
  };

  const isLoading =
    searchMut.isPending || ingestMut.isPending || importMut.isPending;

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Search className="size-4" />
          Paper Search & Ingestion
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* ---- Search form ---- */}
        <form onSubmit={handleSearch} className="flex gap-2">
          <Input
            placeholder="Search query (e.g. budget pacing reinforcement learning)"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            disabled={searchMut.isPending}
            className="flex-1"
          />
          <Button type="submit" disabled={searchMut.isPending || !query.trim()}>
            {searchMut.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <Search className="size-4" />
            )}
            Search
          </Button>
        </form>

        {/* ---- Import by ID ---- */}
        <form onSubmit={handleImport} className="flex gap-2">
          <Input
            placeholder="arXiv ID or DOI (e.g. 2401.12345)"
            value={importId}
            onChange={(e) => setImportId(e.target.value)}
            disabled={importMut.isPending}
            className="flex-1"
          />
          <Button
            type="submit"
            variant="outline"
            disabled={importMut.isPending || !importId.trim()}
          >
            {importMut.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <LinkIcon className="size-4" />
            )}
            Import
          </Button>
        </form>

        {/* ---- Feedback message ---- */}
        {feedback && (
          <div
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-2 text-sm",
              feedback.type === "success"
                ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
                : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300"
            )}
          >
            {feedback.type === "success" ? (
              <CheckCircle2 className="size-4 shrink-0" />
            ) : (
              <AlertCircle className="size-4 shrink-0" />
            )}
            <span className="flex-1">{feedback.message}</span>
            <button
              type="button"
              className="text-xs underline opacity-60 hover:opacity-100"
              onClick={() => setFeedback(null)}
            >
              dismiss
            </button>
          </div>
        )}

        {/* ---- Results list ---- */}
        {results.length > 0 && (
          <>
            <Separator />

            <div className="flex items-center justify-between">
              <div className="flex items-center gap-2">
                <button
                  type="button"
                  onClick={toggleAll}
                  className="flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  {selected.size === results.length ? (
                    <CheckSquare className="size-4" />
                  ) : (
                    <Square className="size-4" />
                  )}
                  {selected.size > 0
                    ? `${selected.size} selected`
                    : "Select all"}
                </button>
              </div>

              <Button
                size="sm"
                disabled={selected.size === 0 || ingestMut.isPending}
                onClick={() => ingestMut.mutate()}
              >
                {ingestMut.isPending ? (
                  <Loader2 className="size-3.5 animate-spin" />
                ) : (
                  <Download className="size-3.5" />
                )}
                Ingest Selected ({selected.size})
              </Button>
            </div>

            <div className="max-h-[400px] overflow-y-auto rounded-md border border-foreground/5 divide-y divide-foreground/5">
              {results.map((paper, idx) => (
                <button
                  key={idx}
                  type="button"
                  onClick={() => toggleSelect(idx)}
                  className={cn(
                    "flex w-full items-start gap-3 px-3 py-2.5 text-left transition-colors hover:bg-muted/50",
                    selected.has(idx) && "bg-blue-50/50 dark:bg-blue-900/10"
                  )}
                >
                  {selected.has(idx) ? (
                    <CheckSquare className="size-4 shrink-0 mt-0.5 text-blue-600" />
                  ) : (
                    <Square className="size-4 shrink-0 mt-0.5 text-muted-foreground" />
                  )}
                  <div className="flex-1 min-w-0 space-y-1">
                    <p className="text-sm font-medium leading-snug line-clamp-2">
                      {paper.title}
                    </p>
                    <div className="flex flex-wrap items-center gap-1.5">
                      {paper.authors && (
                        <span className="text-xs text-muted-foreground truncate max-w-[300px]">
                          {paper.authors}
                        </span>
                      )}
                      {paper.year && (
                        <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
                          {paper.year}
                        </Badge>
                      )}
                      {paper.venue && (
                        <Badge variant="outline" className="text-[10px] h-4 px-1.5">
                          {paper.venue}
                        </Badge>
                      )}
                      {paper.arxiv_id && (
                        <span className="text-[10px] text-muted-foreground font-mono">
                          {paper.arxiv_id}
                        </span>
                      )}
                    </div>
                  </div>
                </button>
              ))}
            </div>
          </>
        )}

        {/* ---- Empty state after search ---- */}
        {searchMut.isSuccess && results.length === 0 && (
          <p className="py-4 text-center text-sm text-muted-foreground">
            No papers found for &ldquo;{query}&rdquo;
          </p>
        )}
      </CardContent>
    </Card>
  );
}
