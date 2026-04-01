from __future__ import annotations

from pathlib import Path

from .base import Tool
from .files import ReadFileTool, WriteFileTool


class ToolRegistry:
    def __init__(self, workspace_root: Path):
        tools = [ReadFileTool(workspace_root), WriteFileTool(workspace_root)]
        self._tools = {tool.name: tool for tool in tools}

    def get(self, name: str) -> Tool:
        return self._tools[name]

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def list_tools(self) -> list[Tool]:
        return [self._tools[name] for name in self.list_names()]
