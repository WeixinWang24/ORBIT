from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult
from orbit.browser_manager import BrowserManager


class BrowserOpenTool(Tool):
    name = "browser_open"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "none"

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    def invoke(self, *, url: str) -> ToolResult:
        try:
            data = self.manager.open(url)
            return ToolResult(ok=True, content=f"opened {data['url']}", data=data)
        except Exception as exc:
            return ToolResult(ok=False, content=str(exc))


class BrowserSnapshotTool(Tool):
    name = "browser_snapshot"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "none"

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    def invoke(self, **kwargs: Any) -> ToolResult:
        try:
            data = self.manager.snapshot()
            return ToolResult(ok=True, content=f"captured snapshot for {data['url']}", data=data)
        except Exception as exc:
            return ToolResult(ok=False, content=str(exc))


class BrowserClickTool(Tool):
    name = "browser_click"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "none"

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    def invoke(self, *, element_id: str) -> ToolResult:
        try:
            data = self.manager.click(element_id)
            return ToolResult(ok=True, content=f"clicked {element_id}", data=data)
        except Exception as exc:
            return ToolResult(ok=False, content=str(exc))


class BrowserTypeTool(Tool):
    name = "browser_type"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "none"

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    def invoke(self, *, element_id: str, text: str) -> ToolResult:
        try:
            data = self.manager.type(element_id, text)
            return ToolResult(ok=True, content=f"typed into {element_id}", data=data)
        except Exception as exc:
            return ToolResult(ok=False, content=str(exc))


class BrowserConsoleTool(Tool):
    name = "browser_console"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "none"

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    def invoke(self, **kwargs: Any) -> ToolResult:
        try:
            data = self.manager.console()
            return ToolResult(ok=True, content=f"read {data['message_count']} console messages", data=data)
        except Exception as exc:
            return ToolResult(ok=False, content=str(exc))


class BrowserScreenshotTool(Tool):
    name = "browser_screenshot"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "none"

    def __init__(self, manager: BrowserManager):
        self.manager = manager

    def invoke(self, **kwargs: Any) -> ToolResult:
        try:
            data = self.manager.screenshot()
            return ToolResult(ok=True, content=f"captured screenshot for {data['url']}", data=data)
        except Exception as exc:
            return ToolResult(ok=False, content=str(exc))
