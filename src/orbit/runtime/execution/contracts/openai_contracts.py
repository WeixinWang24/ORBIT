"""OpenAI first-interaction contract models for ORBIT.

This module defines the narrowest request/response contract ORBIT should use for
its first OpenAI OAuth-backed interaction path. The goal is not to expose raw
provider SDK objects to the runtime coordinator. Instead, it gives the OpenAI
backend a small local contract surface for:

- building the first provider request payload
- holding a minimally useful raw response snapshot
- normalizing the result into ORBIT runtime objects

This contract is intentionally scoped to the first non-streaming final-text
interaction path.
"""

from __future__ import annotations

from pydantic import Field

from orbit.models.core import OrbitBaseModel


class OpenAIFirstRequest(OrbitBaseModel):
    """Describe the first narrow OpenAI request ORBIT wants to send."""

    model: str
    instructions: str | None = None
    input_text: str
    max_output_tokens: int | None = None
    metadata: dict = Field(default_factory=dict)


class OpenAIRawOutputItem(OrbitBaseModel):
    """Store a minimally useful raw output item extracted from a provider response."""

    item_type: str
    text: str | None = None
    raw_payload: dict = Field(default_factory=dict)


class OpenAIFirstRawResponse(OrbitBaseModel):
    """Describe the minimal raw response ORBIT keeps inside the backend boundary."""

    response_id: str | None = None
    model: str | None = None
    output_items: list[OpenAIRawOutputItem] = Field(default_factory=list)
    raw_text: str | None = None
    finish_reason: str | None = None
    usage: dict = Field(default_factory=dict)
    raw_payload: dict = Field(default_factory=dict)
