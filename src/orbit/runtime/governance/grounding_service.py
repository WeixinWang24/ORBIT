from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orbit.tools.base import ToolResult


class GroundingGovernanceService:
    """Governance-surface owner for grounding-aware mutation/readiness policy."""

    def __init__(self, session_manager) -> None:
        self.session_manager = session_manager

    def mutation_kind_for_tool(self, tool_name: str) -> str | None:
        return {
            "native__write_file": "write_file",
            "native__replace_in_file": "replace_in_file",
            "native__replace_all_in_file": "replace_all_in_file",
            "native__replace_block_in_file": "replace_block_in_file",
            "native__apply_exact_hunk": "apply_exact_hunk",
            "replace_in_file": "replace_in_file",
            "apply_unified_patch": "apply_unified_patch",
        }.get(tool_name)

    def grounding_kind_for_tool(self, tool_name: str, *, is_partial_view: bool) -> str | None:
        if tool_name in {"read_file", "native__read_file"}:
            return "partial_read" if is_partial_view else "full_read"
        return None

    def grounding_status_for_path(self, *, session, path: str) -> dict[str, Any]:
        read_state = session.metadata.get("filesystem_read_state", {})
        if not isinstance(read_state, dict):
            return {"status": "none", "path": path, "grounding_kind": None, "fresh": False}
        state = read_state.get(path)
        if not isinstance(state, dict):
            return {"status": "none", "path": path, "grounding_kind": None, "fresh": False}
        grounding_kind = state.get("grounding_kind")
        if grounding_kind == "partial_read":
            return {"status": "partial_only", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        if grounding_kind != "full_read":
            return {"status": "none", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        workspace_root = Path(self.session_manager.workspace_root).resolve()
        target = (workspace_root / path).resolve()
        try:
            target.relative_to(workspace_root)
        except ValueError:
            return {"status": "full_read_stale", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        if not target.exists() or not target.is_file():
            return {"status": "full_read_stale", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        try:
            stat = target.stat()
        except OSError:
            return {"status": "full_read_stale", "path": path, "grounding_kind": grounding_kind, "fresh": False}
        observed_modified_at = state.get("observed_modified_at_epoch")
        observed_size_bytes = state.get("observed_size_bytes")
        fresh = observed_modified_at is not None and observed_size_bytes is not None and stat.st_mtime == observed_modified_at and stat.st_size == observed_size_bytes
        return {
            "status": "full_read_fresh" if fresh else "full_read_stale",
            "path": path,
            "grounding_kind": grounding_kind,
            "fresh": fresh,
        }

    def write_readiness_for_path(self, *, session, path: str) -> dict[str, Any]:
        grounding = self.grounding_status_for_path(session=session, path=path)
        status = grounding.get("status")
        if status == "full_read_fresh":
            return {
                "eligible": True,
                "path": path,
                "grounding_status": status,
                "reason": "full_read_fresh_grounding_available",
            }
        if status == "partial_only":
            reason = "partial_read_grounding_insufficient"
        elif status == "full_read_stale":
            reason = "stale_full_read_grounding"
        else:
            reason = "no_prior_grounding"
        return {
            "eligible": False,
            "path": path,
            "grounding_status": status,
            "reason": reason,
        }

    def maybe_block_mutation(self, *, session, tool_request) -> ToolResult | None:
        mutation_family = {"native__write_file", "native__replace_in_file", "native__replace_all_in_file", "native__replace_block_in_file", "native__apply_exact_hunk", "replace_in_file", "apply_unified_patch"}
        if session is None or tool_request.tool_name not in mutation_family:
            return None
        path = tool_request.input_payload.get("path")
        if not isinstance(path, str) or not path:
            return None

        readiness = self.write_readiness_for_path(session=session, path=path)
        if readiness.get("eligible"):
            return None

        mutation_kind = self.mutation_kind_for_tool(tool_request.tool_name) or tool_request.tool_name
        return ToolResult(
            ok=False,
            content=(
                f"Grounded mutation blocked for {path}: "
                f"{readiness.get('reason', 'grounding_required')}. "
                "A fresh full read of the current file is required before mutation."
            ),
            data={
                "mutation_kind": mutation_kind,
                "path": path,
                "failure_layer": "grounding_readiness",
                "failure_kind": "grounding_required",
                "write_readiness": readiness,
            },
        )

    def maybe_make_unchanged_result(self, *, session, tool_request) -> ToolResult | None:
        if session is None or tool_request.tool_name not in {"read_file", "native__read_file"}:
            return None
        path = tool_request.input_payload.get("path")
        if not isinstance(path, str) or not path:
            return None
        read_state = session.metadata.get("filesystem_read_state", {})
        if not isinstance(read_state, dict):
            return None
        prior = read_state.get(path)
        if not isinstance(prior, dict):
            return None
        grounding_status = self.grounding_status_for_path(session=session, path=path)
        if grounding_status.get("status") != "full_read_fresh":
            return None
        observed_modified_at = prior.get("observed_modified_at_epoch")
        observed_size_bytes = prior.get("observed_size_bytes")
        structured = {
            "path": path,
            "status": "unchanged",
            "grounding_kind": "full_read",
            "freshness_basis": {
                "modified_at_epoch": observed_modified_at,
                "size_bytes": observed_size_bytes,
            },
            "range": None,
        }
        return ToolResult(
            ok=True,
            content=f"File {path} unchanged since prior full read in this session.",
            data={
                "result_kind": "filesystem_unchanged",
                "raw_result": {"structuredContent": structured},
            },
        )

    def record_read_state(self, *, session, tool_request, tool_result) -> None:
        if not tool_result.ok:
            return
        path = tool_request.input_payload.get("path")
        if not isinstance(path, str) or not path:
            return
        tool_data = tool_result.data if isinstance(tool_result.data, dict) else {}
        raw_result = tool_data.get("raw_result") if isinstance(tool_data, dict) else {}
        structured = raw_result.get("structuredContent") if isinstance(raw_result, dict) else {}
        if isinstance(structured, dict) and structured.get("status") == "unchanged":
            return
        truncated = bool(structured.get("truncated")) if isinstance(structured, dict) else False
        grounding_kind = self.grounding_kind_for_tool(tool_request.tool_name, is_partial_view=truncated)
        if grounding_kind is None:
            return
        read_state = session.metadata.setdefault("filesystem_read_state", {})
        observed_modified_at = structured.get("modified_at_epoch") if isinstance(structured, dict) else None
        observed_size_bytes = structured.get("size_bytes") if isinstance(structured, dict) else None
        read_state[path] = {
            "source_tool": tool_request.tool_name,
            "timestamp_epoch": datetime.now(timezone.utc).timestamp(),
            "is_partial_view": truncated,
            "grounding_kind": grounding_kind,
            "path_kind": "file",
            "observed_modified_at_epoch": observed_modified_at,
            "observed_size_bytes": observed_size_bytes,
            "range": None,
        }
        session.updated_at = datetime.now(timezone.utc)
        self.session_manager.store.save_session(session)
