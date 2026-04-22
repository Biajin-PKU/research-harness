"use client";

import { useQuery } from "@tanstack/react-query";
import {
  FileText,
  FolderKanban,
  BookOpen,
  DollarSign,
} from "lucide-react";
import Link from "next/link";
import { fetchDashboardStats, fetchProjects } from "@/lib/api";
import {
  RESEARCH_STAGES,
  STAGE_LABELS,
  STAGE_COLORS,
  STAGE_TEXT_COLORS,
  STAGE_BG_COLORS,
  type ResearchStage,
  type DashboardStats,
  type Project,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Skeleton } from "@/components/ui/skeleton";

// ---------------------------------------------------------------------------
// Stat card
// ---------------------------------------------------------------------------

interface StatCardProps {
  label: string;
  value: string | number;
  icon: React.ComponentType<{ className?: string }>;
  accent: string;
}

function StatCard({ label, value, icon: Icon, accent }: StatCardProps) {
  return (
    <Card>
      <CardContent className="flex items-center gap-4">
        <div
          className={cn(
            "flex size-10 shrink-0 items-center justify-center rounded-lg",
            accent
          )}
        >
          <Icon className="size-5 text-white" />
        </div>
        <div className="min-w-0">
          <p className="text-xs font-medium text-muted-foreground">{label}</p>
          <p className="truncate text-2xl font-semibold tabular-nums">
            {value}
          </p>
        </div>
      </CardContent>
    </Card>
  );
}

function StatCardSkeleton() {
  return (
    <Card>
      <CardContent className="flex items-center gap-4">
        <Skeleton className="size-10 rounded-lg" />
        <div className="space-y-2">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-14" />
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Stage progress mini bar
// ---------------------------------------------------------------------------

function stageIndex(stage: ResearchStage | null): number {
  if (!stage) return 0;
  const idx = RESEARCH_STAGES.indexOf(stage);
  return idx === -1 ? 0 : idx + 1;
}

function StageProgress({ stage }: { stage: ResearchStage | null }) {
  const completed = stageIndex(stage);
  const total = RESEARCH_STAGES.length;

  return (
    <div className="flex items-center gap-1.5">
      {RESEARCH_STAGES.map((s, i) => (
        <div
          key={s}
          className={cn(
            "h-1.5 flex-1 rounded-full transition-colors",
            i < completed
              ? STAGE_COLORS[s]
              : "bg-slate-200 dark:bg-slate-700"
          )}
          title={STAGE_LABELS[s]}
        />
      ))}
      <span className="ml-1 text-xs tabular-nums text-muted-foreground">
        {completed}/{total}
      </span>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Project card
// ---------------------------------------------------------------------------

function ProjectCard({ project }: { project: Project }) {
  const stage = project.current_stage;

  return (
    <Link href={`/projects/${project.id}`} className="block">
      <Card className="transition-shadow hover:ring-2 hover:ring-blue-500/20">
        <CardHeader>
          <CardTitle>{project.name}</CardTitle>
          <CardDescription className="truncate">
            {project.topic_name ?? `Topic #${project.topic_id}`}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            {stage && (
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
            )}
            {project.stage_status && (
              <span className="text-xs text-muted-foreground">
                {project.stage_status}
              </span>
            )}
          </div>
          <StageProgress stage={stage} />
        </CardContent>
      </Card>
    </Link>
  );
}

function ProjectCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-48" />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-3 w-20" />
        </div>
        <Skeleton className="h-1.5 w-full rounded-full" />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Dashboard page
// ---------------------------------------------------------------------------

export default function DashboardPage() {
  const statsQuery = useQuery({
    queryKey: ["dashboard-stats"],
    queryFn: fetchDashboardStats,
  });

  const projectsQuery = useQuery({
    queryKey: ["projects"],
    queryFn: fetchProjects,
  });

  const stats: DashboardStats | undefined = statsQuery.data;

  return (
    <div className="space-y-8 p-6 lg:p-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Overview of your research projects and paper library.
        </p>
      </div>

      {/* Stat cards */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        {statsQuery.isPending ? (
          <>
            <StatCardSkeleton />
            <StatCardSkeleton />
            <StatCardSkeleton />
            <StatCardSkeleton />
          </>
        ) : stats ? (
          <>
            <StatCard
              label="Total Papers"
              value={stats.total_papers.toLocaleString()}
              icon={FileText}
              accent="bg-blue-600"
            />
            <StatCard
              label="Projects"
              value={stats.total_projects}
              icon={FolderKanban}
              accent="bg-violet-600"
            />
            <StatCard
              label="Topics"
              value={stats.total_topics}
              icon={BookOpen}
              accent="bg-emerald-600"
            />
            <StatCard
              label="Artifacts"
              value={stats.total_artifacts.toLocaleString()}
              icon={DollarSign}
              accent="bg-amber-600"
            />
          </>
        ) : (
          <p className="col-span-full text-sm text-muted-foreground">
            Failed to load statistics.
          </p>
        )}
      </div>

      {/* Projects grid */}
      <div>
        <h2 className="mb-4 text-lg font-semibold tracking-tight">
          Projects
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {projectsQuery.isPending ? (
            <>
              <ProjectCardSkeleton />
              <ProjectCardSkeleton />
              <ProjectCardSkeleton />
              <ProjectCardSkeleton />
              <ProjectCardSkeleton />
              <ProjectCardSkeleton />
            </>
          ) : projectsQuery.data?.length ? (
            projectsQuery.data.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))
          ) : (
            <p className="col-span-full text-sm text-muted-foreground">
              No projects found. Create one to get started.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
