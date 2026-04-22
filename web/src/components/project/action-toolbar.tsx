"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Loader2,
  ChevronRight,
  ShieldCheck,
  CheckCircle2,
  AlertCircle,
  XCircle,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import type { ResearchStage } from "@/lib/types";
import {
  STAGE_LABELS,
  STAGE_TEXT_COLORS,
  STAGE_BG_COLORS,
} from "@/lib/types";

// ---------------------------------------------------------------------------
// API stubs — will be replaced when api.ts adds these functions
// ---------------------------------------------------------------------------

interface WriteResponse {
  status: string;
  summary: string;
  output: unknown;
  next_actions: string[];
  artifacts: unknown[];
  recovery_hint: string | null;
}

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function advanceProject(
  projectId: number,
  params?: { actor?: string }
): Promise<WriteResponse> {
  const res = await fetch(`${API_BASE}/api/projects/${projectId}/advance`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(params ?? {}),
  });
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

async function checkGate(projectId: number): Promise<WriteResponse> {
  const res = await fetch(
    `${API_BASE}/api/projects/${projectId}/gate-check`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }
  );
  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${body}`);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

interface ActionToolbarProps {
  projectId: number;
  currentStage: ResearchStage | null;
  stageStatus: string | null;
  onRefresh: () => void;
}

export function ActionToolbar({
  projectId,
  currentStage,
  stageStatus,
  onRefresh,
}: ActionToolbarProps) {
  const [feedback, setFeedback] = useState<{
    type: "success" | "error" | "info";
    message: string;
  } | null>(null);

  // Auto-dismiss feedback after 8 seconds
  const showFeedback = (
    type: "success" | "error" | "info",
    message: string
  ) => {
    setFeedback({ type, message });
    setTimeout(() => setFeedback(null), 8000);
  };

  // Advance mutation
  const advanceMut = useMutation({
    mutationFn: () => advanceProject(projectId, { actor: "web_ui" }),
    onSuccess: (data) => {
      showFeedback(
        data.status === "error" ? "error" : "success",
        data.summary || "Stage advanced"
      );
      onRefresh();
    },
    onError: (err: Error) => {
      showFeedback("error", err.message);
    },
  });

  // Gate check mutation
  const gateMut = useMutation({
    mutationFn: () => checkGate(projectId),
    onSuccess: (data) => {
      const gateStatus =
        typeof data.output === "object" && data.output !== null
          ? (data.output as Record<string, unknown>).gate_status
          : null;
      const type =
        gateStatus === "pass" || gateStatus === "passed"
          ? "success"
          : gateStatus === "fail" || gateStatus === "blocked"
            ? "error"
            : "info";
      showFeedback(type, data.summary || `Gate: ${gateStatus ?? "checked"}`);
      onRefresh();
    },
    onError: (err: Error) => {
      showFeedback("error", err.message);
    },
  });

  const isLoading = advanceMut.isPending || gateMut.isPending;

  return (
    <div className="fixed bottom-0 inset-x-0 z-40 border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/80">
      <div className="mx-auto flex max-w-screen-xl items-center justify-between gap-4 px-6 py-3">
        {/* Left: current stage display */}
        <div className="flex items-center gap-3">
          {currentStage ? (
            <Badge
              variant="secondary"
              className={cn(
                "text-xs font-medium",
                STAGE_BG_COLORS[currentStage],
                STAGE_TEXT_COLORS[currentStage]
              )}
            >
              {STAGE_LABELS[currentStage]}
            </Badge>
          ) : (
            <Badge variant="secondary" className="text-xs">
              No stage
            </Badge>
          )}
          {stageStatus && (
            <span className="text-xs text-muted-foreground">
              {stageStatus}
            </span>
          )}
        </div>

        {/* Center: feedback message */}
        {feedback && (
          <div
            className={cn(
              "flex items-center gap-2 rounded-md px-3 py-1.5 text-sm max-w-lg truncate",
              feedback.type === "success" &&
                "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300",
              feedback.type === "error" &&
                "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300",
              feedback.type === "info" &&
                "bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-300"
            )}
          >
            {feedback.type === "success" && (
              <CheckCircle2 className="size-3.5 shrink-0" />
            )}
            {feedback.type === "error" && (
              <XCircle className="size-3.5 shrink-0" />
            )}
            {feedback.type === "info" && (
              <AlertCircle className="size-3.5 shrink-0" />
            )}
            <span className="truncate">{feedback.message}</span>
          </div>
        )}

        {/* Right: action buttons */}
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            onClick={() => gateMut.mutate()}
            disabled={isLoading}
          >
            {gateMut.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <ShieldCheck className="size-3.5" />
            )}
            Check Gate
          </Button>

          <Button
            size="sm"
            onClick={() => advanceMut.mutate()}
            disabled={isLoading}
          >
            {advanceMut.isPending ? (
              <Loader2 className="size-3.5 animate-spin" />
            ) : (
              <ChevronRight className="size-3.5" />
            )}
            Advance Stage
          </Button>
        </div>
      </div>
    </div>
  );
}
