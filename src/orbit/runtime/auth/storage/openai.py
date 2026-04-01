"""OpenAI auth-material contract helpers for ORBIT."""

from __future__ import annotations

from dataclasses import dataclass
import time


@dataclass
class OpenAIOAuthCredential:
    """Persisted OAuth credential state used for local ORBIT debug bring-up."""

    access_token: str
    refresh_token: str
    expires_at_epoch_ms: int
    account_email: str | None = None


@dataclass
class ResolvedOpenAIAuthMaterial:
    """Request-facing auth material derived from stored OAuth credential state."""

    bearer_token: str
    expires_at_epoch_ms: int
    account_email: str | None = None
    source: str = "persisted_oauth_credential"


class OpenAIAuthResolutionError(RuntimeError):
    """Raised when ORBIT cannot resolve valid OpenAI auth material."""


def resolve_openai_auth_material(credential: OpenAIOAuthCredential) -> ResolvedOpenAIAuthMaterial:
    """Resolve stored OAuth credential state into request-facing auth material."""
    if not credential.access_token.strip():
        raise OpenAIAuthResolutionError("OpenAI OAuth credential is missing an access token")
    now_ms = int(time.time() * 1000)
    if credential.expires_at_epoch_ms <= now_ms:
        raise OpenAIAuthResolutionError("OpenAI OAuth access token is expired; refresh flow is not implemented yet")
    return ResolvedOpenAIAuthMaterial(
        bearer_token=credential.access_token,
        expires_at_epoch_ms=credential.expires_at_epoch_ms,
        account_email=credential.account_email,
    )
