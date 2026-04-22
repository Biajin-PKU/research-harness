"use client";

import { useParams } from "next/navigation";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { useRef, useCallback, useState } from "react";
import {
  ArrowLeft,
  Calendar,
  MapPin,
  AlertTriangle,
  ChevronDown,
  ChevronRight,
  Clock,
  FileText,
  ShieldAlert,
  CheckCircle2,
  XCircle,
  MinusCircle,
} from "lucide-react";
import Link from "next/link";
import {
  fetchProject,
  fetchProjectArtifacts,
  fetchProjectEvents,
  fetchProjectIssues,
} from "@/lib/api";
import {
  RESEARCH_STAGES,
  STAGE_LABELS,
  STAGE_DESCRIPTIONS,
  STAGE_TEXT_COLORS,
  STAGE_BG_COLORS,
  STAGE_COLORS,
  type ResearchStage,
  type Artifact,
  type StageEvent,
  type ReviewIssue,
  type ProjectDetail,
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
import { Separator } from "@/components/ui/separator";
import {
  StagePipeline,
  StagePipelineSkeleton,
} from "@/components/project/stage-pipeline";
import { PaperSearchPanel } from "@/components/project/paper-search-panel";
import { AnalysisPanel } from "@/components/project/analysis-panel";
import { ActionToolbar } from "@/components/project/action-toolbar";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return "--";
  const d = new Date(dateStr);
  return d.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  });
}

function formatTimestamp(dateStr: string | null | undefined): string {
  if (!dateStr) return "--";
  const d = new Date(dateStr);
  return d.toLocaleString("en-US", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

// ---------------------------------------------------------------------------
// Severity badge
// ---------------------------------------------------------------------------

function SeverityBadge({ severity }: { severity: ReviewIssue["severity"] }) {
  const styles: Record<string, string> = {
    critical: "bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300",
    high: "bg-orange-100 text-orange-700 dark:bg-orange-900/50 dark:text-orange-300",
    medium: "bg-yellow-100 text-yellow-700 dark:bg-yellow-900/50 dark:text-yellow-300",
    low: "bg-slate-100 text-slate-600 dark:bg-slate-800 dark:text-slate-400",
  };

  return (
    <Badge className={cn("text-xs font-medium", styles[severity] ?? styles.low)}>
      {severity}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Issue status icon
// ---------------------------------------------------------------------------

function IssueStatusIcon({ status }: { status: ReviewIssue["status"] }) {
  switch (status) {
    case "resolved":
      return <CheckCircle2 className="size-4 text-emerald-500" />;
    case "wontfix":
      return <MinusCircle className="size-4 text-slate-400" />;
    case "in_progress":
      return <Clock className="size-4 text-blue-500" />;
    default:
      return <XCircle className="size-4 text-red-400" />;
  }
}

// ---------------------------------------------------------------------------
// Event type badge
// ---------------------------------------------------------------------------

function EventTypeBadge({ type }: { type: StageEvent["event_type"] }) {
  const styles: Record<string, string> = {
    advance: "bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300",
    gate_check: "bg-blue-100 text-blue-700 dark:bg-blue-900/50 dark:text-blue-300",
    artifact_record: "bg-violet-100 text-violet-700 dark:bg-violet-900/50 dark:text-violet-300",
    decision: "bg-amber-100 text-amber-700 dark:bg-amber-900/50 dark:text-amber-300",
  };

  return (
    <Badge className={cn("text-xs font-medium", styles[type] ?? "bg-slate-100 text-slate-600")}>
      {type.replace(/_/g, " ")}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Artifact preview (expandable)
// ---------------------------------------------------------------------------

function ArtifactRow({ artifact }: { artifact: Artifact }) {
  const [expanded, setExpanded] = useState(false);

  return (
    <div className="border-b border-foreground/5 last:border-b-0">
      <button
        type="button"
        className="flex w-full items-center gap-3 px-3 py-2 text-left text-sm hover:bg-muted/50 transition-colors"
        onClick={() => setExpanded(!expanded)}
      >
        {expanded ? (
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight className="size-3.5 shrink-0 text-muted-foreground" />
        )}
        <FileText className="size-3.5 shrink-0 text-muted-foreground" />
        <span className="flex-1 truncate font-medium">
          {artifact.title || artifact.artifact_type}
        </span>
        <span className="text-xs text-muted-foreground tabular-nums">
          {formatTimestamp(artifact.created_at)}
        </span>
        {artifact.is_stale && (
          <Badge variant="destructive" className="text-[10px] h-4 px-1.5">
            stale
          </Badge>
        )}
      </button>

      {expanded && artifact.payload && (
        <div className="mx-3 mb-2 rounded-md bg-muted/50 p-3">
          <pre className="max-h-48 overflow-auto text-xs text-muted-foreground whitespace-pre-wrap font-mono leading-relaxed">
            {JSON.stringify(artifact.payload, null, 2).slice(0, 2000)}
            {JSON.stringify(artifact.payload, null, 2).length > 2000 && "\n..."}
          </pre>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Stage detail panel
// ---------------------------------------------------------------------------

interface StagePanelProps {
  stage: ResearchStage;
  artifacts: Artifact[];
  isCurrent: boolean;
}

function StagePanel({ stage, artifacts, isCurrent }: StagePanelProps) {
  return (
    <Card
      id={`stage-${stage}`}
      className={cn(isCurrent && "ring-2 ring-blue-500/30")}
    >
      <CardHeader>
        <div className="flex items-center gap-2">
          <div
            className={cn(
              "size-2.5 rounded-full",
              isCurrent ? STAGE_COLORS[stage] : "bg-slate-300 dark:bg-slate-600"
            )}
          />
          <CardTitle className="text-sm">
            {STAGE_LABELS[stage]}
          </CardTitle>
          {isCurrent && (
            <Badge variant="secondary" className="text-[10px] h-4 px-1.5">
              current
            </Badge>
          )}
        </div>
        <CardDescription className="text-xs">
          {STAGE_DESCRIPTIONS[stage]}
        </CardDescription>
      </CardHeader>
      <CardContent>
        {artifacts.length === 0 ? (
          <p className="text-xs text-muted-foreground py-2">
            No artifacts recorded for this stage.
          </p>
        ) : (
          <div className="rounded-md border border-foreground/5">
            {artifacts.map((art) => (
              <ArtifactRow key={art.id} artifact={art} />
            ))}
          </div>
        )}
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Header skeleton
// ---------------------------------------------------------------------------

function HeaderSkeleton() {
  return (
    <div className="space-y-3">
      <Skeleton className="h-5 w-24" />
      <Skeleton className="h-7 w-64" />
      <div className="flex gap-2">
        <Skeleton className="h-5 w-20 rounded-full" />
        <Skeleton className="h-5 w-20 rounded-full" />
        <Skeleton className="h-5 w-32 rounded-full" />
      </div>
    </div>
  );
}

function StagePanelSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-4 w-28" />
        <Skeleton className="h-3 w-48" />
      </CardHeader>
      <CardContent>
        <Skeleton className="h-10 w-full" />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page component
// ---------------------------------------------------------------------------

export default function ProjectDetailPage() {
  const params = useParams();
  const projectId = Number(params.id);
  const queryClient = useQueryClient();

  // Stage section refs for scroll-to
  const stageRefs = useRef<Record<string, HTMLElement | null>>({});

  const handleStageClick = useCallback((stage: ResearchStage) => {
    const el = document.getElementById(`stage-${stage}`);
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  // Queries
  const projectQ = useQuery({
    queryKey: ["project", projectId],
    queryFn: () => fetchProject(projectId),
    enabled: !isNaN(projectId),
  });

  const artifactsQ = useQuery({
    queryKey: ["project-artifacts", projectId],
    queryFn: () => fetchProjectArtifacts(projectId),
    enabled: !isNaN(projectId),
  });

  const eventsQ = useQuery({
    queryKey: ["project-events", projectId],
    queryFn: () => fetchProjectEvents(projectId),
    enabled: !isNaN(projectId),
  });

  const issuesQ = useQuery({
    queryKey: ["project-issues", projectId],
    queryFn: () => fetchProjectIssues(projectId),
    enabled: !isNaN(projectId),
  });

  const project: ProjectDetail | undefined = projectQ.data;
  const artifactsByStage = artifactsQ.data?.artifacts_by_stage ?? {};
  const events = eventsQ.data?.events ?? [];
  const issues = issuesQ.data?.issues ?? [];

  const handleRefresh = useCallback(() => {
    queryClient.invalidateQueries({ queryKey: ["project", projectId] });
    queryClient.invalidateQueries({ queryKey: ["project-artifacts", projectId] });
    queryClient.invalidateQueries({ queryKey: ["project-events", projectId] });
    queryClient.invalidateQueries({ queryKey: ["project-issues", projectId] });
  }, [queryClient, projectId]);

  return (
    <div className="space-y-6 p-6 pb-20 lg:p-8 lg:pb-20">
      {/* ---------------------------------------------------------------- */}
      {/* Back link + Header                                               */}
      {/* ---------------------------------------------------------------- */}
      <div className="space-y-4">
        <Link
          href="/projects"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          All Projects
        </Link>

        {projectQ.isPending ? (
          <HeaderSkeleton />
        ) : project ? (
          <div className="space-y-3">
            {/* Title row */}
            <div>
              <h1 className="text-2xl font-semibold tracking-tight">
                {project.name}
              </h1>
              <p className="mt-0.5 text-sm text-muted-foreground">
                {project.topic_name ?? `Topic #${project.topic_id}`}
                {project.description ? ` — ${project.description}` : ""}
              </p>
            </div>

            {/* Metadata badges */}
            <div className="flex flex-wrap items-center gap-2">
              {project.target_venue && (
                <Badge variant="outline" className="text-xs gap-1">
                  <MapPin className="size-3" />
                  {project.target_venue}
                </Badge>
              )}
              {project.deadline && (
                <Badge variant="outline" className="text-xs gap-1">
                  <Calendar className="size-3" />
                  {project.deadline}
                </Badge>
              )}
              {project.current_stage && (
                <Badge
                  variant="secondary"
                  className={cn(
                    "text-xs font-medium",
                    STAGE_BG_COLORS[project.current_stage],
                    STAGE_TEXT_COLORS[project.current_stage]
                  )}
                >
                  {STAGE_LABELS[project.current_stage]}
                  {project.stage_status ? ` / ${project.stage_status}` : ""}
                </Badge>
              )}
              {project.gate_status && (
                <GateStatusBadge status={project.gate_status} />
              )}
              {(project.blocking_issue_count ?? 0) > 0 && (
                <Badge className="bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300 text-xs gap-1">
                  <AlertTriangle className="size-3" />
                  {project.blocking_issue_count} blocking
                </Badge>
              )}
            </div>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">
            Project not found.
          </p>
        )}
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Pipeline visualization — centerpiece                             */}
      {/* ---------------------------------------------------------------- */}
      <Card>
        <CardHeader className="border-b">
          <CardTitle>Research Pipeline</CardTitle>
        </CardHeader>
        <CardContent className="py-6">
          {projectQ.isPending ? (
            <StagePipelineSkeleton />
          ) : project ? (
            <StagePipeline
              currentStage={project.current_stage}
              stageStatus={project.stage_status}
              artifactCounts={project.artifact_counts}
              onStageClick={handleStageClick}
            />
          ) : null}
        </CardContent>
      </Card>

      {/* ---------------------------------------------------------------- */}
      {/* Stage-specific operation panels                                   */}
      {/* ---------------------------------------------------------------- */}
      {project?.current_stage === "build" && (
        <PaperSearchPanel topicId={project.topic_id} />
      )}
      {project?.current_stage === "analyze" && (
        <AnalysisPanel topicId={project.topic_id} projectId={projectId} />
      )}

      {/* ---------------------------------------------------------------- */}
      {/* Main content: Stages + Activity sidebar                          */}
      {/* ---------------------------------------------------------------- */}
      <div className="grid gap-6 lg:grid-cols-[1fr_320px]">
        {/* Stage detail panels */}
        <div className="space-y-4">
          <h2 className="text-lg font-semibold tracking-tight">
            Stage Details
          </h2>
          {artifactsQ.isPending ? (
            <>
              <StagePanelSkeleton />
              <StagePanelSkeleton />
              <StagePanelSkeleton />
            </>
          ) : (
            RESEARCH_STAGES.map((stage) => (
              <StagePanel
                key={stage}
                stage={stage}
                artifacts={artifactsByStage[stage] ?? []}
                isCurrent={project?.current_stage === stage}
              />
            ))
          )}

          {/* ---------------------------------------------------------- */}
          {/* Review Issues                                               */}
          {/* ---------------------------------------------------------- */}
          <div className="space-y-3">
            <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
              <ShieldAlert className="size-4" />
              Review Issues
              {issues.length > 0 && (
                <span className="text-sm font-normal text-muted-foreground">
                  ({issues.length})
                </span>
              )}
            </h2>

            {issuesQ.isPending ? (
              <Card>
                <CardContent>
                  <div className="space-y-3">
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                    <Skeleton className="h-10 w-full" />
                  </div>
                </CardContent>
              </Card>
            ) : issues.length === 0 ? (
              <Card>
                <CardContent>
                  <p className="py-4 text-center text-sm text-muted-foreground">
                    No review issues recorded.
                  </p>
                </CardContent>
              </Card>
            ) : (
              <Card>
                <CardContent className="p-0">
                  <div className="divide-y divide-foreground/5">
                    {issues.map((issue) => (
                      <div
                        key={issue.id}
                        className="flex items-start gap-3 px-4 py-3"
                      >
                        <IssueStatusIcon status={issue.status} />
                        <div className="flex-1 min-w-0 space-y-1">
                          <div className="flex items-center gap-2 flex-wrap">
                            <SeverityBadge severity={issue.severity} />
                            <span className="text-xs text-muted-foreground">
                              {issue.category}
                            </span>
                            {issue.blocking && (
                              <Badge variant="destructive" className="text-[10px] h-4 px-1.5">
                                blocking
                              </Badge>
                            )}
                          </div>
                          <p className="text-sm">{issue.summary}</p>
                          {issue.recommended_action && (
                            <p className="text-xs text-muted-foreground">
                              Fix: {issue.recommended_action}
                            </p>
                          )}
                        </div>
                        <span className="shrink-0 text-xs text-muted-foreground tabular-nums">
                          {formatTimestamp(issue.created_at)}
                        </span>
                      </div>
                    ))}
                  </div>
                </CardContent>
              </Card>
            )}
          </div>
        </div>

        {/* Activity timeline (right sidebar) */}
        <div className="space-y-3">
          <h2 className="text-lg font-semibold tracking-tight flex items-center gap-2">
            <Clock className="size-4" />
            Activity
          </h2>

          {eventsQ.isPending ? (
            <Card>
              <CardContent>
                <div className="space-y-3">
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                  <Skeleton className="h-12 w-full" />
                </div>
              </CardContent>
            </Card>
          ) : events.length === 0 ? (
            <Card>
              <CardContent>
                <p className="py-4 text-center text-sm text-muted-foreground">
                  No events recorded yet.
                </p>
              </CardContent>
            </Card>
          ) : (
            <Card>
              <CardContent className="p-0">
                <div className="divide-y divide-foreground/5 max-h-[600px] overflow-y-auto">
                  {events.map((event) => (
                    <div key={event.id} className="px-4 py-3 space-y-1.5">
                      <div className="flex items-center gap-2 flex-wrap">
                        <EventTypeBadge type={event.event_type} />
                        {event.stage && (
                          <Badge
                            variant="secondary"
                            className={cn(
                              "text-[10px] h-4 px-1.5",
                              STAGE_BG_COLORS[event.stage],
                              STAGE_TEXT_COLORS[event.stage]
                            )}
                          >
                            {STAGE_LABELS[event.stage]}
                          </Badge>
                        )}
                      </div>
                      <div className="flex items-center justify-between gap-2">
                        <span className="text-xs text-muted-foreground">
                          {event.actor || "system"}
                        </span>
                        <span className="text-xs text-muted-foreground tabular-nums">
                          {formatTimestamp(event.created_at)}
                        </span>
                      </div>
                      {event.details &&
                        Object.keys(event.details).length > 0 && (
                          <p className="text-xs text-muted-foreground truncate">
                            {summarizeDetails(event.details)}
                          </p>
                        )}
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          )}
        </div>
      </div>

      {/* ---------------------------------------------------------------- */}
      {/* Fixed bottom action toolbar                                      */}
      {/* ---------------------------------------------------------------- */}
      {project && (
        <ActionToolbar
          projectId={projectId}
          currentStage={project.current_stage}
          stageStatus={project.stage_status}
          onRefresh={handleRefresh}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Gate status badge (inline helper)
// ---------------------------------------------------------------------------

function GateStatusBadge({ status }: { status: string }) {
  const lower = status.toLowerCase();
  if (lower === "pass" || lower === "passed" || lower === "approved") {
    return (
      <Badge className="bg-emerald-100 text-emerald-700 dark:bg-emerald-900/50 dark:text-emerald-300 text-xs gap-1">
        <CheckCircle2 className="size-3" />
        Gate: {status}
      </Badge>
    );
  }
  if (lower === "fail" || lower === "failed" || lower === "blocked") {
    return (
      <Badge className="bg-red-100 text-red-700 dark:bg-red-900/50 dark:text-red-300 text-xs gap-1">
        <XCircle className="size-3" />
        Gate: {status}
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="text-xs">
      Gate: {status}
    </Badge>
  );
}

// ---------------------------------------------------------------------------
// Summarize event details into one line
// ---------------------------------------------------------------------------

function summarizeDetails(details: Record<string, unknown>): string {
  const parts: string[] = [];
  for (const [key, val] of Object.entries(details)) {
    if (typeof val === "string") {
      parts.push(`${key}: ${val}`);
    } else if (typeof val === "number" || typeof val === "boolean") {
      parts.push(`${key}: ${String(val)}`);
    }
  }
  return parts.join(", ") || JSON.stringify(details).slice(0, 100);
}
