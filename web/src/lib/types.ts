// ---------------------------------------------------------------------------
// Research Harness — shared TypeScript types
// These mirror the FastAPI backend models.
// ---------------------------------------------------------------------------

// -- Enums / union literals ------------------------------------------------

export type ResearchStage =
  | "init"
  | "build"
  | "analyze"
  | "propose"
  | "experiment"
  | "write";

export type GateType =
  | "approval_gate"
  | "coverage_gate"
  | "adversarial_gate"
  | "review_gate"
  | "integrity_gate"
  | "experiment_gate";

export type StageStatus =
  | "not_started"
  | "in_progress"
  | "blocked"
  | "completed"
  | "approved";

export type PaperRelevance = "high" | "medium" | "low";

export type ArtifactType =
  | "topic_frame"
  | "paper_pool"
  | "coverage_report"
  | "gap_analysis"
  | "evidence_matrix"
  | "direction_ranking"
  | "design_brief"
  | "algorithm_candidate"
  | "originality_check"
  | "research_proposal"
  | "experiment_result"
  | "writing_architecture"
  | "section_draft"
  | "review_report"
  | "adversarial_round"
  | "integrity_report"
  | "final_paper";

// -- Core entities ---------------------------------------------------------

export interface Domain {
  id: number;
  name: string;
  description: string | null;
  status: string;
  topic_count: number;
  created_at: string;
}

export interface Topic {
  id: number;
  name: string;
  description: string | null;
  domain_id: number | null;
  domain_name: string | null;
  paper_count: number;
  created_at: string;
}

export interface TopicDetail extends Topic {
  status: string;
  target_venue: string;
  deadline: string;
  contributions: string;
  current_stage: ResearchStage | null;
  stage_status: string | null;
  gate_status: string | null;
  mode: string | null;
  stop_before: string | null;
  blocking_issue_count: number;
  unresolved_issue_count: number;
  annotation_count: number;
  artifact_counts: Record<string, number>;
}

export interface Paper {
  id: number;
  title: string;
  authors: string | null;
  year: number | null;
  venue: string | null;
  arxiv_id: string | null;
  doi: string | null;
  abstract: string | null;
  pdf_path: string | null;
  relevance: PaperRelevance | null;
  source: string | null;
  ingested_at: string;
  topic_id: number | null;
  topic_name: string | null;
}

export interface PaperCard {
  paper_id: number;
  summary: string | null;
  contributions: string | null;
  methods: string | null;
  limitations: string | null;
  created_at: string;
}

export interface PaperWithCard extends Paper {
  card: PaperCard | null;
}

export interface ReviewIssue {
  id: number;
  topic_id: number;
  review_type: string;
  severity: "critical" | "high" | "medium" | "low";
  category: string;
  summary: string;
  details: string | null;
  recommended_action: string | null;
  status: "open" | "in_progress" | "resolved" | "wontfix";
  blocking: boolean;
  created_at: string;
  updated_at: string | null;
}

export interface TopicArtifactsResponse {
  topic_id: number;
  artifacts_by_stage: Record<string, Artifact[]>;
}

export interface TopicEventsResponse {
  topic_id: number;
  events: StageEvent[];
}

export interface TopicIssuesResponse {
  topic_id: number;
  issues: ReviewIssue[];
}

export interface Artifact {
  id: number;
  topic_id: number;
  stage: ResearchStage;
  artifact_type: ArtifactType | string;
  title: string | null;
  payload: Record<string, unknown> | null;
  is_stale: boolean;
  stale_reason: string | null;
  created_at: string;
}

export interface OrchestratorRun {
  id: number;
  topic_id: number;
  current_stage: ResearchStage;
  mode: string;
  stop_before: string | null;
  started_at: string;
  updated_at: string;
}

export interface StageEvent {
  id: number;
  topic_id: number;
  stage: ResearchStage;
  event_type: "advance" | "gate_check" | "artifact_record" | "decision";
  actor: string;
  details: Record<string, unknown> | null;
  created_at: string;
}

// -- Analytics / dashboard -------------------------------------------------

export interface ProvenanceSummary {
  total_calls: number;
  total_cost_usd: number;
  total_prompt_tokens: number;
  total_completion_tokens: number;
  by_backend: Record<
    string,
    {
      calls: number;
      cost_usd: number;
      prompt_tokens: number;
      completion_tokens: number;
    }
  >;
}

export interface DashboardStats {
  total_papers: number;
  total_domains: number;
  total_topics: number;
  total_artifacts: number;
  total_provenance_records: number;
  papers_with_pdf: number;
  recent_papers: Array<Record<string, unknown>>;
  recent_events: Array<Record<string, unknown>>;
}

// -- Stage metadata (for UI rendering) -------------------------------------

export const RESEARCH_STAGES: readonly ResearchStage[] = [
  "init",
  "build",
  "analyze",
  "propose",
  "experiment",
  "write",
] as const;

export const STAGE_LABELS: Record<ResearchStage, string> = {
  init: "Init",
  build: "Build",
  analyze: "Analyze",
  propose: "Propose",
  experiment: "Experiment",
  write: "Write",
};

export const STAGE_COLORS: Record<ResearchStage, string> = {
  init: "bg-slate-500",
  build: "bg-blue-500",
  analyze: "bg-violet-500",
  propose: "bg-amber-500",
  experiment: "bg-emerald-500",
  write: "bg-rose-500",
};

export const STAGE_TEXT_COLORS: Record<ResearchStage, string> = {
  init: "text-slate-600 dark:text-slate-400",
  build: "text-blue-600 dark:text-blue-400",
  analyze: "text-violet-600 dark:text-violet-400",
  propose: "text-amber-600 dark:text-amber-400",
  experiment: "text-emerald-600 dark:text-emerald-400",
  write: "text-rose-600 dark:text-rose-400",
};

export const STAGE_BG_COLORS: Record<ResearchStage, string> = {
  init: "bg-slate-100 dark:bg-slate-900",
  build: "bg-blue-100 dark:bg-blue-900",
  analyze: "bg-violet-100 dark:bg-violet-900",
  propose: "bg-amber-100 dark:bg-amber-900",
  experiment: "bg-emerald-100 dark:bg-emerald-900",
  write: "bg-rose-100 dark:bg-rose-900",
};

export const STAGE_DESCRIPTIONS: Record<ResearchStage, string> = {
  init: "Environment sensing, topic framing, seed papers",
  build: "Literature retrieval, citation expansion, PDF acquisition",
  analyze: "Claim extraction, gap detection, direction ranking",
  propose: "Adversarial review, study design, algorithm design",
  experiment: "Code generation, sandbox execution, metric evaluation",
  write: "Section drafting, review loop, paper compilation",
};

export const STAGE_GATE_TYPES: Record<ResearchStage, GateType> = {
  init: "approval_gate",
  build: "coverage_gate",
  analyze: "approval_gate",
  propose: "adversarial_gate",
  experiment: "experiment_gate",
  write: "review_gate",
};

export const STAGE_ICONS: Record<ResearchStage, string> = {
  init: "Compass",
  build: "Library",
  analyze: "Search",
  propose: "Lightbulb",
  experiment: "FlaskConical",
  write: "PenTool",
};

// -- API response wrappers -------------------------------------------------

export interface PaginatedResponse<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}
