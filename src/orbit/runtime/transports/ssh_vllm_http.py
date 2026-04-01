"""Minimal JSON HTTP transport for the SSH/OpenAI-compatible vLLM route."""

from __future__ import annotations

import json
from dataclasses import dataclass
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from orbit.runtime.transports.ssh_tunnel import SshTunnelConfig, SshTunnelError, SshTunnelManager


@dataclass
class SshVllmHttpResponse:
    status_code: int
    json_body: dict
    raw_text: str


class SshVllmHttpError(RuntimeError):
    """Raised when ORBIT cannot complete an SSH vLLM HTTP request."""


_DEFAULT_TUNNEL_MANAGER = SshTunnelManager()



def get_ssh_vllm_json(*, url: str, headers: dict[str, str], timeout_seconds: int = 3) -> SshVllmHttpResponse:
    request = Request(url=url, headers=headers, method="GET")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_text = response.read().decode("utf-8")
            json_body = json.loads(raw_text)
            return SshVllmHttpResponse(status_code=response.status, json_body=json_body, raw_text=raw_text)
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise SshVllmHttpError(f"SSH vLLM HTTP error {exc.code}: {error_text}") from exc
    except URLError as exc:
        raise SshVllmHttpError(f"SSH vLLM connection error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SshVllmHttpError(f"SSH vLLM returned non-JSON response: {exc}") from exc



def ssh_vllm_endpoint_is_reachable(*, base_url: str, headers: dict[str, str], timeout_seconds: int = 3) -> bool:
    probe_url = base_url.rstrip("/") + "/models"
    try:
        get_ssh_vllm_json(url=probe_url, headers=headers, timeout_seconds=timeout_seconds)
        return True
    except SshVllmHttpError:
        return False



def ensure_ssh_vllm_endpoint(*, base_url: str, headers: dict[str, str], auto_tunnel: bool = False, tunnel_config: SshTunnelConfig | None = None, timeout_seconds: int = 3, tunnel_manager: SshTunnelManager | None = None) -> str:
    if ssh_vllm_endpoint_is_reachable(base_url=base_url, headers=headers, timeout_seconds=timeout_seconds):
        return base_url

    if not auto_tunnel:
        raise SshVllmHttpError("SSH vLLM endpoint is unreachable and auto_tunnel is disabled.")
    if tunnel_config is None:
        raise SshVllmHttpError("SSH vLLM endpoint is unreachable and no tunnel configuration was supplied.")

    manager = tunnel_manager or _DEFAULT_TUNNEL_MANAGER
    try:
        local_base = manager.ensure_tunnel(tunnel_config)
    except SshTunnelError as exc:
        raise SshVllmHttpError(f"SSH vLLM auto-tunnel rebuild failed: {exc}") from exc

    rebuilt_base_url = local_base.rstrip("/") + "/v1"
    if ssh_vllm_endpoint_is_reachable(base_url=rebuilt_base_url, headers=headers, timeout_seconds=timeout_seconds):
        return rebuilt_base_url

    raise SshVllmHttpError("SSH vLLM endpoint is still unreachable after auto-tunnel rebuild.")



def post_ssh_vllm_json(*, url: str, headers: dict[str, str], payload: dict, timeout_seconds: int = 60) -> SshVllmHttpResponse:
    request = Request(url=url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            raw_text = response.read().decode("utf-8")
            json_body = json.loads(raw_text)
            return SshVllmHttpResponse(status_code=response.status, json_body=json_body, raw_text=raw_text)
    except HTTPError as exc:
        error_text = exc.read().decode("utf-8", errors="replace")
        raise SshVllmHttpError(f"SSH vLLM HTTP error {exc.code}: {error_text}") from exc
    except URLError as exc:
        raise SshVllmHttpError(f"SSH vLLM connection error: {exc}") from exc
    except json.JSONDecodeError as exc:
        raise SshVllmHttpError(f"SSH vLLM returned non-JSON response: {exc}") from exc
