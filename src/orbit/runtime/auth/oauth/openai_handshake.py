"""Helpers for persisting manually bootstrapped OpenAI OAuth credentials."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from orbit.runtime.auth.storage.openai import OpenAIOAuthCredential
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStore


class OpenAIOAuthHandshakeError(RuntimeError):
    """Raised when ORBIT cannot complete a local handshake/bootstrap step."""


@dataclass
class OpenAIOAuthHandshakeResult:
    credential_path: str
    account_email: str | None
    expires_at_epoch_ms: int
    source: str


def persist_manual_oauth_credential(*, repo_root: Path, access_token: str, refresh_token: str, expires_at_epoch_ms: int, account_email: str | None = None) -> OpenAIOAuthHandshakeResult:
    store = OpenAIAuthStore(repo_root)
    store.save(OpenAIOAuthCredential(access_token=access_token, refresh_token=refresh_token, expires_at_epoch_ms=expires_at_epoch_ms, account_email=account_email))
    return OpenAIOAuthHandshakeResult(credential_path=str(store.file_path), account_email=account_email, expires_at_epoch_ms=expires_at_epoch_ms, source="manual")


def persist_manual_oauth_credential_from_json(*, repo_root: Path, json_text: str) -> OpenAIOAuthHandshakeResult:
    try:
        payload = json.loads(json_text)
    except json.JSONDecodeError as exc:
        raise OpenAIOAuthHandshakeError(f"Invalid JSON for manual OAuth credential: {exc}") from exc
    return persist_manual_oauth_credential(
        repo_root=repo_root,
        access_token=str(payload["access_token"]),
        refresh_token=str(payload["refresh_token"]),
        expires_at_epoch_ms=int(payload["expires_at_epoch_ms"]),
        account_email=str(payload["account_email"]) if payload.get("account_email") is not None else None,
    )
