"""Exchange pasted OpenAI OAuth callback input into a persisted credential."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

from orbit.runtime.auth.oauth.openai_handshake import OpenAIOAuthHandshakeResult, persist_manual_oauth_credential
from orbit.runtime.auth.oauth.openai_oauth_pkce import OPENAI_OAUTH_CLIENT_ID, OPENAI_OAUTH_REDIRECT_URI, OPENAI_OAUTH_TOKEN_URL, OpenAIOAuthPkceSession


class OpenAIOAuthExchangeError(RuntimeError):
    """Raised when callback parsing or token exchange fails."""


@dataclass
class ParsedOpenAICallback:
    code: str
    state: str | None


def parse_openai_callback_input(callback_input: str) -> ParsedOpenAICallback:
    text = callback_input.strip()
    if not text:
        raise OpenAIOAuthExchangeError("callback input is empty")
    if text.startswith("http://") or text.startswith("https://"):
        parsed = urlparse(text)
        query = parse_qs(parsed.query)
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
    elif "code=" in text:
        query = parse_qs(text.lstrip("?"))
        code = query.get("code", [None])[0]
        state = query.get("state", [None])[0]
    else:
        code = text
        state = None
    if not code:
        raise OpenAIOAuthExchangeError("could not extract authorization code from callback input")
    return ParsedOpenAICallback(code=code, state=state)


def exchange_openai_authorization_code(*, pkce_session: OpenAIOAuthPkceSession, code: str, timeout_seconds: int = 60) -> dict:
    payload = json.dumps({
        "grant_type": "authorization_code",
        "client_id": OPENAI_OAUTH_CLIENT_ID,
        "redirect_uri": OPENAI_OAUTH_REDIRECT_URI,
        "code": code,
        "code_verifier": pkce_session.code_verifier,
    }).encode("utf-8")
    request = Request(OPENAI_OAUTH_TOKEN_URL, data=payload, headers={"Content-Type": "application/json"}, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        raise OpenAIOAuthExchangeError(f"OpenAI OAuth token exchange failed: {exc}") from exc


def exchange_callback_input_and_persist(*, repo_root: Path, pkce_session: OpenAIOAuthPkceSession, callback_input: str, timeout_seconds: int = 60) -> OpenAIOAuthHandshakeResult:
    parsed = parse_openai_callback_input(callback_input)
    if parsed.state and parsed.state != pkce_session.state:
        raise OpenAIOAuthExchangeError("callback state did not match the PKCE session state")
    token_payload = exchange_openai_authorization_code(pkce_session=pkce_session, code=parsed.code, timeout_seconds=timeout_seconds)
    return persist_manual_oauth_credential(
        repo_root=repo_root,
        access_token=str(token_payload["access_token"]),
        refresh_token=str(token_payload["refresh_token"]),
        expires_at_epoch_ms=int(token_payload.get("expires_at") or 0) * 1000 if token_payload.get("expires_at") else int(token_payload["expires_in"]) * 1000,
        account_email=(token_payload.get("email") if isinstance(token_payload.get("email"), str) else None),
    )
