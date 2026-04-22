# Self-Evolution Design for Research Harness

## Design Goal

Research Harness already records provenance, review artifacts, and structured writing outputs. The self-evolution subsystem extends that foundation with a disciplined feedback loop: the system learns from gold-standard papers during cold start, from explicit human interventions during deployment, and from its own review modules during steady-state operation. The design objective is not "memorize more lessons," but "admit only lessons that remain valid under current conditions."

This document defines a self-evolution architecture suitable for a system paper. It introduces:

1. A unified experience ingestion pipeline shared by cold-start and human-intervention pathways.
2. An Experience Validation Gate that performs discriminative acceptance before any lesson is committed.
3. Temporal decay and relevance scoring so old gold standards do not dominate current behavior.
4. A two-tier decision process:
   - Tier 1: determine whether a feedback item applies to the current paper instance.
   - Tier 2: determine whether an aggregated pattern remains valid as a system-level policy.

The intended paper framing is aligned with recent work on reward modeling and preference learning for alignment and system improvement, critique-based self-correction, Bayesian evidence aggregation, and online ranking. Representative foundations include RLHF and reward modeling [Christiano et al., 2017; Ouyang et al., 2022], preference optimization [Rafailov et al., 2024], self-critique and constitutional feedback [Bai et al., 2022], self-refinement [Madaan et al., 2023], Bayesian updating for non-stationary evidence [Gelman et al., 2013], and ELO-style paired-comparison ranking [Elo, 1978].

## Problem Setting

The self-evolution subsystem observes tuples of:

- A generated artifact, such as a draft section, review response, or experiment write-up.
- A feedback source, such as a gold-paper comparison, a human edit, or an internal critique module.
- The surrounding context, such as venue, year, topic, method family, and target paper stage.
- The post-hoc outcome signal, such as acceptance by a reviewer, lower edit distance to a human revision, or improved downstream review scores.

The central challenge is non-stationarity. Research writing norms drift across years, venues, and subfields. A lesson extracted from a 2018 SIGIR paper may be harmful when applied to a 2026 KDD ADS submission. Therefore, the system must treat feedback as evidence with uncertainty, not as ground truth.

## Design Principles

### P1. One experience schema, multiple sources

Cold-start supervision from gold-standard papers is treated as simulated human intervention. It uses the exact same `ExperienceRecord` schema and ingestion path as explicit human edits. The only difference is `source_kind`.

### P2. Validation before memory

No experience enters the durable lesson store without passing an Experience Validation Gate. This gate evaluates source credibility, temporal validity, contextual fit, and conflict with newer evidence.

### P3. Non-stationary weighting

All evidence is time-aware. Gold standards and old lessons receive temporal decay and field-conditioned relevance adjustments.

### P4. Local applicability and global validity are different questions

The system separately scores:

- instance applicability for a concrete paper or draft;
- global validity for promotion into reusable system policy.

### P5. Favor mainstream, defensible learning mechanisms

The system uses techniques that are well-established and easy to motivate in a system paper: reward modeling, preference learning, critique chains, Bayesian updating, and ELO-style ranking rather than opaque ad hoc heuristics.

## High-Level Architecture

```text
Generation / Review Event
        |
        v
Unified Experience Builder
        |
        v
Experience Validation Gate
  |                     |
  | reject              | accept
  v                     v
RejectedExperience   Experience Store
                            |
                            v
                   Aggregation + Policy Learner
                            |
                            v
                Runtime Retriever + Applicability Scorer
                            |
                            v
                 Prompt Overlay / Strategy Injection
```

## Unified Experience Model

The cold-start pathway and the human-intervention pathway must share the same schema and the same persistence contract.

### Unified ExperienceRecord Schema Shared by Cold-Start and Human-Intervention Pipelines

```python
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypedDict

SourceKind = Literal[
    "gold_paper_comparison",
    "human_edit",
    "self_review",
]

ArtifactKind = Literal[
    "abstract",
    "introduction",
    "related_work",
    "method",
    "experiments",
    "rebuttal",
    "review_response",
]

DecisionLabel = Literal["accept", "reject", "defer"]
FeedbackPolarity = Literal["positive", "negative", "mixed"]


class ContextFeatures(TypedDict, total=False):
    topic_id: int
    artifact_id: int
    provenance_id: int
    target_venue: str
    target_track: str
    submission_year: int
    field: str
    subfield: str
    paper_stage: str
    section: str
    method_family: str
    evaluation_style: str
    language: str


@dataclass(frozen=True)
class FeedbackAtom:
    dimension: str
    observation: str
    proposed_action: str
    rationale: str
    polarity: FeedbackPolarity
    evidence_span: str | None = None
    confidence: float = 0.5


@dataclass(frozen=True)
class SourceMetadata:
    source_kind: SourceKind
    source_id: str
    source_title: str | None = None
    source_authors: tuple[str, ...] = ()
    source_venue: str | None = None
    source_year: int | None = None
    citation_count: int | None = None
    citation_velocity: float | None = None
    recency_months: int | None = None
    collector_model: str | None = None
    reviewer_model: str | None = None
    human_editor_id: str | None = None


@dataclass(frozen=True)
class ValidationTrace:
    tier1_applicability: float
    tier2_policy_validity: float
    temporal_relevance: float
    source_reliability: float
    conflict_penalty: float
    novelty_bonus: float
    final_acceptance_score: float
    decision: DecisionLabel
    reasons: tuple[str, ...] = ()


@dataclass(frozen=True)
class ExperienceRecord:
    experience_id: str
    artifact_id: int | None
    provenance_id: int | None
    created_at: str
    context: ContextFeatures
    source: SourceMetadata
    feedback_atoms: tuple[FeedbackAtom, ...]
    before_text: str
    after_text: str
    edit_distance: float | None = None
    reward_signal: float | None = None
    preference_wins: int = 0
    preference_losses: int = 0
    critique_chain: tuple[str, ...] = ()
    validation: ValidationTrace | None = None
    tags: tuple[str, ...] = ()
```

### Why this schema is unified

Both cold-start and human intervention produce the same object:

- `gold_paper_comparison`: `before_text` is the model output, `after_text` is a gold-standard reference or aligned reconstruction, and feedback atoms are extracted by comparison.
- `human_edit`: `before_text` is the system draft, `after_text` is the human revision, and feedback atoms are extracted from the delta.
- `self_review`: `before_text` is the generated artifact, `after_text` may remain unchanged, and feedback atoms come from critique modules.

The ingestion code never branches on data shape. It branches only on source acquisition.

## Unified Experience Ingestion Pipeline

```python
def ingest_experience(
    *,
    source_kind: SourceKind,
    before_text: str,
    after_text: str,
    context: ContextFeatures,
    source: SourceMetadata,
    critique_chain: tuple[str, ...] = (),
) -> ExperienceRecord:
    feedback_atoms = extract_feedback_atoms(
        before_text=before_text,
        after_text=after_text,
        source_kind=source_kind,
        context=context,
    )
    record = ExperienceRecord(
        experience_id=make_experience_id(),
        artifact_id=context.get("artifact_id"),
        provenance_id=context.get("provenance_id"),
        created_at=utc_now_iso(),
        context=context,
        source=source,
        feedback_atoms=tuple(feedback_atoms),
        before_text=before_text,
        after_text=after_text,
        edit_distance=normalized_edit_distance(before_text, after_text),
        critique_chain=critique_chain,
    )
    return validate_and_commit(record)
```

### Cold-start pathway

1. Generate a draft for a target section.
2. Retrieve a matched gold-standard paper or section.
3. Run structured comparison to extract `FeedbackAtom`s.
4. Call `ingest_experience(..., source_kind="gold_paper_comparison")`.

### Human-intervention pathway

1. Capture the system draft and the human revision.
2. Run the same structured comparison to extract `FeedbackAtom`s.
3. Call `ingest_experience(..., source_kind="human_edit")`.

### Self-review pathway

1. Run internal critique modules, such as consistency, reviewer simulation, or adversarial review.
2. Convert critiques into `FeedbackAtom`s with uncertainty.
3. Call `ingest_experience(..., source_kind="self_review")`.

The key requirement is satisfied by construction: cold start and human intervention are identical after feedback extraction.

## Experience Validation Gate

This section defines the discriminative layer that evaluates feedback quality before acceptance. The gate sits between raw experience extraction and persistent lesson formation.

### Gate Responsibilities

The gate answers four questions:

1. Is the source itself reliable enough to consider?
2. Is the feedback applicable to this specific paper and section?
3. Is the lesson still valid under current best practices?
4. Does the feedback improve predictive or downstream utility relative to existing lessons?

### Tier 1: Per-paper applicability

Tier 1 estimates whether a feedback item applies to the current artifact context. This is an instance-level classification problem.

We define:

\[
S_{\mathrm{tier1}}(e, x)=
w_c \cdot \mathrm{ContextSim}(e, x)+
w_s \cdot \mathrm{SectionMatch}(e, x)+
w_m \cdot \mathrm{MethodMatch}(e, x)+
w_v \cdot \mathrm{VenueNormMatch}(e, x)+
w_r \cdot \mathrm{RewardPredict}(e, x)
\]

where:

- \(e\) is an `ExperienceRecord`;
- \(x\) is the current paper context;
- `ContextSim` is an embedding or typed-feature similarity;
- `RewardPredict` is a learned reward model score estimating whether applying the feedback improves downstream review quality.

This component can be implemented as a lightweight reward model or pairwise preference model trained on accepted versus rejected edits. The motivation follows reward modeling and preference learning for human-aligned decision making [Christiano et al., 2017; Ouyang et al., 2022; Rafailov et al., 2024].

### Tier 2: System-level validity

Tier 2 estimates whether an aggregated feedback pattern should become durable policy. This is a population-level decision problem under concept drift.

For a candidate lesson cluster \(L\), we define:

\[
S_{\mathrm{tier2}}(L)=
\alpha \cdot \mathrm{BayesPosterior}(L)+
\beta \cdot \mathrm{TemporalRelevance}(L)+
\gamma \cdot \mathrm{OutcomeGain}(L)+
\delta \cdot \mathrm{PreferenceRank}(L)-
\lambda \cdot \mathrm{ConflictRate}(L)
\]

Interpretation:

- `BayesPosterior(L)`: posterior belief that the lesson improves quality given observed outcomes;
- `TemporalRelevance(L)`: recency-aware validity score defined below;
- `OutcomeGain(L)`: measured lift in downstream metrics such as reduced edit distance, improved reviewer score, or fewer critical issues;
- `PreferenceRank(L)`: ELO-style or Bradley-Terry style ranking from pairwise comparisons between lessons or strategies;
- `ConflictRate(L)`: frequency with which newer accepted experiences contradict the lesson.

Tier 2 prevents the system from promoting a local or outdated heuristic into global policy.

### Concrete acceptance logic

```python
@dataclass(frozen=True)
class GateThresholds:
    min_source_reliability: float = 0.55
    min_tier1: float = 0.62
    min_temporal_relevance: float = 0.45
    min_final_score: float = 0.65
    min_tier2_for_policy: float = 0.70


def validate_and_commit(record: ExperienceRecord) -> ExperienceRecord:
    reliability = score_source_reliability(record.source)
    temporal = score_temporal_relevance(record.source, record.context)
    tier1 = score_tier1_applicability(record)
    tier2 = score_tier2_policy_validity(record)
    conflict = score_conflict_penalty(record)
    novelty = score_novelty_bonus(record)

    final_score = (
        0.20 * reliability
        + 0.20 * temporal
        + 0.30 * tier1
        + 0.20 * tier2
        - 0.15 * conflict
        + 0.05 * novelty
    )

    if reliability < 0.55:
        decision = "reject"
        reasons = ("low_source_reliability",)
    elif temporal < 0.45:
        decision = "reject"
        reasons = ("temporally_outdated",)
    elif tier1 < 0.62:
        decision = "reject"
        reasons = ("not_applicable_to_current_context",)
    elif final_score < 0.65:
        decision = "defer"
        reasons = ("insufficient_evidence",)
    else:
        decision = "accept"
        reasons = ()

    trace = ValidationTrace(
        tier1_applicability=tier1,
        tier2_policy_validity=tier2,
        temporal_relevance=temporal,
        source_reliability=reliability,
        conflict_penalty=conflict,
        novelty_bonus=novelty,
        final_acceptance_score=final_score,
        decision=decision,
        reasons=reasons,
    )
    enriched = replace(record, validation=trace)

    if decision == "accept":
        write_experience_store(enriched)
        update_lesson_posteriors(enriched)
    else:
        write_rejected_experience(enriched)
    return enriched
```

This logic satisfies the requirement that every feedback source, including gold-paper comparison, human edits, and self-review, is judged before incorporation.

## Temporal Decay and Relevance Scoring for Gold Standards

Older gold-standard papers may become obsolete. The system must explicitly model how paper age, citation dynamics, and field norms alter the reliability of a lesson.

### Temporal relevance formula

For an experience from source paper \(p\), define:

\[
\mathrm{TemporalRelevance}(p, c)=
\exp\left(-\frac{\Delta t(p)}{\tau_f}\right)
\cdot \left(0.5 + 0.5 \cdot \mathrm{VenueRecency}(p, c)\right)
\cdot \left(0.5 + 0.5 \cdot \mathrm{CitationVelocityNorm}(p, c)\right)
\cdot \mathrm{FieldNormMatch}(p, c)
\]

where:

- \(\Delta t(p)\) is the age of the source in months;
- \(\tau_f\) is the field-specific half-life or decay constant;
- `VenueRecency(p, c)` measures whether the source venue's stylistic norms remain current for the target context;
- `CitationVelocityNorm(p, c)` is a normalized citation-velocity score, used as a proxy for ongoing relevance;
- `FieldNormMatch(p, c)` captures whether the source field and target field share writing and evaluation norms.

In implementation:

```python
FIELD_DECAY_MONTHS = {
    "llm_systems": 18.0,
    "information_retrieval": 30.0,
    "data_mining": 30.0,
    "software_engineering": 36.0,
    "causal_ml": 24.0,
}


def score_temporal_relevance(source: SourceMetadata, context: ContextFeatures) -> float:
    field = context.get("field", "software_engineering")
    tau = FIELD_DECAY_MONTHS.get(field, 24.0)
    delta_months = float(source.recency_months or 999.0)
    age_term = math.exp(-delta_months / tau)

    venue_term = venue_recency_score(
        source_venue=source.source_venue,
        source_year=source.source_year,
        target_venue=context.get("target_venue"),
        target_year=context.get("submission_year"),
    )
    velocity_term = citation_velocity_score(
        citation_velocity=source.citation_velocity,
        field=field,
    )
    field_term = field_norm_match(
        source_field=infer_field_from_venue(source.source_venue),
        target_field=field,
        section=context.get("section"),
    )
    return clip01(age_term * (0.5 + 0.5 * venue_term) * (0.5 + 0.5 * velocity_term) * field_term)
```

### Interpretation

- Temporal decay ensures older papers lose default authority.
- Venue recency prevents a lesson from an outdated venue style from overriding a current target venue norm.
- Citation velocity guards against uniformly down-weighting older but still central papers.
- Field norm matching prevents, for example, methodological expectations from ICSE-style empirical SE papers from being blindly transferred into KDD ADS writing.

### Why these signals are defensible

This is a standard non-stationary evidence weighting strategy:

- Exponential decay is the mainstream choice for recency weighting.
- Citation velocity is widely used as a dynamic impact proxy in bibliometrics.
- Venue and field-conditioned scoring encode domain adaptation rather than generic transfer.

The design does not claim these proxies are perfect; it claims they are measurable, interpretable, and easy to ablate in an academic evaluation.

## Source Reliability Modeling

Source reliability should not be hard-coded purely by source type. Human edits are often strong evidence, but they can also be noisy; gold-paper comparisons are valuable during cold start, but may encode obsolete norms; self-review is abundant, but vulnerable to self-confirmation.

We therefore define:

\[
\mathrm{SourceReliability}(e)=
\eta_1 \cdot \mathrm{BasePrior}(\text{source\_kind})
+\eta_2 \cdot \mathrm{ReviewerAgreement}
+\eta_3 \cdot \mathrm{OutcomeCalibration}
+\eta_4 \cdot \mathrm{MetadataQuality}
\]

Typical initialization:

- `human_edit`: high prior, but reduced if later outcomes show inconsistent improvement.
- `gold_paper_comparison`: medium prior, improved by strong recency and venue match.
- `self_review`: lower prior unless corroborated by human or outcome evidence.

This is naturally updated by Bayesian calibration. If a source repeatedly yields accepted lessons that improve downstream outcomes, its posterior reliability increases.

## Critique Chains and Feedback Extraction

Raw diffs are not enough for stable learning. The system should convert deltas into explicit critique chains and action-oriented feedback atoms.

### Critique chain template

```text
Observation -> Principle -> Proposed rewrite/action -> Expected outcome
```

Example:

```text
Observation: the introduction claims novelty before setting up the problem.
Principle: KDD-style introductions usually establish problem stakes and operational context first.
Proposed action: move novelty claims after problem framing and insert one paragraph on decision impact.
Expected outcome: improved reviewer perception of motivation and practical grounding.
```

This follows critique-based self-improvement lines of work [Bai et al., 2022; Madaan et al., 2023] while keeping the output typed and auditable.

## Preference Learning and Reward Modeling

The subsystem needs a ranking signal over competing lessons and strategies.

### Pairwise preferences

For two candidate revisions \(y_a\) and \(y_b\) for the same prompt and context, the system records which revision is preferred by:

- a human editor,
- a gold-standard alignment metric,
- or a downstream review module.

These preferences train:

1. A reward model \(R(x, y)\) predicting expected quality gain.
2. A pairwise preference model or direct preference optimization objective [Rafailov et al., 2024].

### ELO-style ranking

For reusable lessons or prompt overlays, an ELO-style score offers a simple online ranking mechanism:

\[
\mathrm{ELO}_{t+1}(L_i)=\mathrm{ELO}_{t}(L_i)+K \cdot (\mathrm{Outcome}-\mathrm{Expected})
\]

where the "match" is a pairwise comparison between two candidate lessons on the same task slice. This ranking is easy to explain and works well as an online exploration-exploitation signal.

### Bayesian posterior for lesson validity

For each lesson cluster \(L\), maintain a Beta-Bernoulli posterior:

\[
\theta_L \sim \mathrm{Beta}(\alpha_0, \beta_0)
\]
\[
\alpha_L = \alpha_0 + \text{successful applications}, \quad
\beta_L = \beta_0 + \text{failed applications}
\]

The posterior mean \(\mathbb{E}[\theta_L]\) becomes a stable estimate of lesson usefulness. This is the `BayesPosterior(L)` term in Tier 2.

## Lesson Aggregation

Accepted experiences are not directly injected as prompts. They are clustered into normalized lesson candidates.

### LessonCandidate

```python
@dataclass(frozen=True)
class LessonCandidate:
    lesson_id: str
    scope: str  # "section_local" | "venue_local" | "field_global"
    canonical_rule: str
    supporting_experience_ids: tuple[str, ...]
    contradicted_by: tuple[str, ...] = ()
    elo_rating: float = 1200.0
    bayes_alpha: float = 1.0
    bayes_beta: float = 1.0
    last_validated_at: str | None = None
    active: bool = True
```

### Aggregation algorithm

```python
def aggregate_lessons(experiences: list[ExperienceRecord]) -> list[LessonCandidate]:
    clusters = semantic_cluster(experiences, key=lambda e: e.feedback_atoms)
    lessons: list[LessonCandidate] = []
    for cluster in clusters:
        rule = summarize_cluster_into_rule(cluster)
        lessons.append(
            LessonCandidate(
                lesson_id=make_lesson_id(cluster),
                scope=infer_scope(cluster),
                canonical_rule=rule,
                supporting_experience_ids=tuple(e.experience_id for e in cluster),
            )
        )
    return lessons
```

Promotion from accepted experience to active lesson occurs only after Tier 2 exceeds the policy threshold.

## Runtime Retrieval and Application

At inference time, the system should not apply the entire lesson store. It retrieves a small set of candidate lessons and reruns Tier 1 scoring for the current paper.

```python
def retrieve_applicable_lessons(context: ContextFeatures) -> list[LessonCandidate]:
    candidates = nearest_lessons(context, top_k=20)
    rescored = [
        (lesson, score_lesson_applicability(lesson, context))
        for lesson in candidates
        if lesson.active
    ]
    return [lesson for lesson, score in sorted(rescored, key=lambda x: x[1], reverse=True) if score >= 0.62][:5]
```

This creates a closed loop:

1. Learn from experiences.
2. Promote durable lessons.
3. Retrieve context-relevant lessons.
4. Observe whether they help.
5. Update posterior validity.

## Failure Modes and Safeguards

### Failure mode 1: outdated gold standards

Mitigation:

- explicit temporal decay;
- venue recency score;
- citation velocity normalization;
- field-specific decay constants;
- periodic revalidation of active lessons.

### Failure mode 2: overfitting to one editor or one venue

Mitigation:

- source reliability posterior;
- conflict penalties across diverse contexts;
- scope inference so local rules stay local.

### Failure mode 3: self-reinforcing internal critique

Mitigation:

- lower prior for `self_review`;
- require external corroboration for promotion to policy;
- track disagreement with human and gold sources.

### Failure mode 4: accepting high-confidence but context-mismatched advice

Mitigation:

- hard Tier 1 threshold;
- section and method-family matching;
- reward model conditioned on context.

## Evaluation Plan

A system paper can evaluate the self-evolution subsystem along four axes:

1. Acceptance precision of the Experience Validation Gate.
   Measure how often accepted experiences lead to downstream quality gains versus rejected experiences.

2. Temporal robustness.
   Compare performance with and without temporal relevance scoring under old-vs-new gold standards.

3. Unified cold-start transfer.
   Show that gold-paper comparison and human-edit data improve the same reward model because they share one schema and pipeline.

4. Policy quality.
   Measure whether Tier 2 promoted lessons improve later drafts, review scores, or reduction in human editing effort.

Recommended ablations:

- no temporal decay;
- no Tier 1 gate;
- no Tier 2 gate;
- separate schemas for gold versus human;
- no Bayesian update;
- no ELO preference ranking.

## Implementation Mapping to Research Harness

The subsystem aligns naturally with existing monorepo components:

- provenance records provide stable `provenance_id` anchors for experiences;
- orchestrator artifacts store accepted lesson snapshots and validation reports;
- review primitives and adversarial review provide `self_review` signals;
- section drafting and review loops provide before/after artifacts;
- strategy injection can retrieve active lessons as prompt overlays.

Suggested durable stores:

- `experience_records` table for raw accepted and rejected experiences;
- `lesson_candidates` table for normalized reusable rules;
- `lesson_applications` table for posterior updates after runtime use;
- `experience_validation_reports` table for auditability.

## Dedicated Requirement Checklist

### Requirement 1: Temporal validity of gold standards

Addressed by:

- the `TemporalRelevance(p, c)` formula;
- field-specific decay constants;
- venue recency scoring;
- citation velocity normalization;
- periodic Tier 2 revalidation of active lessons.

### Requirement 2: Unified feedback model

Addressed by:

- the single `ExperienceRecord` schema defined once in this document;
- one `ingest_experience()` path for cold-start, human-edit, and self-review;
- `source_kind` as the only source-specific difference.

### Requirement 3: Discriminative capability

Addressed by:

- Tier 1 per-paper applicability scoring;
- Tier 2 system-level policy validity scoring;
- the Experience Validation Gate with explicit accept, reject, and defer logic.

## References

- Bai, Y., et al. 2022. Constitutional AI: Harmlessness from AI Feedback.
- Christiano, P. F., et al. 2017. Deep Reinforcement Learning from Human Preferences.
- Elo, A. E. 1978. The Rating of Chessplayers, Past and Present.
- Gelman, A., et al. 2013. Bayesian Data Analysis, 3rd ed.
- Madaan, A., et al. 2023. Self-Refine: Iterative Refinement with Self-Feedback.
- Ouyang, L., et al. 2022. Training language models to follow instructions with human feedback.
- Rafailov, R., et al. 2024. Direct Preference Optimization.
