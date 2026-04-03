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
        return ToolResult(ok=True, content=f"wrote {target}", data={"path": str(target)})


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
            return ToolResult(ok=False, content="old_text not found", data={"path": str(target)})
        updated = content.replace(old_text, new_text, 1)
        target.write_text(updated)
        return ToolResult(ok=True, content=f"replaced text in {target}", data={"path": str(target)})
