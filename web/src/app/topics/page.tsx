"use client";

import { useQuery } from "@tanstack/react-query";
import { BookOpen, Plus } from "lucide-react";
import Link from "next/link";
import { fetchTopics } from "@/lib/api";
import {
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
import { Button } from "@/components/ui/button";
import { Skeleton } from "@/components/ui/skeleton";

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
            {topic.domain_name ? topic.domain_name : "No domain"}
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
// Page
// ---------------------------------------------------------------------------

export default function TopicsPage() {
  const { data: topics, isPending, error } = useQuery({
    queryKey: ["topics"],
    queryFn: () => fetchTopics(),
  });

  return (
    <div className="space-y-6 p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-emerald-600">
            <BookOpen className="size-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Topics</h1>
            <p className="text-sm text-muted-foreground">
              All research topics and their workflow status.
            </p>
          </div>
        </div>
        <Button size="sm" render={<Link href="/topics/new" />}>
          <Plus className="size-4" />
          New Topic
        </Button>
      </div>

      {/* Grid */}
      <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {isPending ? (
          <>
            <TopicCardSkeleton />
            <TopicCardSkeleton />
            <TopicCardSkeleton />
            <TopicCardSkeleton />
            <TopicCardSkeleton />
            <TopicCardSkeleton />
          </>
        ) : error ? (
          <p className="col-span-full text-sm text-muted-foreground">
            Failed to load topics.
          </p>
        ) : topics?.length ? (
          topics.map((topic) => (
            <TopicCard key={topic.id} topic={topic} />
          ))
        ) : (
          <p className="col-span-full text-sm text-muted-foreground">
            No topics found. Create one to get started.
          </p>
        )}
      </div>
    </div>
  );
}
