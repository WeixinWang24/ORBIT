"""Provider-agnostic prompt/context assembly for ORBIT's active runtime."""

from __future__ import annotations

import hashlib
from pathlib import Path

from pydantic import Field

from orbit.models import ConversationMessage
from orbit.models.core import OrbitBaseModel

PROMPT_ASSEMBLY_VERSION = "prompt_assembly_plan_v1"


class ContextFragment(OrbitBaseModel):
    fragment_name: str
    visibility_scope: str
    content: str
    priority: int = 0
    metadata: dict = Field(default_factory=dict)


class PromptAssemblyPlan(OrbitBaseModel):
    source_backend: str
    model: str
    instruction_fragments: list[ContextFragment] = Field(default_factory=list)
    transcript_messages: list[ConversationMessage] = Field(default_factory=list)
    history_context_fragments: list[ContextFragment] = Field(default_factory=list)
    auxiliary_context_fragments: list[ContextFragment] = Field(default_factory=list)
    runtime_only_fragments: list[ContextFragment] = Field(default_factory=list)
    projection_hints: dict = Field(default_factory=dict)

    @property
    def effective_instructions(self) -> str:
        parts = [fragment.content.strip() for fragment in self.instruction_fragments if fragment.content.strip()]
        return "\n\n".join(parts)

    def to_snapshot_dict(self) -> dict:
        workspace_fragment = next((fragment for fragment in self.instruction_fragments if fragment.fragment_name == "project_workspace"), None)
        return {
            "assembly_version": PROMPT_ASSEMBLY_VERSION,
            "backend": self.source_backend,
            "model": self.model,
            "workspace_prompt_source": workspace_fragment.metadata.get("source_file") if workspace_fragment else None,
            "workspace_prompt_sha1": workspace_fragment.metadata.get("content_sha1") if workspace_fragment else None,
            "instruction_fragments": [fragment.model_dump(mode="json") for fragment in self.instruction_fragments],
            "history_context_fragments": [fragment.model_dump(mode="json") for fragment in self.history_context_fragments],
            "auxiliary_context_fragments": [fragment.model_dump(mode="json") for fragment in self.auxiliary_context_fragments],
            "runtime_only_fragments": [fragment.model_dump(mode="json") for fragment in self.runtime_only_fragments],
            "projection_hints": self.projection_hints,
            "effective_instructions": self.effective_instructions,
            "projected_input": [
                {
                    "role": getattr(message.role, "value", str(message.role)),
                    "content": message.content,
                    "turn_index": message.turn_index,
                    "metadata": message.metadata,
                }
                for message in self.transcript_messages
            ],
        }


def _load_workspace_prompt(workspace_root: str | None) -> ContextFragment | None:
    if not workspace_root:
        return None
    candidate = Path(workspace_root) / "PROMPT.md"
    if not candidate.exists():
        return None
    content = candidate.read_text(encoding="utf-8").strip()
    if not content:
        return None
    return ContextFragment(
        fragment_name="project_workspace",
        visibility_scope="runtime",
        content=content,
        priority=90,
        metadata={
            "source_file": str(candidate),
            "content_sha1": hashlib.sha1(content.encode("utf-8")).hexdigest(),
        },
    )


def build_text_only_prompt_assembly_plan(*, backend_name: str, model: str, messages: list[ConversationMessage], workspace_root: str | None = None, memory_fragments: list[ContextFragment] | None = None) -> PromptAssemblyPlan:
    instruction_fragments = [
        ContextFragment(
            fragment_name="identity_charter",
            visibility_scope="runtime",
            content="You are ORBIT's hosted-provider Codex path.",
            priority=100,
            metadata={"origin": "backend_default"},
        ),
        ContextFragment(
            fragment_name="runtime_mode",
            visibility_scope="runtime",
            content="Continue the conversation naturally using the supplied transcript.",
            priority=80,
            metadata={"mode": "text_only"},
        ),
    ]
    workspace_fragment = _load_workspace_prompt(workspace_root)
    if workspace_fragment is not None:
        instruction_fragments.insert(1, workspace_fragment)
    history_fragment = ContextFragment(
        fragment_name="history",
        visibility_scope="session",
        content="\n\n".join(
            f"{getattr(message.role, 'value', str(message.role))}: {message.content}" for message in messages
        ).strip(),
        priority=70,
        metadata={"derived_from": "transcript", "message_count": len(messages)},
    )
    return PromptAssemblyPlan(
        source_backend=backend_name,
        model=model,
        instruction_fragments=instruction_fragments,
        transcript_messages=list(messages),
        history_context_fragments=[history_fragment] if history_fragment.content else [],
        auxiliary_context_fragments=list(memory_fragments or []),
        projection_hints={
            "codex": {
                "instruction_target": "instructions",
                "transcript_target": "input",
            }
        },
    )
