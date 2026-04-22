"use client";

import { useQuery } from "@tanstack/react-query";
import { FolderKanban } from "lucide-react";
import Link from "next/link";
import { fetchProjects } from "@/lib/api";
import {
  RESEARCH_STAGES,
  STAGE_LABELS,
  STAGE_COLORS,
  STAGE_TEXT_COLORS,
  STAGE_BG_COLORS,
  type ResearchStage,
  type Project,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  Table,
  TableHeader,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
} from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// Stage progress mini bar (inline, same as dashboard)
// ---------------------------------------------------------------------------

function stageIndex(stage: ResearchStage | null): number {
  if (!stage) return 0;
  const idx = RESEARCH_STAGES.indexOf(stage);
  return idx === -1 ? 0 : idx + 1;
}

function StageProgressBar({ stage }: { stage: ResearchStage | null }) {
  const completed = stageIndex(stage);

  return (
    <div className="flex items-center gap-0.5">
      {RESEARCH_STAGES.map((s, i) => (
        <div
          key={s}
          className={cn(
            "h-1.5 w-4 rounded-sm transition-colors",
            i < completed ? STAGE_COLORS[s] : "bg-slate-200 dark:bg-slate-700"
          )}
          title={STAGE_LABELS[s]}
        />
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gate status badge
// ---------------------------------------------------------------------------

function GateBadge({ status }: { status: string | null }) {
  if (!status) {
    return (
      <Badge variant="secondary" className="text-xs text-muted-foreground">
        --
      </Badge>
    );
  }

  const lower = status.toLowerCase();
  if (lower === "pass" || lower === "passed" || lower === "approved") {
    return (
      <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900 dark:text-emerald-300 text-xs">
        {status}
      </Badge>
    );
  }
  if (lower === "fail" || lower === "failed" || lower === "blocked") {
    return (
      <Badge className="bg-red-100 text-red-700 dark:bg-red-900 dark:text-red-300 text-xs">
        {status}
      </Badge>
    );
  }

  return (
    <Badge variant="secondary" className="text-xs">
      {status}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Relative time formatter
// ---------------------------------------------------------------------------

function formatRelative(dateStr: string): string {
  if (!dateStr) return "--";
  const date = new Date(dateStr);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60_000);
  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  const diffHours = Math.floor(diffMins / 60);
  if (diffHours < 24) return `${diffHours}h ago`;
  const diffDays = Math.floor(diffHours / 24);
  if (diffDays < 30) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

// ---------------------------------------------------------------------------
// Table row
// ---------------------------------------------------------------------------

function ProjectRow({ project }: { project: Project }) {
  const stage = project.current_stage;

  return (
    <TableRow className="group">
      {/* Name */}
      <TableCell>
        <Link
          href={`/projects/${project.id}`}
          className="font-medium text-foreground hover:text-blue-600 dark:hover:text-blue-400 transition-colors"
        >
          {project.name}
        </Link>
      </TableCell>

      {/* Topic */}
      <TableCell className="text-muted-foreground">
        {project.topic_name ?? `#${project.topic_id}`}
      </TableCell>

      {/* Stage badge */}
      <TableCell>
        {stage ? (
          <Badge
            variant="secondary"
            className={cn(
              "text-xs font-medium",
              STAGE_BG_COLORS[stage],
              STAGE_TEXT_COLORS[stage]
            )}
          >
            {STAGE_LABELS[stage]}
          </Badge>
        ) : (
          <span className="text-xs text-muted-foreground">--</span>
        )}
      </TableCell>

      {/* Stage status */}
      <TableCell className="text-xs text-muted-foreground">
        {project.stage_status ?? "--"}
      </TableCell>

      {/* Gate */}
      <TableCell>
        <GateBadge status={project.gate_status ?? null} />
      </TableCell>

      {/* Venue */}
      <TableCell className="text-xs text-muted-foreground">
        {project.target_venue || "--"}
      </TableCell>

      {/* Updated */}
      <TableCell className="text-xs text-muted-foreground tabular-nums">
        {formatRelative(project.updated_at)}
      </TableCell>

      {/* Progress bar */}
      <TableCell>
        <StageProgressBar stage={stage} />
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// Table skeleton
// ---------------------------------------------------------------------------

function TableRowSkeleton() {
  return (
    <TableRow>
      <TableCell>
        <Skeleton className="h-4 w-32" />
      </TableCell>
      <TableCell>
        <Skeleton className="h-4 w-28" />
      </TableCell>
      <TableCell>
        <Skeleton className="h-5 w-16 rounded-full" />
      </TableCell>
      <TableCell>
        <Skeleton className="h-3 w-20" />
      </TableCell>
      <TableCell>
        <Skeleton className="h-5 w-12 rounded-full" />
      </TableCell>
      <TableCell>
        <Skeleton className="h-3 w-14" />
      </TableCell>
      <TableCell>
        <Skeleton className="h-3 w-12" />
      </TableCell>
      <TableCell>
        <div className="flex gap-0.5">
          {Array.from({ length: 6 }).map((_, i) => (
            <Skeleton key={i} className="h-1.5 w-4 rounded-sm" />
          ))}
        </div>
      </TableCell>
    </TableRow>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function ProjectsPage() {
  const { data: projects, isPending, error } = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  return (
    <div className="space-y-6 p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-violet-600">
          <FolderKanban className="size-5 text-white" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">Projects</h1>
          <p className="text-sm text-muted-foreground">
            All research projects and their pipeline status.
          </p>
        </div>
      </div>

      {/* Table */}
      <div className="rounded-xl bg-card ring-1 ring-foreground/10">
        <Table>
          <TableHeader>
            <TableRow>
              <TableHead>Project</TableHead>
              <TableHead>Topic</TableHead>
              <TableHead>Stage</TableHead>
              <TableHead>Status</TableHead>
              <TableHead>Gate</TableHead>
              <TableHead>Venue</TableHead>
              <TableHead>Updated</TableHead>
              <TableHead>Progress</TableHead>
            </TableRow>
          </TableHeader>
          <TableBody>
            {isPending ? (
              <>
                <TableRowSkeleton />
                <TableRowSkeleton />
                <TableRowSkeleton />
                <TableRowSkeleton />
                <TableRowSkeleton />
              </>
            ) : error ? (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-sm text-muted-foreground py-12">
                  Failed to load projects.
                </TableCell>
              </TableRow>
            ) : projects?.length ? (
              projects.map((project) => (
                <ProjectRow key={project.id} project={project} />
              ))
            ) : (
              <TableRow>
                <TableCell colSpan={8} className="text-center text-sm text-muted-foreground py-12">
                  No projects found. Create one via the CLI to get started.
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>
    </div>
  );
}
