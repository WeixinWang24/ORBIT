"""Notebook display helpers for OpenAI OAuth handshake steps."""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from orbit.runtime.providers.openai_platform import OpenAIOAuthExecutionBackend


def create_openai_login_url_bundle(*, repo_root: Path, originator: str = "pi") -> dict:
    """Create a notebook-friendly bundle for the OpenAI OAuth login step."""
    backend = OpenAIOAuthExecutionBackend(repo_root=repo_root)
    session = backend.create_pkce_handshake_session(originator=originator)
    return {
        "backend_name": backend.backend_name,
        "originator": session.originator,
        "authorize_url": session.authorize_url,
        "state": session.state,
        "code_verifier": session.code_verifier,
        "code_challenge": session.code_challenge,
        "redirect_uri": session.redirect_uri,
    }


def openai_login_url_summary_frame(bundle: dict) -> pd.DataFrame:
    """Render the notebook login bundle as a compact single-row table."""
    return pd.DataFrame([{k: v for k, v in bundle.items() if k != "authorize_url"}])
