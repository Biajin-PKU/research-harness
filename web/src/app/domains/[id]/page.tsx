"use client";

import { useParams } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import { ArrowLeft, Globe, Plus } from "lucide-react";
import Link from "next/link";
import { fetchDomain, fetchTopics } from "@/lib/api";
import type { Topic } from "@/lib/types";
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
// Topic card (within domain context)
// ---------------------------------------------------------------------------

function TopicCard({ topic }: { topic: Topic }) {
  return (
    <Link href={`/topics/${topic.id}`} className="block">
      <Card className="transition-shadow hover:ring-2 hover:ring-blue-500/20">
        <CardHeader>
          <CardTitle>{topic.name}</CardTitle>
          {topic.description && (
            <CardDescription className="truncate">
              {topic.description}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent>
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs">
              {topic.paper_count} paper{topic.paper_count !== 1 ? "s" : ""}
            </Badge>
            <span className="text-xs text-muted-foreground">
              Created {formatRelative(topic.created_at)}
            </span>
          </div>
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
      <CardContent>
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-3 w-24" />
        </div>
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DomainDetailPage() {
  const params = useParams();
  const domainId = Number(params.id);

  const domainQ = useQuery({
    queryKey: ["domain", domainId],
    queryFn: () => fetchDomain(domainId),
    enabled: !isNaN(domainId),
  });

  const topicsQ = useQuery({
    queryKey: ["domain-topics", domainId],
    queryFn: () => fetchTopics({ domain_id: domainId }),
    enabled: !isNaN(domainId),
  });

  const domain = domainQ.data;
  const topics = topicsQ.data ?? [];

  return (
    <div className="space-y-6 p-6 lg:p-8">
      {/* Back link + Header */}
      <div className="space-y-4">
        <Link
          href="/domains"
          className="inline-flex items-center gap-1.5 text-sm text-muted-foreground hover:text-foreground transition-colors"
        >
          <ArrowLeft className="size-3.5" />
          All Domains
        </Link>

        {domainQ.isPending ? (
          <div className="space-y-3">
            <Skeleton className="h-7 w-64" />
            <Skeleton className="h-4 w-96" />
          </div>
        ) : domain ? (
          <div className="flex items-start justify-between">
            <div className="flex items-center gap-3">
              <div className="flex size-9 items-center justify-center rounded-lg bg-blue-600">
                <Globe className="size-5 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-semibold tracking-tight">
                  {domain.name}
                </h1>
                {domain.description && (
                  <p className="mt-0.5 text-sm text-muted-foreground">
                    {domain.description}
                  </p>
                )}
              </div>
            </div>
            <Button size="sm" render={<Link href="/topics/new" />}>
              <Plus className="size-4" />
              New Topic
            </Button>
          </div>
        ) : (
          <p className="text-sm text-muted-foreground">Domain not found.</p>
        )}
      </div>

      {/* Topics grid */}
      <div>
        <h2 className="mb-4 text-lg font-semibold tracking-tight">
          Topics ({topics.length})
        </h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {topicsQ.isPending ? (
            <>
              <TopicCardSkeleton />
              <TopicCardSkeleton />
              <TopicCardSkeleton />
            </>
          ) : topics.length > 0 ? (
            topics.map((topic) => (
              <TopicCard key={topic.id} topic={topic} />
            ))
          ) : (
            <p className="col-span-full text-sm text-muted-foreground">
              No topics in this domain yet.
            </p>
          )}
        </div>
      </div>
    </div>
  );
}
