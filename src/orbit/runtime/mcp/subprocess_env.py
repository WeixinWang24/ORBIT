from __future__ import annotations

import os

_EXPLICIT_SCRUB_KEYS = {
    "ANTHROPIC_API_KEY",
    "CLAUDE_CODE_OAUTH_TOKEN",
    "ANTHROPIC_AUTH_TOKEN",
    "ANTHROPIC_FOUNDRY_API_KEY",
    "ANTHROPIC_CUSTOM_HEADERS",
    "OPENAI_API_KEY",
    "OPENAI_ORG_ID",
    "OPENAI_ORGANIZATION",
    "OPENAI_PROJECT",
    "OPENROUTER_API_KEY",
    "PERPLEXITY_API_KEY",
    "XAI_API_KEY",
    "GEMINI_API_KEY",
    "MISTRAL_API_KEY",
    "OTEL_EXPORTER_OTLP_HEADERS",
    "OTEL_EXPORTER_OTLP_LOGS_HEADERS",
    "OTEL_EXPORTER_OTLP_METRICS_HEADERS",
    "OTEL_EXPORTER_OTLP_TRACES_HEADERS",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_BEARER_TOKEN_BEDROCK",
    "GOOGLE_APPLICATION_CREDENTIALS",
    "AZURE_CLIENT_SECRET",
    "AZURE_CLIENT_CERTIFICATE_PATH",
    "ACTIONS_ID_TOKEN_REQUEST_TOKEN",
    "ACTIONS_ID_TOKEN_REQUEST_URL",
    "ACTIONS_RUNTIME_TOKEN",
    "ACTIONS_RUNTIME_URL",
    "ALL_INPUTS",
    "OVERRIDE_GITHUB_TOKEN",
    "DEFAULT_WORKFLOW_TOKEN",
    "SSH_SIGNING_KEY",
}

_SENSITIVE_SUFFIXES = (
    "_API_KEY",
    "_AUTH_TOKEN",
    "_TOKEN",
    "_SECRET",
    "_SECRET_ACCESS_KEY",
    "_CREDENTIALS",
    "_CERTIFICATE_PATH",
    "_PRIVATE_KEY",
)


def should_scrub_subprocess_env_key(key: str) -> bool:
    normalized = key.strip().upper()
    if not normalized:
        return False
    if normalized in _EXPLICIT_SCRUB_KEYS:
        return True
    if normalized.startswith("INPUT_") and normalized[6:] in _EXPLICIT_SCRUB_KEYS:
        return True
    if normalized.endswith(_SENSITIVE_SUFFIXES):
        return True
    if normalized.startswith("INPUT_") and normalized[6:].endswith(_SENSITIVE_SUFFIXES):
        return True
    return False


def build_scrubbed_subprocess_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    for key in list(env.keys()):
        if should_scrub_subprocess_env_key(key):
            env.pop(key, None)
    return env
