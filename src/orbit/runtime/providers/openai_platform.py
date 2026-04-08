"""OpenAI OAuth execution backend scaffold for ORBIT.

This module intentionally implements only the narrowest first step toward live
provider integration. Its current purpose is to define the code location and
basic interface shape for the first real provider-backed backend without yet
pulling the runtime into full provider complexity.

Current scope:
- reserve the backend class and configuration surface
- define the first request/response contract shape
- define the first auth-material contract shape
- support local persisted credential reuse during bring-up
- execute one non-streaming first HTTP call
- keep normalization explicit and local

Out of scope for this first scaffold:
- full authentication UX
- streaming
- advanced tool calling
- broad provider feature coverage
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from orbit.runtime.auth.storage.openai import OpenAIOAuthCredential, ResolvedOpenAIAuthMaterial, resolve_openai_auth_material
from orbit.runtime.auth.oauth.openai_handshake import OpenAIOAuthHandshakeResult, persist_manual_oauth_credential, persist_manual_oauth_credential_from_json
from orbit.runtime.auth.oauth.openai_oauth_exchange import exchange_callback_input_and_persist
from orbit.runtime.auth.oauth.openai_oauth_pkce import OpenAIOAuthPkceSession, create_openai_oauth_pkce_session
from orbit.runtime.auth.storage.openai_store import OpenAIAuthStore
from orbit.runtime.execution.backends import ExecutionBackend
from orbit.runtime.core.contracts import RunDescriptor
from orbit.runtime.execution.normalization import ProviderFailure, ProviderNormalizedResult, normalized_result_to_execution_plan
from orbit.runtime.execution.contracts.openai_contracts import OpenAIFirstRawResponse, OpenAIFirstRequest, OpenAIRawOutputItem
from orbit.runtime.execution.contracts.plans import ExecutionPlan
from orbit.runtime.transports.openai_platform_http import OpenAIHttpTransportError, post_openai_platform_json


@dataclass
class OpenAIOAuthConfig:
    """Minimal configuration scaffold for the OpenAI OAuth backend."""

    model: str = "gpt-5"
    api_base: str = "https://api.openai.com/v1"
    timeout_seconds: int = 60


class OpenAIOAuthExecutionBackend(ExecutionBackend):
    """Narrow first scaffold for OpenAI OAuth-backed execution.

    This backend intentionally stops at the point where ORBIT can reserve the
    correct integration shape. The first real implementation step should focus
    on a single, non-streaming interaction path that normalizes provider output
    into ORBIT's generic execution plan.
    """

    backend_name = "openai-oauth"

    def __init__(self, config: OpenAIOAuthConfig | None = None, repo_root: Path | None = None):
        """Initialize the OpenAI OAuth backend scaffold with minimal config."""
        self.config = config or OpenAIOAuthConfig()
        self.repo_root = repo_root or Path.cwd()
        self.auth_store = OpenAIAuthStore(self.repo_root)

    def create_pkce_handshake_session(self, originator: str = "pi") -> OpenAIOAuthPkceSession:
        """Create a browser-openable PKCE handshake session for OpenAI OAuth."""
        return create_openai_oauth_pkce_session(originator=originator)

    def exchange_callback_input(self, *, pkce_session: OpenAIOAuthPkceSession, callback_input: str) -> OpenAIOAuthHandshakeResult:
        """Exchange pasted callback input into a persisted ORBIT OAuth credential."""
        return exchange_callback_input_and_persist(
            repo_root=self.repo_root,
            pkce_session=pkce_session,
            callback_input=callback_input,
            timeout_seconds=self.config.timeout_seconds,
        )

    def bootstrap_persisted_credential(self, *, access_token: str, refresh_token: str, expires_at_epoch_ms: int, account_email: str | None = None) -> OpenAIOAuthHandshakeResult:
        """Persist a manually supplied OAuth credential for immediate bring-up use."""
        return persist_manual_oauth_credential(
            repo_root=self.repo_root,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_at_epoch_ms=expires_at_epoch_ms,
            account_email=account_email,
        )

    def bootstrap_persisted_credential_from_json(self, json_text: str) -> OpenAIOAuthHandshakeResult:
        """Persist a manually supplied OAuth credential JSON blob."""
        return persist_manual_oauth_credential_from_json(repo_root=self.repo_root, json_text=json_text)

    def plan(self, descriptor: RunDescriptor) -> ExecutionPlan:
        """Execute the narrowest possible first real OpenAI OAuth interaction path."""
        credential = self.load_persisted_credential()
        auth = self.resolve_auth_material(credential)
        request = self.build_first_request(descriptor)
        payload = self.build_first_request_payload(request)
        headers = self.build_first_request_headers(auth)
        url = self.build_first_request_url()
        try:
            response = post_openai_platform_json(url=url, headers=headers, payload=payload, timeout_seconds=self.config.timeout_seconds)
        except OpenAIHttpTransportError as exc:
            normalized = ProviderNormalizedResult(
                source_backend=self.backend_name,
                plan_label="openai-responses-transport-failure",
                failure=ProviderFailure(kind="transport_error", message=str(exc)),
            )
            return normalized_result_to_execution_plan(normalized)
        raw = self.parse_first_raw_response(response.json_body)
        return self.normalize_first_response(raw)

    def load_persisted_credential(self) -> OpenAIOAuthCredential:
        return self.auth_store.load_fresh()

    def save_persisted_credential(self, credential: OpenAIOAuthCredential) -> Path:
        return self.auth_store.save(credential)

    def resolve_auth_material(self, credential: OpenAIOAuthCredential) -> ResolvedOpenAIAuthMaterial:
        return resolve_openai_auth_material(credential)

    def build_first_request(self, descriptor: RunDescriptor) -> OpenAIFirstRequest:
        return OpenAIFirstRequest(
            model=self.config.model,
            instructions="You are ORBIT's first hosted-provider validation path. Return a direct helpful answer.",
            input_text=descriptor.user_input,
            metadata={"run_id": descriptor.run_id, "session_key": descriptor.session_key, "conversation_id": descriptor.conversation_id},
        )

    def build_first_request_payload(self, request: OpenAIFirstRequest) -> dict:
        payload = {"model": request.model, "input": request.input_text}
        if request.instructions:
            payload["instructions"] = request.instructions
        if request.max_output_tokens is not None:
            payload["max_output_tokens"] = request.max_output_tokens
        if request.metadata:
            payload["metadata"] = request.metadata
        return payload

    def build_first_request_headers(self, auth: ResolvedOpenAIAuthMaterial) -> dict[str, str]:
        return {"Authorization": f"Bearer {auth.bearer_token}", "Content-Type": "application/json"}

    def build_first_request_url(self) -> str:
        return self.config.api_base.rstrip("/") + "/responses"

    def parse_first_raw_response(self, payload: dict) -> OpenAIFirstRawResponse:
        output_items: list[OpenAIRawOutputItem] = []
        raw_output = payload.get("output")
        if isinstance(raw_output, list):
            for item in raw_output:
                if not isinstance(item, dict):
                    continue
                text_value = None
                content = item.get("content")
                if isinstance(content, list):
                    text_parts: list[str] = []
                    for part in content:
                        if isinstance(part, dict) and isinstance(part.get("text"), str):
                            text_parts.append(part["text"])
                    if text_parts:
                        text_value = "\n".join(text_parts)
                output_items.append(OpenAIRawOutputItem(item_type=str(item.get("type", "unknown")), text=text_value, raw_payload=item))
        raw_text = payload.get("output_text")
        if not isinstance(raw_text, str) or not raw_text.strip():
            joined_texts = [item.text for item in output_items if item.text]
            raw_text = "\n".join(joined_texts) if joined_texts else None
        return OpenAIFirstRawResponse(
            response_id=payload.get("id") if isinstance(payload.get("id"), str) else None,
            model=payload.get("model") if isinstance(payload.get("model"), str) else None,
            output_items=output_items,
            raw_text=raw_text,
            finish_reason=payload.get("status") if isinstance(payload.get("status"), str) else None,
            usage=payload.get("usage") if isinstance(payload.get("usage"), dict) else {},
            raw_payload=payload,
        )

    def normalize_first_response(self, response: OpenAIFirstRawResponse) -> ExecutionPlan:
        if response.raw_text and response.raw_text.strip():
            normalized = ProviderNormalizedResult(
                source_backend=self.backend_name,
                plan_label="openai-responses-final-text",
                final_text=response.raw_text.strip(),
                metadata={"response_id": response.response_id, "model": response.model, "finish_reason": response.finish_reason, "usage": response.usage},
            )
            return normalized_result_to_execution_plan(normalized)
        normalized = ProviderNormalizedResult(
            source_backend=self.backend_name,
            plan_label="openai-responses-malformed-response",
            failure=ProviderFailure(kind="malformed_response", message="OpenAI response did not contain extractable final text"),
            metadata={"response_id": response.response_id, "model": response.model, "finish_reason": response.finish_reason},
        )
        return normalized_result_to_execution_plan(normalized)
