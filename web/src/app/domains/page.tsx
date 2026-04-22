"use client";

import { useQuery } from "@tanstack/react-query";
import { Globe, Plus } from "lucide-react";
import Link from "next/link";
import { fetchDomains } from "@/lib/api";
import type { Domain } from "@/lib/types";
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
// Domain card
// ---------------------------------------------------------------------------

function DomainCard({ domain }: { domain: Domain }) {
  return (
    <Link href={`/domains/${domain.id}`} className="block">
      <Card className="transition-shadow hover:ring-2 hover:ring-blue-500/20">
        <CardHeader>
          <CardTitle>{domain.name}</CardTitle>
          {domain.description && (
            <CardDescription className="truncate">
              {domain.description}
            </CardDescription>
          )}
        </CardHeader>
        <CardContent className="space-y-3">
          <div className="flex items-center gap-2">
            <Badge variant="secondary" className="text-xs">
              {domain.topic_count} topic{domain.topic_count !== 1 ? "s" : ""}
            </Badge>
            <Badge variant="outline" className="text-xs">
              {domain.status}
            </Badge>
          </div>
          <p className="text-xs text-muted-foreground">
            Created {formatRelative(domain.created_at)}
          </p>
        </CardContent>
      </Card>
    </Link>
  );
}

function DomainCardSkeleton() {
  return (
    <Card>
      <CardHeader>
        <Skeleton className="h-5 w-36" />
        <Skeleton className="h-4 w-48" />
      </CardHeader>
      <CardContent className="space-y-3">
        <div className="flex items-center gap-2">
          <Skeleton className="h-5 w-16 rounded-full" />
          <Skeleton className="h-5 w-14 rounded-full" />
        </div>
        <Skeleton className="h-3 w-24" />
      </CardContent>
    </Card>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function DomainsPage() {
  const { data: domains, isPending, error } = useQuery({
    queryKey: ["domains"],
    queryFn: fetchDomains,
  });

  return (
    <div className="space-y-6 p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <div className="flex size-9 items-center justify-center rounded-lg bg-blue-600">
            <Globe className="size-5 text-white" />
          </div>
          <div>
            <h1 className="text-2xl font-semibold tracking-tight">Domains</h1>
            <p className="text-sm text-muted-foreground">
              Research domains organize related topics.
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
            <DomainCardSkeleton />
            <DomainCardSkeleton />
            <DomainCardSkeleton />
          </>
        ) : error ? (
          <p className="col-span-full text-sm text-muted-foreground">
            Failed to load domains.
          </p>
        ) : domains?.length ? (
          domains.map((domain) => (
            <DomainCard key={domain.id} domain={domain} />
          ))
        ) : (
          <p className="col-span-full text-sm text-muted-foreground">
            No domains found. Create one when setting up a new topic.
          </p>
        )}
      </div>
    </div>
  );
}
