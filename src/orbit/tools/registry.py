from __future__ import annotations

from pathlib import Path

from .base import Tool
from .files import ReadFileTool, ReplaceAllInFileTool, ReplaceBlockInFileTool, ReplaceInFileTool, WriteFileTool


class ToolRegistry:
    def __init__(self, workspace_root: Path):
        tools = [ReadFileTool(workspace_root), WriteFileTool(workspace_root), ReplaceInFileTool(workspace_root), ReplaceAllInFileTool(workspace_root), ReplaceBlockInFileTool(workspace_root)]
        self._tools = {tool.name: tool for tool in tools}

    def register(self, tool: Tool) -> None:
        self._tools[tool.name] = tool

    def register_many(self, tools: list[Tool]) -> None:
        for tool in tools:
            self.register(tool)

    def get(self, name: str) -> Tool:
        try:
            return self._tools[name]
        except KeyError as exc:
            available = ", ".join(sorted(self._tools.keys()))
            raise KeyError(f"tool not found: {name}. available tools: {available}") from exc

    def list_names(self) -> list[str]:
        return sorted(self._tools.keys())

    def list_tools(self) -> list[Tool]:
        return [self._tools[name] for name in self.list_names()]
