"""Observation data models for session tracking."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SessionObservation:
    """A single observed MCP tool invocation within a session."""

    id: int = 0
    session_id: str = ""
    tool_name: str = ""
    arguments_hash: str = ""  # SHA256[:16] of sanitized args (privacy-safe)
    result_summary: str = ""  # First 500 chars of result (no paper text)
    success: bool = True
    cost_usd: float = 0.0
    latency_ms: int = 0
    stage: str = ""
    gate_outcome: str = ""
    user_intervention: bool = False  # Did user override/correct after this call?
    created_at: str = ""


@dataclass
class SessionSummary:
    """Aggregated summary of a session's tool usage patterns."""

    session_id: str = ""
    tool_sequence: list[str] = field(default_factory=list)
    total_tools: int = 0
    total_cost_usd: float = 0.0
    total_latency_ms: int = 0
    success_rate: float = 1.0
    stages_visited: list[str] = field(default_factory=list)
    user_interventions: int = 0
