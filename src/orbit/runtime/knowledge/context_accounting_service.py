"""Context usage accounting service for ORBIT first-slice token tracking.

This service is the single owner of context usage normalization, recording,
and projection. It is runtime- and provider-neutral: callers pass raw usage
dicts from plan metadata; this service normalizes, accumulates, and persists.

Out of scope for this first slice:
- preflight estimation
- context window percentage
- per-source breakdown
- budget warnings or blocking
"""

from __future__ import annotations

from datetime import datetime, timezone

from orbit.runtime.knowledge.context_models import (
    ContextUsageSnapshot,
    ModelCallUsage,
    SessionUsageTotals,
)


class ContextAccountingService:
    """Normalize and record observed provider usage into session metadata.

    Designed to be instantiated per-call or as a lightweight singleton;
    it holds no state itself — all state lives in session.metadata["context_usage"].
    """

    # Stable key under session.metadata where usage is persisted.
    METADATA_KEY = "context_usage"

    def normalize_provider_usage(
        self,
        *,
        usage: dict | None,
        provider: str = "",
        model: str = "",
    ) -> ModelCallUsage | None:
        """Normalize a raw provider usage dict into a ModelCallUsage.

        Tolerates both naming styles:
        - OpenAI Responses API: input_tokens / output_tokens
        - OpenAI Chat Completions: prompt_tokens / completion_tokens
        - Extended: cache_creation_input_tokens, cache_read_input_tokens, reasoning_tokens

        Returns None when usage is absent or empty so callers can skip recording.
        """
        if not usage or not isinstance(usage, dict):
            return None

        input_tokens = (
            usage.get("input_tokens")
            or usage.get("prompt_tokens")
            or 0
        )
        output_tokens = (
            usage.get("output_tokens")
            or usage.get("completion_tokens")
            or 0
        )

        # No tokens at all — treat as absent.
        if not input_tokens and not output_tokens:
            return None

        return ModelCallUsage(
            input_tokens=int(input_tokens),
            output_tokens=int(output_tokens),
            cache_creation_input_tokens=int(usage.get("cache_creation_input_tokens") or 0),
            cache_read_input_tokens=int(usage.get("cache_read_input_tokens") or 0),
            reasoning_tokens=int(usage.get("reasoning_tokens") or 0),
            provider=provider,
            model=model,
        )

    def record_observed_usage(
        self,
        *,
        session,
        call_usage: ModelCallUsage,
        store,
    ) -> None:
        """Update session.metadata["context_usage"] with a new observed call.

        Accumulates cumulative totals in place and persists the session.
        """
        existing = self._load_usage_block(session)
        totals = existing.totals

        # Accumulate
        totals = SessionUsageTotals(
            total_input_tokens=totals.total_input_tokens + call_usage.input_tokens,
            total_output_tokens=totals.total_output_tokens + call_usage.output_tokens,
            total_cache_creation_input_tokens=totals.total_cache_creation_input_tokens + call_usage.cache_creation_input_tokens,
            total_cache_read_input_tokens=totals.total_cache_read_input_tokens + call_usage.cache_read_input_tokens,
            total_reasoning_tokens=totals.total_reasoning_tokens + call_usage.reasoning_tokens,
            call_count=totals.call_count + 1,
        )

        snapshot = ContextUsageSnapshot(latest_call=call_usage, totals=totals)
        session.metadata[self.METADATA_KEY] = snapshot.model_dump(mode="json")
        session.updated_at = datetime.now(timezone.utc)
        store.save_session(session)

    def get_usage_snapshot(self, *, session) -> ContextUsageSnapshot:
        """Return the current usage snapshot for a session."""
        return self._load_usage_block(session)

    def build_status_projection(self, *, session) -> dict:
        """Return a status-surface-safe projection dict from the current snapshot.

        Consumers (e.g. runtime adapters) should call this instead of
        reading session metadata directly, to keep accounting logic contained.
        """
        snapshot = self.get_usage_snapshot(session=session)
        latest = snapshot.latest_call
        totals = snapshot.totals
        return {
            "latest_call": latest.model_dump(mode="json") if latest is not None else None,
            "totals": totals.model_dump(mode="json"),
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _load_usage_block(self, session) -> ContextUsageSnapshot:
        """Deserialize the stored usage block, defaulting to empty snapshot."""
        raw = session.metadata.get(self.METADATA_KEY) if isinstance(session.metadata, dict) else None
        if not isinstance(raw, dict):
            return ContextUsageSnapshot()
        try:
            return ContextUsageSnapshot.model_validate(raw)
        except Exception:
            return ContextUsageSnapshot()
