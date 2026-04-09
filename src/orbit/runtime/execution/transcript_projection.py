"""Provider request projection helpers for ORBIT conversation transcripts.

ORBIT's transcript model is intentionally richer than the first provider wire
formats. In particular, governed tool-calling artifacts should remain
canonically distinct even when the current transport still needs a conservative
compatibility projection.
"""

from __future__ import annotations

from orbit.models import ConversationMessage, MessageRole



def _message_kind(message: ConversationMessage) -> str | None:
    value = message.metadata.get("message_kind")
    return value if isinstance(value, str) else None



def _chat_completions_compat_content(message: ConversationMessage) -> str:
    """Return a compatibility-safe textual projection for current chat backends."""
    kind = _message_kind(message)
    if message.role == MessageRole.TOOL and kind in {"tool_result", "capability_result"}:
        return message.content
    if kind == "approval_request":
        tool_name = message.metadata.get("tool_name")
        side_effect_class = message.metadata.get("side_effect_class")
        return (
            f"Approval request for tool {tool_name}: pending. "
            f"side_effect_class={side_effect_class}. Tool has not executed yet."
        )
    if kind == "approval_decision":
        tool_name = message.metadata.get("tool_name")
        decision = message.metadata.get("decision")
        note = message.metadata.get("note")
        executed = message.metadata.get("tool_executed")
        suffix = ""
        if note:
            suffix = f" Note: {note}"
        if decision == "rejected":
            return (
                f"Governance update: the requested tool {tool_name} was rejected by the human operator. "
                f"tool_executed={executed}.{suffix} "
                "Do not assume the tool ran. Continue the conversation without executing that tool, "
                "for example by acknowledging the rejection, summarizing what would have happened, "
                "or offering a non-side-effecting alternative."
            )
        return (
            f"Approval decision for tool {tool_name}: {decision}. "
            f"tool_executed={executed}.{suffix}"
        )
    if kind == "continuation_bridge":
        return message.content
    return message.content



def _codex_metadata(message: ConversationMessage) -> dict:
    """Return a compact provider-facing metadata envelope for Codex projection."""
    kind = _message_kind(message)
    data = {"orbit_role": str(message.role)}
    if kind is not None:
        data["message_kind"] = kind
    for key in [
        "tool_name",
        "tool_ok",
        "tool_executed",
        "decision",
        "side_effect_class",
        "bridge_kind",
        "source_message_kind",
    ]:
        value = message.metadata.get(key)
        if value is not None:
            data[key] = value
    return data



def _codex_function_call_output_item(*, call_id: str, output_text: str) -> dict:
    return {
        "type": "function_call_output",
        "call_id": call_id,
        "output": output_text,
    }


def _codex_user_input_item(*, text: str, metadata: dict | None = None) -> dict:
    """Return a Codex-compatible user input item.

    Current hosted-route compatibility rule: do not attach item-level metadata
    fields, because the route rejects unknown `input[i].metadata` parameters.
    Keep the metadata argument here for call-site clarity and future protocol
    extension, but do not serialize it into the current payload.
    """
    _ = metadata
    return {
        "role": "user",
        "content": [{"type": "input_text", "text": text}],
    }



def messages_to_chat_completions_messages(messages: list[ConversationMessage]) -> list[dict[str, str]]:
    """Project ORBIT transcript messages into chat-completions role/content rows.

    Current compatibility rule:
    - canonical ORBIT tool and approval artifacts remain distinct internally
    - the first SSH vLLM continuation path still receives a conservative text
      projection using ordinary chat-completions roles
    """
    projected: list[dict[str, str]] = []
    for message in messages:
        role = str(message.role)
        if message.role == MessageRole.TOOL:
            role = MessageRole.USER.value
        projected.append({"role": role, "content": _chat_completions_compat_content(message)})
    return projected



def messages_to_codex_input(messages: list[ConversationMessage]) -> list[dict]:
    """Project ORBIT transcript messages into a first Codex-compatible item stream.

    Current projection contract:
    - canonical user-authored text remains user input text
    - canonical assistant plain text remains assistant output text
    - governed tool/approval/bridge artifacts are projected explicitly through
      compatibility user-input items with compact metadata envelopes
    - system messages are intentionally omitted here and should flow through
      `instructions` instead

    This keeps the canonical/provider boundary visible while Codex tool-calling
    support is still being prepared.
    """
    projected: list[dict] = []
    assistant_index = 0
    for message in messages:
        kind = _message_kind(message)
        if message.role == MessageRole.SYSTEM:
            continue
        if message.role == MessageRole.USER and kind is None:
            projected.append(_codex_user_input_item(text=message.content))
            continue
        if message.role == MessageRole.TOOL:
            provider_call_id = message.metadata.get("provider_call_id")
            if isinstance(provider_call_id, str) and provider_call_id:
                projected.append(
                    _codex_function_call_output_item(
                        call_id=provider_call_id,
                        output_text=message.content,
                    )
                )
            else:
                projected.append(
                    _codex_user_input_item(
                        text=message.content,
                        metadata=_codex_metadata(message),
                    )
                )
            continue
        if kind in {"approval_request", "approval_decision", "continuation_bridge"}:
            projected.append(
                _codex_user_input_item(
                    text=_chat_completions_compat_content(message),
                    metadata=_codex_metadata(message),
                )
            )
            continue
        if message.role == MessageRole.USER:
            projected.append(
                _codex_user_input_item(
                    text=message.content,
                    metadata=_codex_metadata(message),
                )
            )
            continue
        if message.role == MessageRole.ASSISTANT:
            projected.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": message.content, "annotations": []}],
                    "status": "completed",
                    "id": f"msg_{assistant_index}",
                }
            )
            assistant_index += 1
    return projected
