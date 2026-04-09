from __future__ import annotations

import threading
from pathlib import Path

from .base import Tool
from .browser import BrowserClickTool, BrowserConsoleTool, BrowserOpenTool, BrowserScreenshotTool, BrowserSnapshotTool, BrowserTypeTool
from orbit.browser_manager import BrowserManager
from .files import ApplyExactHunkTool, ReadFileTool, ReplaceAllInFileTool, ReplaceBlockInFileTool, ReplaceInFileTool, WriteFileTool
from .introspection import DescribeToolTool, ListAvailableToolsTool


class ToolRegistry:
    def __init__(self, workspace_root: Path, *, enable_native_browser_tools: bool = False):
        self._lock = threading.Lock()
        self._tools: dict[str, Tool] = {}
        tools = [
            ReadFileTool(workspace_root),
            WriteFileTool(workspace_root),
            ReplaceInFileTool(workspace_root),
            ReplaceAllInFileTool(workspace_root),
            ReplaceBlockInFileTool(workspace_root),
            ApplyExactHunkTool(workspace_root),
            ListAvailableToolsTool(lambda: self),
            DescribeToolTool(lambda: self),
        ]
        if enable_native_browser_tools:
            browser_manager = BrowserManager(workspace_root)
            tools.extend([
                BrowserOpenTool(browser_manager),
                BrowserSnapshotTool(browser_manager),
                BrowserClickTool(browser_manager),
                BrowserTypeTool(browser_manager),
                BrowserConsoleTool(browser_manager),
                BrowserScreenshotTool(browser_manager),
            ])
        self._tools = {tool.name: tool for tool in tools}

    def register(self, tool: Tool) -> None:
        with self._lock:
            self._tools[tool.name] = tool

    def register_many(self, tools: list[Tool]) -> None:
        with self._lock:
            for tool in tools:
                self._tools[tool.name] = tool

    def get(self, name: str) -> Tool:
        with self._lock:
            try:
                return self._tools[name]
            except KeyError as exc:
                available = ", ".join(sorted(self._tools.keys()))
                raise KeyError(f"tool not found: {name}. available tools: {available}") from exc

    def list_names(self) -> list[str]:
        with self._lock:
            return sorted(self._tools.keys())

    def list_tools(self) -> list[Tool]:
        with self._lock:
            return [self._tools[name] for name in sorted(self._tools.keys())]
