"use client";

import { useCallback, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { useQuery } from "@tanstack/react-query";
import {
  Check,
  ChevronLeft,
  ChevronRight,
  FileText,
  Globe,
  BookOpen,
  Loader2,
} from "lucide-react";
import Link from "next/link";

import { cn } from "@/lib/utils";
import { fetchDomains, createDomain, createTopic, ingestPaper } from "@/lib/api";
import type { Domain } from "@/lib/types";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const STEPS = [
  { label: "Domain", icon: Globe },
  { label: "Topic", icon: BookOpen },
  { label: "Seed Papers", icon: FileText },
  { label: "Confirm", icon: Check },
] as const;

const TOTAL_STEPS = STEPS.length;

// ---------------------------------------------------------------------------
// Step indicator
// ---------------------------------------------------------------------------

function StepIndicator({ current }: { current: number }) {
  return (
    <nav aria-label="Wizard steps" className="flex items-center justify-center gap-0">
      {STEPS.map((step, i) => {
        const done = i < current;
        const active = i === current;
        const Icon = step.icon;

        return (
          <div key={step.label} className="flex items-center">
            {i > 0 && (
              <div
                className={cn(
                  "h-px w-10 sm:w-16 transition-colors",
                  done ? "bg-blue-500" : "bg-slate-300 dark:bg-slate-700"
                )}
              />
            )}

            <div className="flex flex-col items-center gap-1.5">
              <div
                className={cn(
                  "flex size-9 items-center justify-center rounded-full border-2 transition-colors",
                  done
                    ? "border-blue-500 bg-blue-500 text-white"
                    : active
                      ? "border-blue-500 bg-white text-blue-600 dark:bg-slate-900"
                      : "border-slate-300 bg-white text-slate-400 dark:border-slate-700 dark:bg-slate-900"
                )}
              >
                {done ? (
                  <Check className="size-4" />
                ) : (
                  <Icon className="size-4" />
                )}
              </div>
              <span
                className={cn(
                  "text-xs font-medium transition-colors",
                  active
                    ? "text-blue-600 dark:text-blue-400"
                    : done
                      ? "text-foreground"
                      : "text-muted-foreground"
                )}
              >
                {step.label}
              </span>
            </div>
          </div>
        );
      })}
    </nav>
  );
}

// ---------------------------------------------------------------------------
// Seed paper ID parser
// ---------------------------------------------------------------------------

function parseSeedIds(raw: string): string[] {
  return raw
    .split(/[\n,]+/)
    .map((s) => s.trim())
    .filter(Boolean);
}

// ---------------------------------------------------------------------------
// Step 1: Domain
// ---------------------------------------------------------------------------

function StepDomain({
  domains,
  domainsLoading,
  useExistingDomain,
  setUseExistingDomain,
  existingDomainId,
  setExistingDomainId,
  domainName,
  setDomainName,
  domainDescription,
  setDomainDescription,
}: {
  domains: Domain[];
  domainsLoading: boolean;
  useExistingDomain: boolean;
  setUseExistingDomain: (v: boolean) => void;
  existingDomainId: number | null;
  setExistingDomainId: (v: number | null) => void;
  domainName: string;
  setDomainName: (v: string) => void;
  domainDescription: string;
  setDomainDescription: (v: string) => void;
}) {
  return (
    <div className="space-y-6">
      <div className="flex gap-2">
        <Button
          variant={useExistingDomain ? "outline" : "default"}
          size="sm"
          onClick={() => setUseExistingDomain(false)}
        >
          Create new domain
        </Button>
        <Button
          variant={useExistingDomain ? "default" : "outline"}
          size="sm"
          onClick={() => setUseExistingDomain(true)}
        >
          Use existing domain
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-muted-foreground"
          onClick={() => {
            setUseExistingDomain(false);
            setExistingDomainId(null);
            setDomainName("");
            setDomainDescription("");
          }}
        >
          Skip (no domain)
        </Button>
      </div>

      {useExistingDomain ? (
        <div className="space-y-3">
          <label className="text-sm font-medium text-foreground">
            Select domain
          </label>
          {domainsLoading ? (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              Loading domains...
            </div>
          ) : domains.length === 0 ? (
            <p className="text-sm text-muted-foreground">
              No domains found. Create a new one instead.
            </p>
          ) : (
            <select
              value={existingDomainId ?? ""}
              onChange={(e) => {
                const val = e.target.value;
                setExistingDomainId(val ? Number(val) : null);
              }}
              className="h-8 w-full rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            >
              <option value="">-- Choose a domain --</option>
              {domains.map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name} ({d.topic_count} topics)
                </option>
              ))}
            </select>
          )}
        </div>
      ) : (
        <div className="space-y-4">
          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              Domain name
            </label>
            <Input
              placeholder="e.g., computational-advertising"
              value={domainName}
              onChange={(e) => setDomainName(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Leave empty to create the topic without a domain.
            </p>
          </div>

          <div className="space-y-1.5">
            <label className="text-sm font-medium text-foreground">
              Domain description
            </label>
            <Textarea
              placeholder="Brief description of the research domain..."
              value={domainDescription}
              onChange={(e) => setDomainDescription(e.target.value)}
              rows={2}
            />
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2: Topic details
// ---------------------------------------------------------------------------

function StepTopicDetails({
  domainLabel,
  topicName,
  setTopicName,
  topicDescription,
  setTopicDescription,
  targetVenue,
  setTargetVenue,
  deadline,
  setDeadline,
}: {
  domainLabel: string;
  topicName: string;
  setTopicName: (v: string) => void;
  topicDescription: string;
  setTopicDescription: (v: string) => void;
  targetVenue: string;
  setTargetVenue: (v: string) => void;
  deadline: string;
  setDeadline: (v: string) => void;
}) {
  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 rounded-lg bg-slate-100 px-3 py-2 text-sm dark:bg-slate-800">
        <Globe className="size-4 text-blue-500" />
        <span className="text-muted-foreground">Domain:</span>
        <span className="font-medium">{domainLabel}</span>
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium text-foreground">
          Topic name <span className="text-red-500">*</span>
        </label>
        <Input
          placeholder="e.g., auto-bidding-budget-pacing"
          value={topicName}
          onChange={(e) => setTopicName(e.target.value)}
        />
      </div>

      <div className="space-y-1.5">
        <label className="text-sm font-medium text-foreground">
          Description
        </label>
        <Textarea
          placeholder="Brief description of the research topic..."
          value={topicDescription}
          onChange={(e) => setTopicDescription(e.target.value)}
          rows={3}
        />
      </div>

      <div className="grid grid-cols-2 gap-4">
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-foreground">
            Target venue
          </label>
          <Input
            placeholder="e.g., KDD 2027"
            value={targetVenue}
            onChange={(e) => setTargetVenue(e.target.value)}
          />
        </div>
        <div className="space-y-1.5">
          <label className="text-sm font-medium text-foreground">
            Deadline
          </label>
          <Input
            type="date"
            value={deadline}
            onChange={(e) => setDeadline(e.target.value)}
          />
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3: Seed Papers
// ---------------------------------------------------------------------------

function StepSeedPapers({
  seedPapersRaw,
  setSeedPapersRaw,
}: {
  seedPapersRaw: string;
  setSeedPapersRaw: (v: string) => void;
}) {
  const parsed = useMemo(() => parseSeedIds(seedPapersRaw), [seedPapersRaw]);

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <label className="text-sm font-medium text-foreground">
          Seed paper IDs
        </label>
        <p className="text-xs text-muted-foreground">
          Paste arXiv IDs or DOIs, one per line. These will be ingested into the
          topic&apos;s paper pool. This step is optional.
        </p>
        <Textarea
          placeholder={"2401.12345\n2403.67890\n10.1145/1234567.1234568"}
          value={seedPapersRaw}
          onChange={(e) => setSeedPapersRaw(e.target.value)}
          rows={6}
          className="font-mono text-xs"
        />
      </div>

      {parsed.length > 0 && (
        <div className="space-y-2">
          <p className="text-sm font-medium text-foreground">
            Parsed IDs ({parsed.length})
          </p>
          <div className="flex flex-wrap gap-1.5">
            {parsed.map((id) => (
              <Badge key={id} variant="secondary" className="font-mono text-xs">
                {id}
              </Badge>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4: Confirm
// ---------------------------------------------------------------------------

function StepConfirm({
  domainLabel,
  topicName,
  topicDescription,
  targetVenue,
  deadline,
  seedPapers,
}: {
  domainLabel: string;
  topicName: string;
  topicDescription: string;
  targetVenue: string;
  deadline: string;
  seedPapers: string[];
}) {
  const rows: Array<{ label: string; value: string }> = [
    { label: "Domain", value: domainLabel },
    { label: "Topic name", value: topicName },
  ];

  if (topicDescription) {
    rows.push({ label: "Description", value: topicDescription });
  }
  if (targetVenue) {
    rows.push({ label: "Target venue", value: targetVenue });
  }
  if (deadline) {
    rows.push({ label: "Deadline", value: deadline });
  }
  rows.push({
    label: "Seed papers",
    value: seedPapers.length > 0 ? `${seedPapers.length} paper(s)` : "None",
  });

  return (
    <div className="space-y-4">
      <p className="text-sm text-muted-foreground">
        Review the details below, then click &quot;Create Topic&quot; to
        proceed.
      </p>

      <div className="divide-y rounded-lg border">
        {rows.map((row) => (
          <div key={row.label} className="flex gap-4 px-4 py-2.5 text-sm">
            <span className="w-36 shrink-0 font-medium text-muted-foreground">
              {row.label}
            </span>
            <span className="text-foreground">{row.value}</span>
          </div>
        ))}
      </div>

      {seedPapers.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {seedPapers.map((id) => (
            <Badge key={id} variant="secondary" className="font-mono text-xs">
              {id}
            </Badge>
          ))}
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main Wizard Page
// ---------------------------------------------------------------------------

export default function NewTopicPage() {
  const router = useRouter();

  // Step state
  const [step, setStep] = useState(0);

  // Step 1: Domain
  const [useExistingDomain, setUseExistingDomain] = useState(false);
  const [existingDomainId, setExistingDomainId] = useState<number | null>(null);
  const [domainName, setDomainName] = useState("");
  const [domainDescription, setDomainDescription] = useState("");

  // Step 2: Topic
  const [topicName, setTopicName] = useState("");
  const [topicDescription, setTopicDescription] = useState("");
  const [targetVenue, setTargetVenue] = useState("");
  const [deadline, setDeadline] = useState("");

  // Step 3: Seed papers
  const [seedPapersRaw, setSeedPapersRaw] = useState("");

  // Submission state
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState(false);

  // Fetch existing domains
  const { data: domains = [], isPending: domainsLoading } = useQuery({
    queryKey: ["domains"],
    queryFn: fetchDomains,
  });

  // Derived values
  const seedPapers = useMemo(() => parseSeedIds(seedPapersRaw), [seedPapersRaw]);

  const domainLabel = useMemo(() => {
    if (useExistingDomain && existingDomainId) {
      const d = domains.find((dom) => dom.id === existingDomainId);
      return d?.name ?? "--";
    }
    if (domainName.trim()) return `New: ${domainName}`;
    return "None (standalone topic)";
  }, [useExistingDomain, existingDomainId, domainName, domains]);

  // ---------------------------------------------------------------------------
  // Validation
  // ---------------------------------------------------------------------------

  const canProceed = useCallback((): boolean => {
    switch (step) {
      case 0:
        // Domain step is always valid — domain is optional
        if (useExistingDomain) return existingDomainId !== null;
        return true;
      case 1:
        return topicName.trim().length > 0;
      case 2:
        return true; // optional
      case 3:
        return true;
      default:
        return false;
    }
  }, [step, useExistingDomain, existingDomainId, topicName]);

  // ---------------------------------------------------------------------------
  // Navigation
  // ---------------------------------------------------------------------------

  function goNext() {
    if (step < TOTAL_STEPS - 1) setStep(step + 1);
  }

  function goBack() {
    if (step > 0) setStep(step - 1);
  }

  // ---------------------------------------------------------------------------
  // Submit
  // ---------------------------------------------------------------------------

  async function handleSubmit() {
    setSubmitting(true);
    setError(null);

    try {
      // 1. Resolve domain_id (create new if needed)
      let domainId: number | undefined;

      if (useExistingDomain && existingDomainId) {
        domainId = existingDomainId;
      } else if (domainName.trim()) {
        const newDomain = await createDomain({
          name: domainName.trim(),
          description: domainDescription.trim() || undefined,
        });
        domainId = newDomain.id;
      }

      // 2. Create topic
      const newTopic = await createTopic({
        name: topicName.trim(),
        description: topicDescription.trim(),
        domain_id: domainId,
        target_venue: targetVenue.trim() || undefined,
        deadline: deadline.trim() || undefined,
      });

      // 3. Ingest seed papers
      const ingestErrors: string[] = [];
      for (const source of seedPapers) {
        try {
          await ingestPaper({ source, topic_id: newTopic.id, relevance: "high" });
        } catch (e) {
          ingestErrors.push(
            `${source}: ${e instanceof Error ? e.message : "Unknown error"}`
          );
        }
      }

      if (ingestErrors.length > 0) {
        setError(
          `Topic created, but ${ingestErrors.length} paper(s) failed to ingest:\n${ingestErrors.join("\n")}`
        );
      }

      setSuccess(true);

      // 4. Redirect after brief delay
      setTimeout(() => {
        router.push(`/topics/${newTopic.id}`);
      }, 1500);
    } catch (e) {
      setError(e instanceof Error ? e.message : "An unknown error occurred.");
    } finally {
      setSubmitting(false);
    }
  }

  // ---------------------------------------------------------------------------
  // Render
  // ---------------------------------------------------------------------------

  return (
    <div className="space-y-6 p-6 lg:p-8">
      {/* Header */}
      <div className="flex items-center gap-3">
        <div className="flex size-9 items-center justify-center rounded-lg bg-emerald-600">
          <BookOpen className="size-5 text-white" />
        </div>
        <div>
          <h1 className="text-2xl font-semibold tracking-tight">
            New Topic
          </h1>
          <p className="text-sm text-muted-foreground">
            Set up a research domain and topic in a few steps.
          </p>
        </div>
      </div>

      {/* Step indicator */}
      <StepIndicator current={step} />

      {/* Card */}
      <Card className="mx-auto max-w-2xl">
        <CardHeader>
          <CardTitle>{STEPS[step].label}</CardTitle>
          <CardDescription>
            {step === 0 && "Choose an existing domain or create a new one. You can also skip this step."}
            {step === 1 && "Name your research topic and set workflow details."}
            {step === 2 && "Optionally add seed papers to bootstrap the literature pool."}
            {step === 3 && "Review everything before creating."}
          </CardDescription>
        </CardHeader>

        <CardContent>
          {/* Step content */}
          {step === 0 && (
            <StepDomain
              domains={domains}
              domainsLoading={domainsLoading}
              useExistingDomain={useExistingDomain}
              setUseExistingDomain={setUseExistingDomain}
              existingDomainId={existingDomainId}
              setExistingDomainId={setExistingDomainId}
              domainName={domainName}
              setDomainName={setDomainName}
              domainDescription={domainDescription}
              setDomainDescription={setDomainDescription}
            />
          )}
          {step === 1 && (
            <StepTopicDetails
              domainLabel={domainLabel}
              topicName={topicName}
              setTopicName={setTopicName}
              topicDescription={topicDescription}
              setTopicDescription={setTopicDescription}
              targetVenue={targetVenue}
              setTargetVenue={setTargetVenue}
              deadline={deadline}
              setDeadline={setDeadline}
            />
          )}
          {step === 2 && (
            <StepSeedPapers
              seedPapersRaw={seedPapersRaw}
              setSeedPapersRaw={setSeedPapersRaw}
            />
          )}
          {step === 3 && (
            <StepConfirm
              domainLabel={domainLabel}
              topicName={topicName}
              topicDescription={topicDescription}
              targetVenue={targetVenue}
              deadline={deadline}
              seedPapers={seedPapers}
            />
          )}

          {/* Error / success feedback */}
          {error && (
            <div className="mt-4 rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700 dark:border-red-800 dark:bg-red-950/30 dark:text-red-400 whitespace-pre-wrap">
              {error}
            </div>
          )}
          {success && (
            <div className="mt-4 rounded-lg border border-emerald-200 bg-emerald-50 px-4 py-3 text-sm text-emerald-700 dark:border-emerald-800 dark:bg-emerald-950/30 dark:text-emerald-400">
              Topic created successfully! Redirecting...
            </div>
          )}
        </CardContent>

        {/* Footer navigation */}
        <div className="flex items-center justify-between border-t px-4 py-3">
          <div>
            {step > 0 ? (
              <Button variant="ghost" size="sm" onClick={goBack} disabled={submitting}>
                <ChevronLeft className="size-4" data-icon="inline-start" />
                Back
              </Button>
            ) : (
              <Button variant="ghost" size="sm" render={<Link href="/topics" />}>
                Cancel
              </Button>
            )}
          </div>

          <div>
            {step < TOTAL_STEPS - 1 ? (
              <Button
                size="sm"
                onClick={goNext}
                disabled={!canProceed()}
              >
                Next
                <ChevronRight className="size-4" data-icon="inline-end" />
              </Button>
            ) : (
              <Button
                size="sm"
                onClick={handleSubmit}
                disabled={submitting || success}
              >
                {submitting ? (
                  <>
                    <Loader2 className="size-4 animate-spin" data-icon="inline-start" />
                    Creating...
                  </>
                ) : (
                  "Create Topic"
                )}
              </Button>
            )}
          </div>
        </div>
      </Card>
    </div>
  );
}
