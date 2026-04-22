"use client";

import {
  Compass,
  Library,
  Search,
  Lightbulb,
  FlaskConical,
  PenTool,
  Check,
} from "lucide-react";
import {
  RESEARCH_STAGES,
  STAGE_LABELS,
  STAGE_DESCRIPTIONS,
  type ResearchStage,
} from "@/lib/types";
import { cn } from "@/lib/utils";
import {
  Tooltip,
  TooltipTrigger,
  TooltipContent,
  TooltipProvider,
} from "@/components/ui/tooltip";

// ---------------------------------------------------------------------------
// Stage icon mapping
// ---------------------------------------------------------------------------

const STAGE_ICON_MAP: Record<
  ResearchStage,
  React.ComponentType<{ className?: string }>
> = {
  init: Compass,
  build: Library,
  analyze: Search,
  propose: Lightbulb,
  experiment: FlaskConical,
  write: PenTool,
};

// Stage-specific ring/fill colors for the circle indicators
const STAGE_RING_COLORS: Record<ResearchStage, string> = {
  init: "border-slate-500",
  build: "border-blue-500",
  analyze: "border-violet-500",
  propose: "border-amber-500",
  experiment: "border-emerald-500",
  write: "border-rose-500",
};

const STAGE_FILL_COLORS: Record<ResearchStage, string> = {
  init: "bg-slate-500",
  build: "bg-blue-500",
  analyze: "bg-violet-500",
  propose: "bg-amber-500",
  experiment: "bg-emerald-500",
  write: "bg-rose-500",
};

const STAGE_LIGHT_BG: Record<ResearchStage, string> = {
  init: "bg-slate-100 dark:bg-slate-800",
  build: "bg-blue-100 dark:bg-blue-900",
  analyze: "bg-violet-100 dark:bg-violet-900",
  propose: "bg-amber-100 dark:bg-amber-900",
  experiment: "bg-emerald-100 dark:bg-emerald-900",
  write: "bg-rose-100 dark:bg-rose-900",
};

const STAGE_ICON_ACTIVE: Record<ResearchStage, string> = {
  init: "text-slate-600 dark:text-slate-300",
  build: "text-blue-600 dark:text-blue-300",
  analyze: "text-violet-600 dark:text-violet-300",
  propose: "text-amber-600 dark:text-amber-300",
  experiment: "text-emerald-600 dark:text-emerald-300",
  write: "text-rose-600 dark:text-rose-300",
};

// ---------------------------------------------------------------------------
// Helper: determine each stage's visual status
// ---------------------------------------------------------------------------

type StageVisual = "completed" | "current" | "future";

function resolveStageVisuals(
  currentStage: ResearchStage | null,
  stageStatus: string | null
): Record<ResearchStage, StageVisual> {
  const currentIdx = currentStage
    ? RESEARCH_STAGES.indexOf(currentStage)
    : -1;

  const result: Record<string, StageVisual> = {};
  for (let i = 0; i < RESEARCH_STAGES.length; i++) {
    const s = RESEARCH_STAGES[i];
    if (currentIdx < 0) {
      // No active stage
      result[s] = "future";
    } else if (i < currentIdx) {
      result[s] = "completed";
    } else if (i === currentIdx) {
      // If the current stage is "completed" or "approved", treat it as completed
      if (stageStatus === "completed" || stageStatus === "approved") {
        result[s] = "completed";
      } else {
        result[s] = "current";
      }
    } else {
      result[s] = "future";
    }
  }
  return result as Record<ResearchStage, StageVisual>;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface StagePipelineProps {
  currentStage: ResearchStage | null;
  stageStatus: string | null;
  artifactCounts?: Record<string, number>;
  onStageClick?: (stage: ResearchStage) => void;
  className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function StagePipeline({
  currentStage,
  stageStatus,
  artifactCounts = {},
  onStageClick,
  className,
}: StagePipelineProps) {
  const visuals = resolveStageVisuals(currentStage, stageStatus);

  return (
    <TooltipProvider>
      <div className={cn("w-full", className)}>
        {/* Pipeline row */}
        <div className="flex items-center">
          {RESEARCH_STAGES.map((stage, i) => {
            const Icon = STAGE_ICON_MAP[stage];
            const visual = visuals[stage];
            const count = artifactCounts[stage] ?? 0;
            const isLast = i === RESEARCH_STAGES.length - 1;

            return (
              <div key={stage} className="flex flex-1 items-center">
                {/* Stage node */}
                <Tooltip>
                  <TooltipTrigger
                    className={cn(
                      "group relative flex flex-col items-center",
                      onStageClick && "cursor-pointer"
                    )}
                    onClick={() => onStageClick?.(stage)}
                  >
                    {/* Circle indicator */}
                    <div
                      className={cn(
                        "relative flex size-10 items-center justify-center rounded-full border-2 transition-all",
                        visual === "completed" && [
                          STAGE_FILL_COLORS[stage],
                          "border-transparent",
                        ],
                        visual === "current" && [
                          STAGE_LIGHT_BG[stage],
                          STAGE_RING_COLORS[stage],
                          "animate-pulse",
                        ],
                        visual === "future" && [
                          "border-slate-300 bg-white dark:border-slate-600 dark:bg-slate-800",
                        ]
                      )}
                    >
                      {visual === "completed" ? (
                        <Check className="size-4 text-white" />
                      ) : (
                        <Icon
                          className={cn(
                            "size-4",
                            visual === "current"
                              ? STAGE_ICON_ACTIVE[stage]
                              : "text-slate-400 dark:text-slate-500"
                          )}
                        />
                      )}
                    </div>

                    {/* Label */}
                    <span
                      className={cn(
                        "mt-1.5 text-xs font-medium",
                        visual === "completed"
                          ? "text-foreground"
                          : visual === "current"
                            ? "text-foreground font-semibold"
                            : "text-muted-foreground"
                      )}
                    >
                      {STAGE_LABELS[stage]}
                    </span>

                    {/* Artifact count badge */}
                    {count > 0 && (
                      <span
                        className={cn(
                          "absolute -right-1.5 -top-1.5 flex size-4.5 items-center justify-center rounded-full text-[10px] font-semibold text-white",
                          STAGE_FILL_COLORS[stage]
                        )}
                      >
                        {count > 9 ? "9+" : count}
                      </span>
                    )}
                  </TooltipTrigger>
                  <TooltipContent>
                    <p className="font-medium">{STAGE_LABELS[stage]}</p>
                    <p className="text-xs opacity-80">
                      {STAGE_DESCRIPTIONS[stage]}
                    </p>
                    {count > 0 && (
                      <p className="mt-0.5 text-xs opacity-70">
                        {count} artifact{count !== 1 ? "s" : ""}
                      </p>
                    )}
                  </TooltipContent>
                </Tooltip>

                {/* Connector line (not after last stage) */}
                {!isLast && (
                  <div className="mx-1 h-0.5 flex-1">
                    <div
                      className={cn(
                        "h-full rounded-full transition-colors",
                        visuals[RESEARCH_STAGES[i + 1]] === "completed" ||
                          visual === "completed"
                          ? STAGE_FILL_COLORS[stage]
                          : "bg-slate-200 dark:bg-slate-700"
                      )}
                    />
                  </div>
                )}
              </div>
            );
          })}
        </div>
      </div>
    </TooltipProvider>
  );
}

// ---------------------------------------------------------------------------
// Skeleton for loading state
// ---------------------------------------------------------------------------

export function StagePipelineSkeleton() {
  return (
    <div className="flex items-center">
      {RESEARCH_STAGES.map((stage, i) => (
        <div key={stage} className="flex flex-1 items-center">
          <div className="flex flex-col items-center">
            <div className="size-10 animate-pulse rounded-full bg-muted" />
            <div className="mt-1.5 h-3 w-12 animate-pulse rounded bg-muted" />
          </div>
          {i < RESEARCH_STAGES.length - 1 && (
            <div className="mx-1 h-0.5 flex-1 rounded-full bg-muted" />
          )}
        </div>
      ))}
    </div>
  );
}
