// ---------------------------------------------------------------------------
// Research Harness — typed API client
// Calls FastAPI backend at http://localhost:8000
// ---------------------------------------------------------------------------

import type {
  Domain,
  Topic,
  TopicDetail,
  Paper,
  PaperWithCard,
  Artifact,
  StageEvent,
  ReviewIssue,
  DashboardStats,
  ProvenanceSummary,
  PaginatedResponse,
  TopicArtifactsResponse,
  TopicEventsResponse,
  TopicIssuesResponse,
} from "./types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

// ---------------------------------------------------------------------------
// Generic fetcher
// ---------------------------------------------------------------------------

async function apiFetch<T>(path: string, init?: RequestInit): Promise<T> {
  const url = `${API_BASE}${path}`;
  const res = await fetch(url, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers,
    },
  });

  if (!res.ok) {
    const body = await res.text().catch(() => "");
    throw new Error(`API ${res.status}: ${res.statusText} — ${body}`);
  }

  return res.json() as Promise<T>;
}

// ---------------------------------------------------------------------------
// Domains
// ---------------------------------------------------------------------------

export function fetchDomains(): Promise<Domain[]> {
  return apiFetch<Domain[]>("/api/domains");
}

export function fetchDomain(domainId: number): Promise<Domain> {
  return apiFetch<Domain>(`/api/domains/${domainId}`);
}

export function createDomain(data: {
  name: string;
  description?: string;
}): Promise<Domain> {
  return apiFetch<Domain>("/api/domains", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

// ---------------------------------------------------------------------------
// Topics
// ---------------------------------------------------------------------------

export function fetchTopics(params?: {
  domain_id?: number;
}): Promise<Topic[]> {
  const sp = new URLSearchParams();
  if (params?.domain_id != null) sp.set("domain_id", String(params.domain_id));
  const qs = sp.toString();
  return apiFetch<Topic[]>(`/api/topics${qs ? `?${qs}` : ""}`);
}

export function fetchTopic(topicId: number): Promise<Topic> {
  return apiFetch<Topic>(`/api/topics/${topicId}`);
}

export function fetchTopicDetail(topicId: number): Promise<TopicDetail> {
  return apiFetch<TopicDetail>(`/api/topics/${topicId}`);
}

export function fetchTopicPapers(
  topicId: number,
  params?: { page?: number; page_size?: number; search?: string }
): Promise<PaginatedResponse<Paper>> {
  const sp = new URLSearchParams();
  if (params?.page != null) sp.set("page", String(params.page));
  if (params?.page_size != null) sp.set("page_size", String(params.page_size));
  if (params?.search) sp.set("search", params.search);
  const qs = sp.toString();
  return apiFetch<PaginatedResponse<Paper>>(
    `/api/topics/${topicId}/papers${qs ? `?${qs}` : ""}`
  );
}

export function fetchTopicArtifacts(
  topicId: number
): Promise<TopicArtifactsResponse> {
  return apiFetch<TopicArtifactsResponse>(
    `/api/topics/${topicId}/artifacts`
  );
}

export function fetchTopicEvents(
  topicId: number
): Promise<TopicEventsResponse> {
  return apiFetch<TopicEventsResponse>(
    `/api/topics/${topicId}/events`
  );
}

export function fetchTopicIssues(
  topicId: number
): Promise<TopicIssuesResponse> {
  return apiFetch<TopicIssuesResponse>(
    `/api/topics/${topicId}/issues`
  );
}

// ---------------------------------------------------------------------------
// Papers (global)
// ---------------------------------------------------------------------------

export async function fetchPapers(params?: {
  page?: number;
  page_size?: number;
  search?: string;
  topic_id?: number;
  sort?: string;
  order?: "asc" | "desc";
}): Promise<PaginatedResponse<Paper>> {
  const sp = new URLSearchParams();
  if (params?.page != null) sp.set("page", String(params.page));
  if (params?.page_size != null)
    sp.set("per_page", String(params.page_size));
  if (params?.search) sp.set("search", params.search);
  if (params?.topic_id != null) sp.set("topic_id", String(params.topic_id));
  if (params?.sort) sp.set("sort", params.sort);
  if (params?.order) sp.set("order", params.order);
  const qs = sp.toString();

  // Backend returns { data: Paper[], pagination: { page, per_page, total, total_pages } }
  const result = await apiFetch<{
    data: Paper[];
    pagination: { page: number; per_page: number; total: number; total_pages: number };
  }>(`/api/papers${qs ? `?${qs}` : ""}`);

  return {
    items: result.data,
    total: result.pagination.total,
    page: result.pagination.page,
    page_size: result.pagination.per_page,
  };
}

export function fetchPaper(paperId: number): Promise<PaperWithCard> {
  return apiFetch<PaperWithCard>(`/api/papers/${paperId}`);
}

// ---------------------------------------------------------------------------
// Dashboard / analytics
// ---------------------------------------------------------------------------

export function fetchDashboardStats(): Promise<DashboardStats> {
  return apiFetch<DashboardStats>("/api/stats");
}

export function fetchProvenanceSummary(
  topicId?: number
): Promise<ProvenanceSummary> {
  const path = topicId != null
    ? `/api/provenance/summary?topic_id=${topicId}`
    : "/api/provenance/summary";
  return apiFetch<ProvenanceSummary>(path);
}

// ---------------------------------------------------------------------------
// Write operations
// ---------------------------------------------------------------------------

export function createTopic(data: {
  name: string;
  description: string;
  domain_id?: number;
  target_venue?: string;
  deadline?: string;
}): Promise<Topic> {
  return apiFetch<Topic>("/api/topics", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function searchPapers(data: {
  query: string;
  topic_id?: number;
  max_results?: number;
}): Promise<unknown> {
  return apiFetch("/api/papers/search", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function ingestPaper(data: {
  source: string;
  topic_id: number;
  relevance?: string;
}): Promise<unknown> {
  return apiFetch("/api/papers/ingest", {
    method: "POST",
    body: JSON.stringify(data),
  });
}

export function advanceTopic(topicId: number): Promise<unknown> {
  return apiFetch(`/api/topics/${topicId}/advance`, {
    method: "POST",
    body: JSON.stringify({ actor: "web_ui" }),
  });
}

export function checkTopicGate(topicId: number): Promise<unknown> {
  return apiFetch(`/api/topics/${topicId}/gate`);
}

export function detectGaps(topicId: number, focus?: string): Promise<unknown> {
  return apiFetch(`/api/topics/${topicId}/gaps`, {
    method: "POST",
    body: JSON.stringify({ focus }),
  });
}

export function rankDirections(
  topicId: number,
  focus?: string
): Promise<unknown> {
  return apiFetch(`/api/topics/${topicId}/directions`, {
    method: "POST",
    body: JSON.stringify({ focus }),
  });
}
