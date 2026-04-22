"use client";

import { useState, useMemo, useCallback, useEffect } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  useReactTable,
  getCoreRowModel,
  type ColumnDef,
  type SortingState,
  flexRender,
} from "@tanstack/react-table";
import { Search, ArrowUpDown, ArrowUp, ArrowDown, FileText } from "lucide-react";
import { fetchPapers, fetchTopics } from "@/lib/api";
import type { Paper, Topic } from "@/lib/types";
import { cn } from "@/lib/utils";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const PAGE_SIZE = 50;

const STATUS_STYLES: Record<string, string> = {
  meta_only: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300",
  pdf_ready: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  annotated: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
};

const RELEVANCE_STYLES: Record<string, string> = {
  high: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300",
  medium: "bg-blue-100 text-blue-700 dark:bg-blue-900 dark:text-blue-300",
  low: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
};

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatAuthors(authors: string | string[] | null): string {
  if (!authors) return "--";
  const list = Array.isArray(authors) ? authors : [authors];
  if (list.length === 0) return "--";
  if (list.length <= 3) return list.join(", ");
  return `${list.slice(0, 2).join(", ")} et al.`;
}

function derivePaperStatus(paper: Paper): string {
  if (paper.pdf_path) return "pdf_ready";
  return "meta_only";
}

// ---------------------------------------------------------------------------
// Debounce hook
// ---------------------------------------------------------------------------

function useDebouncedSearch(value: string, delay: number): string {
  const [debounced, setDebounced] = useState(value);

  useEffect(() => {
    const timer = setTimeout(() => setDebounced(value), delay);
    return () => clearTimeout(timer);
  }, [value, delay]);

  return debounced;
}

// ---------------------------------------------------------------------------
// Sort header component
// ---------------------------------------------------------------------------

function SortableHeader({
  label,
  columnId,
  sorting,
  onSort,
}: {
  label: string;
  columnId: string;
  sorting: SortingState;
  onSort: (id: string) => void;
}) {
  const current = sorting.find((s) => s.id === columnId);
  return (
    <button
      type="button"
      className="inline-flex items-center gap-1 hover:text-foreground"
      onClick={() => onSort(columnId)}
    >
      {label}
      {current ? (
        current.desc ? (
          <ArrowDown className="size-3.5" />
        ) : (
          <ArrowUp className="size-3.5" />
        )
      ) : (
        <ArrowUpDown className="size-3.5 opacity-40" />
      )}
    </button>
  );
}

// ---------------------------------------------------------------------------
// Pagination
// ---------------------------------------------------------------------------

function PaginationControls({
  page,
  totalPages,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  onPageChange: (p: number) => void;
}) {
  // Build a compact page range: [1, ..., page-1, page, page+1, ..., totalPages]
  const pages = useMemo(() => {
    const result: (number | "ellipsis")[] = [];
    const delta = 2;
    const start = Math.max(2, page - delta);
    const end = Math.min(totalPages - 1, page + delta);

    result.push(1);
    if (start > 2) result.push("ellipsis");
    for (let i = start; i <= end; i++) result.push(i);
    if (end < totalPages - 1) result.push("ellipsis");
    if (totalPages > 1) result.push(totalPages);

    return result;
  }, [page, totalPages]);

  if (totalPages <= 1) return null;

  return (
    <div className="flex items-center justify-center gap-1">
      <Button
        variant="outline"
        size="sm"
        disabled={page <= 1}
        onClick={() => onPageChange(page - 1)}
      >
        Previous
      </Button>
      {pages.map((p, i) =>
        p === "ellipsis" ? (
          <span
            key={`ellipsis-${i}`}
            className="px-2 text-sm text-muted-foreground"
          >
            ...
          </span>
        ) : (
          <Button
            key={p}
            variant={p === page ? "default" : "outline"}
            size="sm"
            onClick={() => onPageChange(p)}
            className="min-w-[2rem] tabular-nums"
          >
            {p}
          </Button>
        )
      )}
      <Button
        variant="outline"
        size="sm"
        disabled={page >= totalPages}
        onClick={() => onPageChange(page + 1)}
      >
        Next
      </Button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Table skeleton
// ---------------------------------------------------------------------------

function TableSkeleton() {
  return (
    <div className="space-y-2">
      {Array.from({ length: 10 }).map((_, i) => (
        <div key={i} className="flex items-center gap-4 px-2 py-3">
          <Skeleton className="h-4 w-[40%]" />
          <Skeleton className="h-4 w-[20%]" />
          <Skeleton className="h-4 w-12" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-14 rounded-full" />
        </div>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Empty state
// ---------------------------------------------------------------------------

function EmptyState({ hasFilters }: { hasFilters: boolean }) {
  return (
    <div className="flex flex-col items-center justify-center py-20 text-center">
      <FileText className="size-10 text-muted-foreground/50" />
      <h3 className="mt-4 text-sm font-medium text-foreground">
        No papers found
      </h3>
      <p className="mt-1 text-sm text-muted-foreground">
        {hasFilters
          ? "Try adjusting your search or filters."
          : "Ingest papers via the CLI or MCP tools to get started."}
      </p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function LibraryPage() {
  // -- State ----------------------------------------------------------------
  const [search, setSearch] = useState("");
  const debouncedSearch = useDebouncedSearch(search, 300);
  const [topicId, setTopicId] = useState<number | undefined>(undefined);
  const [page, setPage] = useState(1);
  const [sorting, setSorting] = useState<SortingState>([
    { id: "year", desc: true },
  ]);

  // Reset to page 1 when filters change
  const handleSearchChange = useCallback((value: string) => {
    setSearch(value);
    setPage(1);
  }, []);

  const handleTopicChange = useCallback((value: string | null) => {
    setTopicId(!value || value === "all" ? undefined : Number(value));
    setPage(1);
  }, []);

  // -- Derive sort params ---------------------------------------------------
  const sortField = sorting[0]?.id ?? "year";
  const sortOrder = sorting[0]?.desc ? "desc" : "asc";

  // -- Data fetching --------------------------------------------------------
  const topicsQuery = useQuery({
    queryKey: ["topics"],
    queryFn: () => fetchTopics(),
    staleTime: 60_000,
  });

  const papersQuery = useQuery({
    queryKey: ["papers", { page, search: debouncedSearch, topicId, sortField, sortOrder }],
    queryFn: () =>
      fetchPapers({
        page,
        page_size: PAGE_SIZE,
        search: debouncedSearch || undefined,
        topic_id: topicId,
        sort: sortField,
        order: sortOrder as "asc" | "desc",
      }),
    placeholderData: (prev) => prev,
  });

  const papers = papersQuery.data?.items ?? [];
  const total = papersQuery.data?.total ?? 0;
  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  // -- Column sort handler --------------------------------------------------
  const handleSort = useCallback(
    (columnId: string) => {
      setSorting((prev) => {
        const existing = prev.find((s) => s.id === columnId);
        if (existing) {
          // Toggle direction, or remove if already asc
          if (!existing.desc) return [];
          return [{ id: columnId, desc: false }];
        }
        return [{ id: columnId, desc: true }];
      });
      setPage(1);
    },
    []
  );

  // -- TanStack Table columns -----------------------------------------------
  const columns = useMemo<ColumnDef<Paper>[]>(
    () => [
      {
        id: "title",
        accessorKey: "title",
        header: () => (
          <SortableHeader
            label="Title"
            columnId="title"
            sorting={sorting}
            onSort={handleSort}
          />
        ),
        cell: ({ row }) => (
          <div className="max-w-[400px]">
            <p className="truncate font-medium text-foreground" title={row.original.title}>
              {row.original.title}
            </p>
            {row.original.arxiv_id && (
              <p className="mt-0.5 truncate text-xs text-muted-foreground">
                {row.original.arxiv_id}
              </p>
            )}
          </div>
        ),
      },
      {
        id: "authors",
        accessorKey: "authors",
        header: "Authors",
        cell: ({ row }) => (
          <span
            className="block max-w-[200px] truncate text-muted-foreground"
            title={
              Array.isArray(row.original.authors)
                ? row.original.authors.join(", ")
                : row.original.authors ?? ""
            }
          >
            {formatAuthors(row.original.authors)}
          </span>
        ),
      },
      {
        id: "year",
        accessorKey: "year",
        header: () => (
          <SortableHeader
            label="Year"
            columnId="year"
            sorting={sorting}
            onSort={handleSort}
          />
        ),
        cell: ({ row }) => (
          <span className="tabular-nums text-muted-foreground">
            {row.original.year ?? "--"}
          </span>
        ),
      },
      {
        id: "venue",
        accessorKey: "venue",
        header: () => (
          <SortableHeader
            label="Venue"
            columnId="venue"
            sorting={sorting}
            onSort={handleSort}
          />
        ),
        cell: ({ row }) => {
          const venue = row.original.venue;
          if (!venue) return <span className="text-muted-foreground">--</span>;
          return (
            <Badge
              variant="secondary"
              className="max-w-[120px] truncate text-xs font-normal"
              title={venue}
            >
              {venue}
            </Badge>
          );
        },
      },
      {
        id: "status",
        header: "Status",
        cell: ({ row }) => {
          const status = derivePaperStatus(row.original);
          const label = status.replace("_", " ");
          return (
            <Badge
              variant="secondary"
              className={cn(
                "text-xs font-normal capitalize",
                STATUS_STYLES[status] ?? STATUS_STYLES.meta_only
              )}
            >
              {label}
            </Badge>
          );
        },
      },
      {
        id: "relevance",
        header: "Relevance",
        cell: ({ row }) => {
          const rel = row.original.relevance;
          if (!rel) return <span className="text-muted-foreground">--</span>;
          return (
            <Badge
              variant="secondary"
              className={cn(
                "text-xs font-normal capitalize",
                RELEVANCE_STYLES[rel] ?? RELEVANCE_STYLES.low
              )}
            >
              {rel}
            </Badge>
          );
        },
      },
    ],
    [sorting, handleSort]
  );

  // -- TanStack Table instance ----------------------------------------------
  const table = useReactTable({
    data: papers,
    columns,
    state: { sorting },
    onSortingChange: setSorting,
    getCoreRowModel: getCoreRowModel(),
    manualSorting: true,
    manualPagination: true,
    pageCount: totalPages,
  });

  // -- Render ---------------------------------------------------------------
  const hasFilters = !!debouncedSearch || topicId != null;

  return (
    <div className="space-y-6 p-6 lg:p-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Paper Library</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          {total > 0
            ? `${total.toLocaleString()} papers across all topics`
            : "Browse and search your research paper collection."}
        </p>
      </div>

      {/* Toolbar: search + filters */}
      <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
        <div className="relative flex-1">
          <Search className="pointer-events-none absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
          <Input
            placeholder="Search title, authors, venue..."
            value={search}
            onChange={(e) => handleSearchChange(e.target.value)}
            className="pl-9"
          />
        </div>
        <Select
          value={topicId != null ? String(topicId) : "all"}
          onValueChange={handleTopicChange}
        >
          <SelectTrigger className="w-full sm:w-[220px]">
            <SelectValue placeholder="All topics" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="all">All topics</SelectItem>
            {(topicsQuery.data ?? []).map((topic: Topic) => (
              <SelectItem key={topic.id} value={String(topic.id)}>
                {topic.name}
                <span className="ml-1 text-muted-foreground">
                  ({topic.paper_count})
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      {/* Table */}
      <div className="rounded-lg border border-border bg-white dark:bg-slate-900">
        {papersQuery.isPending ? (
          <div className="p-4">
            <TableSkeleton />
          </div>
        ) : papers.length === 0 ? (
          <EmptyState hasFilters={hasFilters} />
        ) : (
          <Table>
            <TableHeader>
              {table.getHeaderGroups().map((headerGroup) => (
                <TableRow key={headerGroup.id}>
                  {headerGroup.headers.map((header) => (
                    <TableHead key={header.id}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext()
                          )}
                    </TableHead>
                  ))}
                </TableRow>
              ))}
            </TableHeader>
            <TableBody>
              {table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext()
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </div>

      {/* Pagination footer */}
      {totalPages > 1 && (
        <div className="flex flex-col items-center gap-2 sm:flex-row sm:justify-between">
          <p className="text-sm text-muted-foreground tabular-nums">
            Showing{" "}
            {((page - 1) * PAGE_SIZE + 1).toLocaleString()}
            {" -- "}
            {Math.min(page * PAGE_SIZE, total).toLocaleString()} of{" "}
            {total.toLocaleString()}
          </p>
          <PaginationControls
            page={page}
            totalPages={totalPages}
            onPageChange={setPage}
          />
        </div>
      )}
    </div>
  );
}
