"""ProvenanceRecorder — records every primitive execution to DB."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from ..primitives.registry import get_primitive_spec
from ..primitives.types import PrimitiveResult
from .models import ProvenanceRecord, ProvenanceSummary


class ProvenanceRecorder:
    """Records provenance for every research primitive execution."""

    def __init__(self, db: Any):
        self._db = db

    def record(
        self,
        result: PrimitiveResult,
        input_kwargs: dict[str, Any],
        topic_id: int | None = None,
        stage: str = "",
        parent_id: int | None = None,
        artifact_id: int | None = None,
        quality_score: float | None = None,
        human_accept: bool | None = None,
        loop_round: int = 0,
    ) -> int:
        """Record a primitive execution and return the record id."""

        conn = self._db.connect()
        try:
            cursor = conn.execute(
                """
                INSERT INTO provenance_records
                    (primitive, category, started_at, finished_at, backend, model_used,
                     topic_id, stage, input_hash, output_hash, cost_usd, success, error, parent_id,
                     artifact_id, quality_score, human_accept, loop_round,
                     prompt_tokens, completion_tokens)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    result.primitive,
                    self._get_category(result.primitive),
                    result.started_at,
                    result.finished_at,
                    result.backend,
                    result.model_used,
                    topic_id,
                    stage,
                    self._hash_dict(input_kwargs),
                    result.output_hash(),
                    result.cost_usd,
                    1 if result.success else 0,
                    result.error,
                    parent_id,
                    artifact_id,
                    quality_score,
                    1 if human_accept else (0 if human_accept is not None else None),
                    loop_round,
                    result.prompt_tokens,
                    result.completion_tokens,
                ),
            )
            conn.commit()
            return int(cursor.lastrowid)
        finally:
            conn.close()

    def get(self, record_id: int) -> ProvenanceRecord | None:
        """Retrieve a single provenance record."""

        conn = self._db.connect()
        try:
            row = conn.execute(
                "SELECT * FROM provenance_records WHERE id = ?", (record_id,)
            ).fetchone()
            if row is None:
                return None
            return self._row_to_record(row)
        finally:
            conn.close()

    def list_records(
        self,
        topic_id: int | None = None,
        primitive: str | None = None,
        backend: str | None = None,
        limit: int = 100,
    ) -> list[ProvenanceRecord]:
        """Query provenance records with optional filters."""

        conn = self._db.connect()
        try:
            clauses: list[str] = []
            params: list[Any] = []

            if topic_id is not None:
                clauses.append("topic_id = ?")
                params.append(topic_id)
            if primitive:
                clauses.append("primitive = ?")
                params.append(primitive)
            if backend:
                clauses.append("backend = ?")
                params.append(backend)

            where = " AND ".join(clauses) if clauses else "1=1"
            params.append(limit)
            rows = conn.execute(
                f"SELECT * FROM provenance_records WHERE {where} ORDER BY id DESC LIMIT ?",
                params,
            ).fetchall()
            return [self._row_to_record(row) for row in rows]
        finally:
            conn.close()

    def summarize(
        self,
        topic_id: int | None = None,
        backend: str | None = None,
    ) -> ProvenanceSummary:
        """Generate aggregate statistics from provenance records."""

        records = self.list_records(topic_id=topic_id, backend=backend, limit=10000)
        if not records:
            return ProvenanceSummary()

        operations_by_backend: dict[str, int] = {}
        operations_by_primitive: dict[str, int] = {}
        cost_by_backend: dict[str, float] = {}
        cost_by_primitive: dict[str, float] = {}
        tokens_by_backend: dict[str, dict[str, int]] = {}
        tokens_by_primitive: dict[str, dict[str, int]] = {}
        total_prompt = 0
        total_completion = 0
        successes = 0

        for record in records:
            operations_by_backend[record.backend] = operations_by_backend.get(record.backend, 0) + 1
            operations_by_primitive[record.primitive] = operations_by_primitive.get(record.primitive, 0) + 1
            cost_by_backend[record.backend] = cost_by_backend.get(record.backend, 0.0) + record.cost_usd
            cost_by_primitive[record.primitive] = cost_by_primitive.get(record.primitive, 0.0) + record.cost_usd

            pt = record.prompt_tokens or 0
            ct = record.completion_tokens or 0
            total_prompt += pt
            total_completion += ct
            b_bucket = tokens_by_backend.setdefault(
                record.backend, {"prompt": 0, "completion": 0}
            )
            b_bucket["prompt"] += pt
            b_bucket["completion"] += ct
            p_bucket = tokens_by_primitive.setdefault(
                record.primitive, {"prompt": 0, "completion": 0}
            )
            p_bucket["prompt"] += pt
            p_bucket["completion"] += ct

            if record.success:
                successes += 1

        return ProvenanceSummary(
            total_operations=len(records),
            total_cost_usd=sum(record.cost_usd for record in records),
            operations_by_backend=operations_by_backend,
            operations_by_primitive=operations_by_primitive,
            cost_by_backend=cost_by_backend,
            cost_by_primitive=cost_by_primitive,
            success_rate=successes / len(records),
            time_range=(records[-1].started_at, records[0].finished_at),
            total_prompt_tokens=total_prompt,
            total_completion_tokens=total_completion,
            tokens_by_backend=tokens_by_backend,
            tokens_by_primitive=tokens_by_primitive,
        )

    def token_report_by_agent(
        self,
        topic_id: int | None = None,
    ) -> list[dict[str, Any]]:
        """Aggregate token / cost usage grouped by (backend, model_used).

        Designed for long-term per-topic per-agent accounting. Returns a list of
        rows sorted by total cost descending, each with call count, token
        sums, and derived metrics.
        """

        conn = self._db.connect()
        try:
            clauses: list[str] = []
            params: list[Any] = []
            if topic_id is not None:
                clauses.append("topic_id = ?")
                params.append(topic_id)
            where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
            rows = conn.execute(
                f"""
                SELECT
                    backend,
                    model_used,
                    COUNT(*)                       AS calls,
                    SUM(COALESCE(prompt_tokens, 0))     AS prompt_tokens,
                    SUM(COALESCE(completion_tokens, 0)) AS completion_tokens,
                    SUM(cost_usd)                  AS cost_usd,
                    SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END) AS successes
                FROM provenance_records
                {where}
                GROUP BY backend, model_used
                ORDER BY cost_usd DESC
                """,
                params,
            ).fetchall()
            report: list[dict[str, Any]] = []
            for row in rows:
                calls = int(row["calls"])
                prompt = int(row["prompt_tokens"] or 0)
                completion = int(row["completion_tokens"] or 0)
                cost = float(row["cost_usd"] or 0.0)
                report.append(
                    {
                        "backend": row["backend"],
                        "model_used": row["model_used"],
                        "calls": calls,
                        "prompt_tokens": prompt,
                        "completion_tokens": completion,
                        "total_tokens": prompt + completion,
                        "cost_usd": cost,
                        "cost_per_call": cost / calls if calls else 0.0,
                        "success_rate": (int(row["successes"]) / calls) if calls else 0.0,
                    }
                )
            return report
        finally:
            conn.close()

    def _get_category(self, primitive_name: str) -> str:
        spec = get_primitive_spec(primitive_name)
        return spec.category.value if spec is not None else ""

    def _hash_dict(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]

    def _row_to_record(self, row: Any) -> ProvenanceRecord:
        keys = row.keys() if hasattr(row, "keys") else []

        def _opt_int(col: str) -> int | None:
            if col not in keys:
                return None
            value = row[col]
            if value is None:
                return None
            try:
                return int(value)
            except (TypeError, ValueError):
                return None

        return ProvenanceRecord(
            id=int(row["id"]),
            primitive=row["primitive"],
            category=row["category"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            backend=row["backend"],
            model_used=row["model_used"],
            topic_id=row["topic_id"],
            stage=row["stage"],
            input_hash=row["input_hash"],
            output_hash=row["output_hash"],
            cost_usd=float(row["cost_usd"]),
            success=bool(row["success"]),
            error=row["error"],
            parent_id=row["parent_id"],
            artifact_id=row["artifact_id"] if "artifact_id" in keys else None,
            quality_score=float(row["quality_score"]) if "quality_score" in keys and row["quality_score"] is not None else None,
            human_accept=bool(row["human_accept"]) if "human_accept" in keys and row["human_accept"] is not None else None,
            loop_round=int(row["loop_round"] or 0) if "loop_round" in keys else 0,
            created_at=row["created_at"],
            prompt_tokens=_opt_int("prompt_tokens"),
            completion_tokens=_opt_int("completion_tokens"),
        )
