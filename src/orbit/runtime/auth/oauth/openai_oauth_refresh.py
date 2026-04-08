"""Refresh-token flow for ORBIT's persisted OpenAI OAuth credential."""

from __future__ import annotations

import json
import time
from urllib.request import Request, urlopen
from urllib.error import HTTPError

from orbit.runtime.auth.oauth.openai_oauth_pkce import OPENAI_OAUTH_CLIENT_ID, OPENAI_OAUTH_TOKEN_URL
from orbit.runtime.auth.storage.openai import OpenAIOAuthCredential


class OpenAIRefreshError(RuntimeError):
    """Raised when the refresh-token exchange fails."""


def refresh_openai_credential(credential: OpenAIOAuthCredential) -> OpenAIOAuthCredential:
    """Exchange a refresh token for a new access token and return the updated credential.

    Writes nothing to disk — callers are responsible for persisting the result.
    """
    if not credential.refresh_token.strip():
        raise OpenAIRefreshError("credential has no refresh token — cannot refresh")

    payload = json.dumps({
        "grant_type": "refresh_token",
        "client_id": OPENAI_OAUTH_CLIENT_ID,
        "refresh_token": credential.refresh_token,
    }).encode("utf-8")

    request = Request(
        OPENAI_OAUTH_TOKEN_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urlopen(request, timeout=30) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        raise OpenAIRefreshError(f"token refresh failed ({exc.code}): {body}") from exc
    except Exception as exc:
        raise OpenAIRefreshError(f"token refresh request error: {exc}") from exc

    access_token = data.get("access_token")
    if not access_token:
        raise OpenAIRefreshError(f"refresh response missing access_token: {data}")

    # Resolve expiry: prefer expires_at (epoch s) over expires_in (seconds from now)
    if data.get("expires_at"):
        expires_at_epoch_ms = int(data["expires_at"]) * 1000
    elif data.get("expires_in"):
        expires_at_epoch_ms = int((time.time() + int(data["expires_in"])) * 1000)
    else:
        # fallback: 1 hour
        expires_at_epoch_ms = int((time.time() + 3600) * 1000)

    return OpenAIOAuthCredential(
        access_token=str(access_token),
        refresh_token=str(data.get("refresh_token") or credential.refresh_token),
        expires_at_epoch_ms=expires_at_epoch_ms,
        account_email=credential.account_email,
    )
