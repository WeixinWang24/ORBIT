"""First-slice data models for context usage accounting in ORBIT.

This module lives on the Operation Surface: it is runtime observability
infrastructure, not a Knowledge Surface concern.

Tracks observed token usage per provider call and cumulatively across
session turns.

Out of scope for this first slice:
- preflight estimates
- context window size / remaining percentage
- per-source breakdown
- budget warnings
"""

from __future__ import annotations

from orbit.models.core import OrbitBaseModel


class ModelCallUsage(OrbitBaseModel):
    """Observed token usage for a single provider call."""

    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int = 0
    cache_read_input_tokens: int = 0
    reasoning_tokens: int = 0
    provider: str = ""
    model: str = ""


class SessionUsageTotals(OrbitBaseModel):
    """Cumulative token usage across all observed provider calls in a session."""

    total_input_tokens: int = 0
    total_output_tokens: int = 0
    total_cache_creation_input_tokens: int = 0
    total_cache_read_input_tokens: int = 0
    total_reasoning_tokens: int = 0
    call_count: int = 0


class ContextUsageSnapshot(OrbitBaseModel):
    """Combined snapshot of latest call usage and cumulative session totals."""

    latest_call: ModelCallUsage | None = None
    totals: SessionUsageTotals = SessionUsageTotals()
