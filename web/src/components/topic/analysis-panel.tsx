"use client";

import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Loader2,
  Crosshair,
  TrendingUp,
  MessageSquareQuote,
  AlertCircle,
  CheckCircle2,
  Sparkles,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";

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

async function detectGaps(
  topicId: number,
  params: { focus?: string }
): Promise<WriteResponse> {
  const res = await fetch(`${API_BASE}/api/topics/${topicId}/gaps`, {
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

async function rankDirections(
  topicId: number,
  params: { focus?: string }
): Promise<WriteResponse> {
  const res = await fetch(`${API_BASE}/api/topics/${topicId}/directions`, {
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

async function extractClaims(
  topicId: number,
  params: { paper_ids: number[]; focus?: string }
): Promise<WriteResponse> {
  const res = await fetch(`${API_BASE}/api/topics/${topicId}/claims`, {
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
// Shared inline feedback
// ---------------------------------------------------------------------------

function InlineFeedback({
  type,
  message,
  onDismiss,
}: {
  type: "success" | "error";
  message: string;
  onDismiss: () => void;
}) {
  return (
    <div
      className={cn(
        "flex items-center gap-2 rounded-md px-3 py-2 text-sm",
        type === "success"
          ? "bg-emerald-50 text-emerald-700 dark:bg-emerald-900/20 dark:text-emerald-300"
          : "bg-red-50 text-red-700 dark:bg-red-900/20 dark:text-red-300"
      )}
    >
      {type === "success" ? (
        <CheckCircle2 className="size-4 shrink-0" />
      ) : (
        <AlertCircle className="size-4 shrink-0" />
      )}
      <span className="flex-1">{message}</span>
      <button
        type="button"
        className="text-xs underline opacity-60 hover:opacity-100"
        onClick={onDismiss}
      >
        dismiss
      </button>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Typed output renderers
// ---------------------------------------------------------------------------

interface GapItem {
  gap: string;
  description?: string;
  severity?: string;
  evidence?: string;
}

interface DirectionItem {
  direction: string;
  novelty?: number;
  feasibility?: number;
  impact?: number;
  score?: number;
  rationale?: string;
}

interface ClaimItem {
  claim: string;
  paper_id?: number;
  paper_title?: string;
  type?: string;
  confidence?: string;
}

function renderGaps(output: unknown): GapItem[] {
  if (Array.isArray(output)) return output as GapItem[];
  if (output && typeof output === "object" && "gaps" in output) {
    return (output as { gaps: GapItem[] }).gaps;
  }
  return [];
}

function renderDirections(output: unknown): DirectionItem[] {
  if (Array.isArray(output)) return output as DirectionItem[];
  if (output && typeof output === "object" && "directions" in output) {
    return (output as { directions: DirectionItem[] }).directions;
  }
  return [];
}

function renderClaims(output: unknown): ClaimItem[] {
  if (Array.isArray(output)) return output as ClaimItem[];
  if (output && typeof output === "object" && "claims" in output) {
    return (output as { claims: ClaimItem[] }).claims;
  }
  return [];
}

// ---------------------------------------------------------------------------
// Gaps tab content
// ---------------------------------------------------------------------------

function GapsTab({ topicId }: { topicId: number }) {
  const [focus, setFocus] = useState("");
  const [gaps, setGaps] = useState<GapItem[]>([]);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      detectGaps(topicId, { focus: focus.trim() || undefined }),
    onSuccess: (data) => {
      setGaps(renderGaps(data.output));
      setFeedback({
        type: "success",
        message: data.summary || "Gap detection complete",
      });
    },
    onError: (err: Error) => {
      setFeedback({ type: "error", message: err.message });
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Input
          placeholder="Focus area (optional)"
          value={focus}
          onChange={(e) => setFocus(e.target.value)}
          disabled={mut.isPending}
          className="flex-1"
        />
        <Button onClick={() => mut.mutate()} disabled={mut.isPending}>
          {mut.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <Crosshair className="size-4" />
          )}
          Detect Gaps
        </Button>
      </div>

      {feedback && (
        <InlineFeedback
          type={feedback.type}
          message={feedback.message}
          onDismiss={() => setFeedback(null)}
        />
      )}

      {gaps.length > 0 && (
        <div className="space-y-2">
          {gaps.map((gap, idx) => (
            <div
              key={idx}
              className="rounded-md border border-foreground/5 p-3 space-y-1"
            >
              <div className="flex items-start gap-2">
                <span className="text-xs font-mono text-muted-foreground mt-0.5 shrink-0 tabular-nums">
                  #{idx + 1}
                </span>
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium">{gap.gap}</p>
                  {gap.description && (
                    <p className="text-xs text-muted-foreground mt-1">
                      {gap.description}
                    </p>
                  )}
                </div>
                {gap.severity && (
                  <Badge
                    variant="secondary"
                    className="text-[10px] h-4 px-1.5 shrink-0"
                  >
                    {gap.severity}
                  </Badge>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {mut.isSuccess && gaps.length === 0 && (
        <p className="py-4 text-center text-sm text-muted-foreground">
          No gaps detected.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Directions tab content
// ---------------------------------------------------------------------------

function DirectionsTab({ topicId }: { topicId: number }) {
  const [focus, setFocus] = useState("");
  const [directions, setDirections] = useState<DirectionItem[]>([]);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const mut = useMutation({
    mutationFn: () =>
      rankDirections(topicId, { focus: focus.trim() || undefined }),
    onSuccess: (data) => {
      setDirections(renderDirections(data.output));
      setFeedback({
        type: "success",
        message: data.summary || "Direction ranking complete",
      });
    },
    onError: (err: Error) => {
      setFeedback({ type: "error", message: err.message });
    },
  });

  return (
    <div className="space-y-4">
      <div className="flex gap-2">
        <Input
          placeholder="Focus area (optional)"
          value={focus}
          onChange={(e) => setFocus(e.target.value)}
          disabled={mut.isPending}
          className="flex-1"
        />
        <Button onClick={() => mut.mutate()} disabled={mut.isPending}>
          {mut.isPending ? (
            <Loader2 className="size-4 animate-spin" />
          ) : (
            <TrendingUp className="size-4" />
          )}
          Rank Directions
        </Button>
      </div>

      {feedback && (
        <InlineFeedback
          type={feedback.type}
          message={feedback.message}
          onDismiss={() => setFeedback(null)}
        />
      )}

      {directions.length > 0 && (
        <div className="space-y-2">
          {directions.map((dir, idx) => (
            <div
              key={idx}
              className="rounded-md border border-foreground/5 p-3 space-y-2"
            >
              <div className="flex items-start gap-2">
                <span className="text-xs font-mono text-muted-foreground mt-0.5 shrink-0 tabular-nums">
                  #{idx + 1}
                </span>
                <p className="flex-1 text-sm font-medium">{dir.direction}</p>
                {dir.score != null && (
                  <Badge
                    variant="secondary"
                    className="text-[10px] h-4 px-1.5 shrink-0 tabular-nums"
                  >
                    {dir.score.toFixed(2)}
                  </Badge>
                )}
              </div>

              {/* Score breakdown */}
              {(dir.novelty != null ||
                dir.feasibility != null ||
                dir.impact != null) && (
                <div className="flex gap-3 ml-6">
                  {dir.novelty != null && (
                    <ScoreChip label="Novelty" value={dir.novelty} />
                  )}
                  {dir.feasibility != null && (
                    <ScoreChip label="Feasibility" value={dir.feasibility} />
                  )}
                  {dir.impact != null && (
                    <ScoreChip label="Impact" value={dir.impact} />
                  )}
                </div>
              )}

              {dir.rationale && (
                <p className="ml-6 text-xs text-muted-foreground">
                  {dir.rationale}
                </p>
              )}
            </div>
          ))}
        </div>
      )}

      {mut.isSuccess && directions.length === 0 && (
        <p className="py-4 text-center text-sm text-muted-foreground">
          No directions ranked.
        </p>
      )}
    </div>
  );
}

function ScoreChip({ label, value }: { label: string; value: number }) {
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-muted-foreground">
      <span>{label}:</span>
      <span className="font-medium tabular-nums text-foreground">
        {typeof value === "number" ? value.toFixed(1) : value}
      </span>
    </span>
  );
}

// ---------------------------------------------------------------------------
// Claims tab content
// ---------------------------------------------------------------------------

function ClaimsTab({ topicId }: { topicId: number }) {
  const [paperIdsStr, setPaperIdsStr] = useState("");
  const [focus, setFocus] = useState("");
  const [claims, setClaims] = useState<ClaimItem[]>([]);
  const [feedback, setFeedback] = useState<{
    type: "success" | "error";
    message: string;
  } | null>(null);

  const parsePaperIds = (): number[] => {
    return paperIdsStr
      .split(/[,\s]+/)
      .map((s) => parseInt(s.trim(), 10))
      .filter((n) => !isNaN(n));
  };

  const mut = useMutation({
    mutationFn: () =>
      extractClaims(topicId, {
        paper_ids: parsePaperIds(),
        focus: focus.trim() || undefined,
      }),
    onSuccess: (data) => {
      setClaims(renderClaims(data.output));
      setFeedback({
        type: "success",
        message: data.summary || "Claim extraction complete",
      });
    },
    onError: (err: Error) => {
      setFeedback({ type: "error", message: err.message });
    },
  });

  const validIds = parsePaperIds().length > 0;

  return (
    <div className="space-y-4">
      <div className="space-y-2">
        <Input
          placeholder="Paper IDs (comma-separated, e.g. 12, 34, 56)"
          value={paperIdsStr}
          onChange={(e) => setPaperIdsStr(e.target.value)}
          disabled={mut.isPending}
        />
        <div className="flex gap-2">
          <Input
            placeholder="Focus area (optional)"
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
            disabled={mut.isPending}
            className="flex-1"
          />
          <Button
            onClick={() => mut.mutate()}
            disabled={mut.isPending || !validIds}
          >
            {mut.isPending ? (
              <Loader2 className="size-4 animate-spin" />
            ) : (
              <MessageSquareQuote className="size-4" />
            )}
            Extract Claims
          </Button>
        </div>
      </div>

      {feedback && (
        <InlineFeedback
          type={feedback.type}
          message={feedback.message}
          onDismiss={() => setFeedback(null)}
        />
      )}

      {claims.length > 0 && (
        <div className="space-y-2">
          {claims.map((claim, idx) => (
            <div
              key={idx}
              className="rounded-md border border-foreground/5 p-3 space-y-1"
            >
              <div className="flex items-start gap-2">
                <Sparkles className="size-3.5 shrink-0 mt-0.5 text-amber-500" />
                <p className="flex-1 text-sm">{claim.claim}</p>
              </div>
              <div className="flex flex-wrap gap-1.5 ml-5">
                {claim.type && (
                  <Badge
                    variant="secondary"
                    className="text-[10px] h-4 px-1.5"
                  >
                    {claim.type}
                  </Badge>
                )}
                {claim.confidence && (
                  <Badge
                    variant="outline"
                    className="text-[10px] h-4 px-1.5"
                  >
                    {claim.confidence}
                  </Badge>
                )}
                {claim.paper_title && (
                  <span className="text-[10px] text-muted-foreground truncate max-w-[250px]">
                    from: {claim.paper_title}
                  </span>
                )}
              </div>
            </div>
          ))}
        </div>
      )}

      {mut.isSuccess && claims.length === 0 && (
        <p className="py-4 text-center text-sm text-muted-foreground">
          No claims extracted.
        </p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main component
// ---------------------------------------------------------------------------

interface AnalysisPanelProps {
  topicId: number;
}

export function AnalysisPanel({ topicId }: AnalysisPanelProps) {
  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm">
          <Crosshair className="size-4" />
          Literature Analysis
        </CardTitle>
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="gaps">
          <TabsList>
            <TabsTrigger value="gaps">
              <Crosshair className="size-3.5" />
              Gaps
            </TabsTrigger>
            <TabsTrigger value="directions">
              <TrendingUp className="size-3.5" />
              Directions
            </TabsTrigger>
            <TabsTrigger value="claims">
              <MessageSquareQuote className="size-3.5" />
              Claims
            </TabsTrigger>
          </TabsList>

          <TabsContent value="gaps" className="pt-4">
            <GapsTab topicId={topicId} />
          </TabsContent>

          <TabsContent value="directions" className="pt-4">
            <DirectionsTab topicId={topicId} />
          </TabsContent>

          <TabsContent value="claims" className="pt-4">
            <ClaimsTab topicId={topicId} />
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
