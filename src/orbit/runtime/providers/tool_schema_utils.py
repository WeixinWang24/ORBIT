from __future__ import annotations

from typing import Any

from orbit.tools.base import Tool


_NATIVE_TOOL_PARAMETER_SCHEMAS: dict[str, dict[str, Any]] = {
    "native__list_available_tools": {
        "type": "object",
        "properties": {},
        "additionalProperties": False,
    },
    "native__describe_tool": {
        "type": "object",
        "properties": {
            "name": {"type": "string", "description": "Exact tool name to describe."},
        },
        "required": ["name"],
        "additionalProperties": False,
    },
    "native__read_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
        },
        "required": ["path"],
        "additionalProperties": False,
    },
    "native__write_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "content": {"type": "string", "description": "File content to write."},
        },
        "required": ["path", "content"],
        "additionalProperties": False,
    },
    "native__replace_in_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "old_text": {"type": "string", "description": "Exact text to replace once."},
            "new_text": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    },
    "native__replace_all_in_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "old_text": {"type": "string", "description": "Exact text to replace everywhere."},
            "new_text": {"type": "string", "description": "Replacement text."},
        },
        "required": ["path", "old_text", "new_text"],
        "additionalProperties": False,
    },
    "native__replace_block_in_file": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "start_marker": {"type": "string", "description": "Unique start marker for the block."},
            "end_marker": {"type": "string", "description": "Unique end marker for the block."},
            "replacement": {"type": "string", "description": "Replacement text for the block."},
        },
        "required": ["path", "start_marker", "end_marker", "replacement"],
        "additionalProperties": False,
    },
    "native__apply_exact_hunk": {
        "type": "object",
        "properties": {
            "path": {"type": "string", "description": "Workspace-relative file path."},
            "before_context": {"type": "string", "description": "Exact context immediately before the old block."},
            "old_block": {"type": "string", "description": "Exact block to replace within the hunk."},
            "after_context": {"type": "string", "description": "Exact context immediately after the old block."},
            "new_block": {"type": "string", "description": "Replacement block."},
        },
        "required": ["path", "before_context", "old_block", "after_context", "new_block"],
        "additionalProperties": False,
    },
}


_NATIVE_TOOL_DESCRIPTIONS: dict[str, str] = {
    "native__list_available_tools": "Return ORBIT's assembled runtime tool inventory from the active ToolRegistry truth, including governance attributes, capability-family hints, maturity signals, closure status, and guidance for choosing already-implemented tools.",
    "native__describe_tool": "Describe one currently callable ORBIT tool from the assembled runtime ToolRegistry, including capability-family context, maturity, closure status, and known limits.",
    "native__read_file": "Read one workspace-relative text file through ORBIT's live native file-inspection layer.",
    "native__write_file": "Approval-gated grounded single-file write tool in ORBIT's active filesystem mutation family. Use for direct full-file replacement after fresh grounding when appropriate.",
    "native__replace_in_file": "Approval-gated grounded single-file mutation tool in ORBIT's active filesystem mutation family. Replace one exact text occurrence after fresh grounding; this is a live runtime capability, not a planning stub.",
    "native__replace_all_in_file": "Approval-gated grounded single-file mutation tool in ORBIT's active filesystem mutation family. Replace all exact text occurrences after fresh grounding.",
    "native__replace_block_in_file": "Approval-gated grounded single-file mutation tool in ORBIT's active filesystem mutation family. Replace the exact block between unique markers after fresh grounding.",
    "native__apply_exact_hunk": "Approval-gated grounded single-file mutation tool in ORBIT's active filesystem mutation family. Apply one exact context-anchored hunk replacement after fresh grounding; this is a live runtime capability, not a stub.",
}


def tool_description(tool: Tool) -> str:
    descriptor = getattr(tool, "descriptor", None)
    description = getattr(descriptor, "description", None)
    if isinstance(description, str) and description.strip():
        return description
    return _NATIVE_TOOL_DESCRIPTIONS.get(tool.name, f"Invoke the {tool.name} tool.")


def tool_parameters_schema(tool: Tool) -> dict[str, Any]:
    descriptor = getattr(tool, "descriptor", None)
    input_schema = getattr(descriptor, "input_schema", None)
    if isinstance(input_schema, dict) and input_schema:
        return input_schema
    return _NATIVE_TOOL_PARAMETER_SCHEMAS.get(
        tool.name,
        {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )


def codex_function_definition(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "name": tool.name,
        "description": tool_description(tool),
        "parameters": tool_parameters_schema(tool),
    }


def chat_completions_function_definition(tool: Tool) -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": tool.name,
            "description": tool_description(tool),
            "parameters": tool_parameters_schema(tool),
        },
    }
