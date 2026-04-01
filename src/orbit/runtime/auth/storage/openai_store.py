"""Repo-local OpenAI OAuth credential persistence for ORBIT."""

from __future__ import annotations

import json
from pathlib import Path

from orbit.runtime.auth.storage.openai import OpenAIOAuthCredential

DEFAULT_OPENAI_AUTH_STORE_PATH = Path(".runtime/openai_oauth_credentials.json")


class OpenAIAuthStoreError(RuntimeError):
    """Raised when ORBIT cannot load or save its local OpenAI auth store."""


class OpenAIAuthStore:
    """Persist OpenAI OAuth credentials inside ORBIT's repo-local runtime area."""

    def __init__(self, repo_root: Path, relative_path: Path = DEFAULT_OPENAI_AUTH_STORE_PATH):
        self.repo_root = repo_root
        self.relative_path = relative_path

    @property
    def file_path(self) -> Path:
        return self.repo_root / self.relative_path

    def save(self, credential: OpenAIOAuthCredential) -> Path:
        self.file_path.parent.mkdir(parents=True, exist_ok=True)
        self.file_path.write_text(
            json.dumps(
                {
                    "access_token": credential.access_token,
                    "refresh_token": credential.refresh_token,
                    "expires_at_epoch_ms": credential.expires_at_epoch_ms,
                    "account_email": credential.account_email,
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return self.file_path

    def load(self) -> OpenAIOAuthCredential:
        if not self.file_path.exists():
            raise OpenAIAuthStoreError(f"OpenAI auth store not found at {self.file_path}")
        try:
            data = json.loads(self.file_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise OpenAIAuthStoreError(f"OpenAI auth store is not valid JSON: {exc}") from exc
        try:
            return OpenAIOAuthCredential(
                access_token=str(data["access_token"]),
                refresh_token=str(data["refresh_token"]),
                expires_at_epoch_ms=int(data["expires_at_epoch_ms"]),
                account_email=str(data["account_email"]) if data.get("account_email") is not None else None,
            )
        except Exception as exc:
            raise OpenAIAuthStoreError(f"OpenAI auth store is missing required fields: {exc}") from exc
