"""PKCE helper utilities for the first OpenAI OAuth browser handshake."""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from urllib.parse import urlencode

OPENAI_OAUTH_AUTHORIZE_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_OAUTH_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_OAUTH_REDIRECT_URI = "http://localhost:1455/auth/callback"
OPENAI_OAUTH_SCOPE = "openid profile email offline_access"


def generate_pkce_verifier(length_bytes: int = 48) -> str:
    return secrets.token_urlsafe(length_bytes)


def generate_pkce_challenge(verifier: str) -> str:
    digest = hashlib.sha256(verifier.encode("utf-8")).digest()
    return base64.urlsafe_b64encode(digest).decode("utf-8").rstrip("=")


@dataclass
class OpenAIOAuthPkceSession:
    originator: str
    state: str
    code_verifier: str
    code_challenge: str
    authorize_url: str
    redirect_uri: str = OPENAI_OAUTH_REDIRECT_URI
    client_id: str = OPENAI_OAUTH_CLIENT_ID
    scope: str = OPENAI_OAUTH_SCOPE
    authorize_url_base: str = OPENAI_OAUTH_AUTHORIZE_URL
    token_url: str = OPENAI_OAUTH_TOKEN_URL


def create_openai_oauth_pkce_session(originator: str = "pi") -> OpenAIOAuthPkceSession:
    state = secrets.token_urlsafe(24)
    code_verifier = generate_pkce_verifier()
    code_challenge = generate_pkce_challenge(code_verifier)
    query = urlencode({
        "response_type": "code",
        "client_id": OPENAI_OAUTH_CLIENT_ID,
        "redirect_uri": OPENAI_OAUTH_REDIRECT_URI,
        "scope": OPENAI_OAUTH_SCOPE,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "state": state,
        "originator": originator,
    })
    return OpenAIOAuthPkceSession(originator=originator, state=state, code_verifier=code_verifier, code_challenge=code_challenge, authorize_url=f"{OPENAI_OAUTH_AUTHORIZE_URL}?{query}")
