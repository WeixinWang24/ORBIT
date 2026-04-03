from __future__ import annotations

from pathlib import Path

from .base import Tool, ToolResult


class ReadFileTool(Tool):
    name = "native__read_file"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "path_exists"

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def invoke(self, *, path: str) -> ToolResult:
        target = (self.workspace_root / path).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return ToolResult(ok=False, content="path escapes workspace")
        if not target.exists() or not target.is_file():
            return ToolResult(ok=False, content="file not found")
        return ToolResult(ok=True, content=target.read_text(), data={"path": str(target)})


class WriteFileTool(Tool):
    name = "native__write_file"
    side_effect_class = "write"
    requires_approval = True
    governance_policy_group = "permission_authority"
    environment_check_kind = "none"

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def invoke(self, *, path: str, content: str) -> ToolResult:
        target = (self.workspace_root / path).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return ToolResult(ok=False, content="path escapes workspace")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content)
        return ToolResult(ok=True, content=f"wrote {target}", data={"mutation_kind": "write_file", "path": str(target)})


class ReplaceInFileTool(Tool):
    name = "native__replace_in_file"
    side_effect_class = "write"
    requires_approval = True
    governance_policy_group = "permission_authority"
    environment_check_kind = "none"

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def invoke(self, *, path: str, old_text: str, new_text: str) -> ToolResult:
        target = (self.workspace_root / path).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return ToolResult(ok=False, content="path escapes workspace")
        if not target.exists() or not target.is_file():
            return ToolResult(ok=False, content="file not found")
        content = target.read_text()
        if old_text not in content:
            return ToolResult(ok=False, content="old_text not found", data={"mutation_kind": "replace_in_file", "failure_layer": "tool_semantic", "path": str(target)})
        updated = content.replace(old_text, new_text, 1)
        target.write_text(updated)
        return ToolResult(ok=True, content=f"replaced text in {target}", data={"mutation_kind": "replace_in_file", "path": str(target), "replacement_count": 1, "before_excerpt": old_text, "after_excerpt": new_text})


class ReplaceAllInFileTool(Tool):
    name = "native__replace_all_in_file"
    side_effect_class = "write"
    requires_approval = True
    governance_policy_group = "permission_authority"
    environment_check_kind = "none"

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def invoke(self, *, path: str, old_text: str, new_text: str) -> ToolResult:
        target = (self.workspace_root / path).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return ToolResult(ok=False, content="path escapes workspace")
        if not target.exists() or not target.is_file():
            return ToolResult(ok=False, content="file not found")
        content = target.read_text()
        replacement_count = content.count(old_text)
        if replacement_count == 0:
            return ToolResult(ok=False, content="old_text not found", data={"mutation_kind": "replace_all_in_file", "failure_layer": "tool_semantic", "path": str(target), "replacement_count": 0})
        updated = content.replace(old_text, new_text)
        target.write_text(updated)
        return ToolResult(ok=True, content=f"replaced {replacement_count} occurrence(s) in {target}", data={"mutation_kind": "replace_all_in_file", "path": str(target), "replacement_count": replacement_count, "before_excerpt": old_text, "after_excerpt": new_text})


class ReplaceBlockInFileTool(Tool):
    name = "native__replace_block_in_file"
    side_effect_class = "write"
    requires_approval = True
    governance_policy_group = "permission_authority"
    environment_check_kind = "none"

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def invoke(self, *, path: str, old_block: str, new_block: str) -> ToolResult:
        target = (self.workspace_root / path).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return ToolResult(ok=False, content="path escapes workspace")
        if not target.exists() or not target.is_file():
            return ToolResult(ok=False, content="file not found")
        content = target.read_text()
        match_count = content.count(old_block)
        if match_count == 0:
            return ToolResult(ok=False, content="old_block not found", data={"mutation_kind": "replace_block_in_file", "failure_layer": "tool_semantic", "path": str(target), "match_count": 0, "replacement_count": 0})
        if match_count > 1:
            return ToolResult(ok=False, content="old_block matched multiple regions", data={"mutation_kind": "replace_block_in_file", "failure_layer": "tool_semantic", "path": str(target), "match_count": match_count, "replacement_count": 0})
        updated = content.replace(old_block, new_block, 1)
        target.write_text(updated)
        return ToolResult(ok=True, content=f"replaced block in {target}", data={"mutation_kind": "replace_block_in_file", "path": str(target), "match_count": 1, "replacement_count": 1, "before_excerpt": old_block, "after_excerpt": new_block})


class ApplyExactHunkTool(Tool):
    name = "native__apply_exact_hunk"
    side_effect_class = "write"
    requires_approval = True
    governance_policy_group = "permission_authority"
    environment_check_kind = "none"

    def __init__(self, workspace_root: Path):
        self.workspace_root = workspace_root.resolve()

    def invoke(self, *, path: str, before_context: str, old_block: str, after_context: str, new_block: str) -> ToolResult:
        target = (self.workspace_root / path).resolve()
        try:
            target.relative_to(self.workspace_root)
        except ValueError:
            return ToolResult(ok=False, content="path escapes workspace")
        if not target.exists() or not target.is_file():
            return ToolResult(ok=False, content="file not found")
        content = target.read_text()
        old_hunk = before_context + old_block + after_context
        new_hunk = before_context + new_block + after_context
        match_count = content.count(old_hunk)
        if match_count == 0:
            return ToolResult(ok=False, content="exact hunk not found", data={"mutation_kind": "apply_exact_hunk", "failure_layer": "tool_semantic", "path": str(target), "match_count": 0, "replacement_count": 0, "change_summary": "0 exact hunk matches"})
        if match_count > 1:
            return ToolResult(ok=False, content="exact hunk matched multiple regions", data={"mutation_kind": "apply_exact_hunk", "failure_layer": "tool_semantic", "path": str(target), "match_count": match_count, "replacement_count": 0, "change_summary": f"{match_count} exact hunk matches"})
        updated = content.replace(old_hunk, new_hunk, 1)
        target.write_text(updated)
        return ToolResult(ok=True, content=f"applied exact hunk in {target}", data={"mutation_kind": "apply_exact_hunk", "path": str(target), "match_count": 1, "replacement_count": 1, "before_excerpt": old_block, "after_excerpt": new_block, "change_summary": "1 exact hunk applied"})
