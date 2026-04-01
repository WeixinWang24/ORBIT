"""Minimal JSON HTTP transport for the official OpenAI Platform route."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


@dataclass
class OpenAIHttpResponse:
    status_code: int
    json_body: dict
    raw_text: str


class OpenAIHttpTransportError(RuntimeError):
    """Raised when ORBIT cannot complete the first OpenAI HTTP call."""


def post_openai_platform_json(*, url: str, headers: dict[str, str], payload: dict, timeout_seconds: int = 60) -> OpenAIHttpResponse:
    body = json.dumps(payload).encode("utf-8")
    request = Request(url=url, data=body, headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_text = response.read().decode("utf-8")
            json_body = json.loads(raw_text)
            return OpenAIHttpResponse(status_code=response.status, json_body=json_body, raw_text=raw_text)
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise OpenAIHttpTransportError(f"OpenAI HTTP error {exc.code}: {error_text}") from exc
    except URLError as exc:
        raise OpenAIHttpTransportError(f"OpenAI connection error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise OpenAIHttpTransportError(f"OpenAI returned non-JSON response: {exc}") from exc
