"""Provider request projection helpers for ORBIT conversation transcripts."""

from __future__ import annotations

from orbit.models import ConversationMessage, MessageRole



def messages_to_chat_completions_messages(messages: list[ConversationMessage]) -> list[dict[str, str]]:
    """Project ORBIT transcript messages into chat-completions role/content rows."""
    projected: list[dict[str, str]] = []
    for message in messages:
        projected.append({"role": str(message.role), "content": message.content})
    return projected



def messages_to_codex_input(messages: list[ConversationMessage]) -> list[dict]:
    """Project ORBIT transcript messages into a first Codex-compatible item stream.

    MVP scope:
    - user text becomes `role=user` input_text content
    - assistant text becomes a Responses-style assistant output message item
    - system messages are intentionally omitted here and should flow through
      `instructions` instead
    """
    projected: list[dict] = []
    assistant_index = 0
    for message in messages:
        if message.role == MessageRole.SYSTEM:
            continue
        if message.role == MessageRole.USER:
            projected.append(
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": message.content}],
                }
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
