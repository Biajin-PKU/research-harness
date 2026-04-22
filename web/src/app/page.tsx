"use client";

import { useQuery } from "@tanstack/react-query";
import {
  FileText,
  Globe,
  BookOpen,
  DollarSign,
} from "lucide-react";
import Link from "next/link";
import { fetchDashboardStats, fetchTopics } from "@/lib/api";
import {
  RESEARCH_STAGES,
  STAGE_LABELS,
  STAGE_COLORS,
  type DashboardStats,
  type Topic,
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
// Topic card
// ---------------------------------------------------------------------------

function TopicCard({ topic }: { topic: Topic }) {
  return (
    <Link href={`/topics/${topic.id}`} className="block">
      <Card className="transition-shadow hover:ring-2 hover:ring-blue-500/20">
        <CardHeader>
          <CardTitle>{topic.name}</CardTitle>
          <CardDescription className="truncate">
            {topic.domain_name ?? "No domain"}
          </CardDescription>
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs">
              {topic.paper_count} paper{topic.paper_count !== 1 ? "s" : ""}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            Created {formatRelative(topic.created_at)}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

function TopicCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-32" />
        <Skeleton className="h-4 w-48" />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-16 rounded-full" />
        </div>
        <Skeleton className="h-3 w-24" />
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

  const topicsQuery = useQuery({
    queryKey: ["topics"],
    queryFn: () => fetchTopics(),
  });

  const stats: DashboardStats | undefined = statsQuery.data;

  return (
    <div className="space-y-8 p-6 lg:p-8">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Dashboard</h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Overview of your research domains, topics, and paper library.
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
              label="Domains"
              value={stats.total_domains}
              icon={Globe}
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

      {/* Topics grid */}
      <div>
        <h2 className="mb-4 text-lg font-semibold tracking-tight">
          Topics
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {topicsQuery.isPending ? (
            <>
              <TopicCardSkeleton />
              <TopicCardSkeleton />
              <TopicCardSkeleton />
              <TopicCardSkeleton />
              <TopicCardSkeleton />
              <TopicCardSkeleton />
            </>
          ) : topicsQuery.data?.length ? (
            topicsQuery.data.map((topic) => (
              <TopicCard key={topic.id} topic={topic} />
            ))
          ) : (
            <p className="col-span-full text-sm text-muted-foreground">
              No topics found. Create one to get started.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
