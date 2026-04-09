from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from queue import Queue
from threading import Event, Thread
from typing import Any, Protocol, TextIO
from urllib.parse import urlparse

import anyio
from mcp.client.session import ClientSession
from mcp.client.stdio import StdioServerParameters, stdio_client

from orbit.runtime.mcp.models import McpClientBootstrap, McpToolDescriptor
from orbit.runtime.mcp.resource_models import McpResourceContent, McpResourceDescriptor
from orbit.tools.base import ToolResult

DEFAULT_MCP_TIMEOUT_SECONDS = 15

# Redirect MCP subprocess stderr to a log file so it never pollutes the PTY UI.
# The file is created lazily on first open; the directory is created if needed.
_MCP_STDERR_LOG: Path = Path(
    os.environ.get("ORBIT_MCP_STDERR_LOG",
                   str(Path(__file__).resolve().parents[4] / ".tmp" / "mcp_stderr.log"))
)


def _open_mcp_errlog() -> TextIO:
    _MCP_STDERR_LOG.parent.mkdir(parents=True, exist_ok=True)
    return _MCP_STDERR_LOG.open("a", encoding="utf-8", errors="replace")


class McpClient(Protocol):
    async def async_list_tools(self) -> list[McpToolDescriptor]:
        raise NotImplementedError

    def list_tools(self) -> list[McpToolDescriptor]:
        raise NotImplementedError

    async def async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        raise NotImplementedError

    def list_resources(self) -> list[McpResourceDescriptor]:
        raise NotImplementedError

    def read_resource(self, uri: str) -> list[McpResourceContent]:
        raise NotImplementedError

    def close(self) -> None:
        raise NotImplementedError


@dataclass
class StdioMcpClient:
    bootstrap: McpClientBootstrap

    async def async_list_tools(self) -> list[McpToolDescriptor]:
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        with anyio.fail_after(DEFAULT_MCP_TIMEOUT_SECONDS):
            async with stdio_client(server_params, errlog=_open_mcp_errlog()) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_tools()
                    return _descriptors_from_result(self.bootstrap, result)

    def list_tools(self) -> list[McpToolDescriptor]:
        return anyio.run(self.async_list_tools)

    async def async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        with anyio.fail_after(DEFAULT_MCP_TIMEOUT_SECONDS):
            async with stdio_client(server_params, errlog=_open_mcp_errlog()) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(tool_name, arguments)
                    return _tool_result_from_mcp_result(result)


    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        return anyio.run(self.async_call_tool, tool_name, arguments)

    async def async_list_resources(self) -> list[McpResourceDescriptor]:
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        with anyio.fail_after(DEFAULT_MCP_TIMEOUT_SECONDS):
            async with stdio_client(server_params, errlog=_open_mcp_errlog()) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.list_resources()
                    descriptors: list[McpResourceDescriptor] = []
                    for item in getattr(result, "resources", []) or []:
                        uri = getattr(item, "uri", None)
                        name = getattr(item, "name", None)
                        if not isinstance(uri, str) or not uri or not isinstance(name, str) or not name:
                            continue
                        descriptors.append(
                            McpResourceDescriptor(
                                server_name=self.bootstrap.server_name,
                                resource_uri=uri,
                                resource_name=name,
                                description=getattr(item, "description", None) if isinstance(getattr(item, "description", None), str) else None,
                                mime_type=getattr(item, "mimeType", None) if isinstance(getattr(item, "mimeType", None), str) else None,
                            )
                        )
                    return descriptors

    def list_resources(self) -> list[McpResourceDescriptor]:
        return anyio.run(self.async_list_resources)

    async def async_read_resource(self, uri: str) -> list[McpResourceContent]:
        parsed = urlparse(uri)
        if not isinstance(uri, str) or not uri.strip() or not parsed.scheme:
            raise ValueError(f"invalid MCP resource URI: {uri!r}")
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        with anyio.fail_after(DEFAULT_MCP_TIMEOUT_SECONDS):
            async with stdio_client(server_params, errlog=_open_mcp_errlog()) as (read_stream, write_stream):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.read_resource(uri)
                    contents: list[McpResourceContent] = []
                    for item in getattr(result, "contents", []) or []:
                        raw_item = item.model_dump(mode="json") if hasattr(item, "model_dump") else None
                        contents.append(
                            McpResourceContent(
                                uri=getattr(item, "uri", uri),
                                mime_type=getattr(item, "mimeType", None) if isinstance(getattr(item, "mimeType", None), str) else None,
                                text=getattr(item, "text", None) if isinstance(getattr(item, "text", None), str) else None,
                                blob=getattr(item, "blob", None) if isinstance(getattr(item, "blob", None), str) else None,
                                raw_item=raw_item,
                            )
                        )
                    return contents

    def read_resource(self, uri: str) -> list[McpResourceContent]:
        return anyio.run(self.async_read_resource, uri)

    def close(self) -> None:
        return None


@dataclass
class PersistentStdioMcpClient:
    bootstrap: McpClientBootstrap
    _request_queue: Queue = field(init=False)
    _ready: Event = field(init=False)
    _thread: Thread = field(init=False)
    _descriptors: list[McpToolDescriptor] | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._request_queue = Queue()
        self._ready = Event()
        self._thread = Thread(target=self._thread_main, name=f"orbit-mcp-{self.bootstrap.server_name}", daemon=True)
        self._thread.start()
        self._ready.wait(timeout=10)
        if not self._ready.is_set():
            raise RuntimeError(f"persistent MCP client failed to start for server {self.bootstrap.server_name}")

    def _thread_main(self) -> None:
        anyio.run(self._host_main)

    async def _host_main(self) -> None:
        server_params = StdioServerParameters(
            command=self.bootstrap.command,
            args=self.bootstrap.args,
            env=self.bootstrap.env or None,
        )
        async with stdio_client(server_params, errlog=_open_mcp_errlog()) as (read_stream, write_stream):
            async with ClientSession(read_stream, write_stream) as session:
                await session.initialize()
                self._ready.set()
                while True:
                    request = await anyio.to_thread.run_sync(self._request_queue.get)
                    kind = request["kind"]
                    response_queue = request["response_queue"]
                    try:
                        if kind == "close":
                            response_queue.put((True, None))
                            break
                        if kind == "list_tools":
                            result = await session.list_tools()
                            response_queue.put((True, _descriptors_from_result(self.bootstrap, result)))
                            continue
                        if kind == "call_tool":
                            result = await session.call_tool(request["tool_name"], request["arguments"])
                            response_queue.put((True, _tool_result_from_mcp_result(result)))
                            continue
                        raise ValueError(f"unknown persistent MCP request kind: {kind}")
                    except Exception as exc:
                        response_queue.put((False, exc))

    def _request(self, payload: dict[str, Any]) -> Any:
        response_queue: Queue = Queue()
        payload = dict(payload)
        payload["response_queue"] = response_queue
        self._request_queue.put(payload)
        ok, value = response_queue.get(timeout=30)
        if ok:
            return value
        raise value

    async def async_list_tools(self) -> list[McpToolDescriptor]:
        return self.list_tools()

    def list_tools(self) -> list[McpToolDescriptor]:
        if self._descriptors is None:
            self._descriptors = self._request({"kind": "list_tools"})
        return list(self._descriptors)

    async def async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        return self.call_tool(tool_name, arguments)

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        return self._request({"kind": "call_tool", "tool_name": tool_name, "arguments": arguments})

    def list_resources(self) -> list[McpResourceDescriptor]:
        return []

    def read_resource(self, uri: str) -> list[McpResourceContent]:
        raise ValueError("persistent stdio MCP resource reads are not implemented in this first slice")

    def close(self) -> None:
        try:
            self._request({"kind": "close"})
        except Exception:
            pass


def _descriptors_from_result(bootstrap: McpClientBootstrap, result: Any) -> list[McpToolDescriptor]:
    descriptors: list[McpToolDescriptor] = []
    for item in result.tools:
        original_name = getattr(item, "name", None)
        if not isinstance(original_name, str) or not original_name:
            continue
        description = getattr(item, "description", None)
        input_schema = getattr(item, "inputSchema", None)
        descriptors.append(
            McpToolDescriptor(
                server_name=bootstrap.server_name,
                original_name=original_name,
                orbit_tool_name=original_name,
                description=description if isinstance(description, str) else None,
                input_schema=input_schema if isinstance(input_schema, dict) else None,
            )
        )
    return descriptors


def _tool_result_from_mcp_result(result: Any) -> ToolResult:
    content = getattr(result, "content", [])
    text_parts: list[str] = []
    if isinstance(content, list):
        for item in content:
            item_type = getattr(item, "type", None)
            item_text = getattr(item, "text", None)
            if item_type == "text" and isinstance(item_text, str):
                text_parts.append(item_text)
    output_text = "\n".join(text_parts).strip()
    is_error = bool(getattr(result, "isError", False))
    raw_result = result.model_dump(mode="json") if hasattr(result, "model_dump") else {"content": output_text, "isError": is_error}
    structured = raw_result.get("structuredContent") if isinstance(raw_result, dict) and isinstance(raw_result.get("structuredContent"), dict) else {}
    failure_layer = structured.get("failure_layer") if isinstance(structured, dict) else None
    return ToolResult(
        ok=(not is_error) and failure_layer is None,
        content=output_text,
        data={"failure_layer": failure_layer, "raw_result": raw_result},
    )


@dataclass
class UnixSocketMcpClient:
    """MCP client that talks to a filesystem daemon over a Unix domain socket.

    Uses the ORBIT-local daemon socket protocol (see ``socket_protocol.py``),
    NOT standard MCP-over-stdio.  This is a transitional phase 3 transport
    scoped to the filesystem daemon.  The protocol is request-per-connection
    newline-delimited JSON.
    """
    bootstrap: McpClientBootstrap
    timeout_seconds: float = 30.0

    def __post_init__(self) -> None:
        if not self.bootstrap.socket_path:
            raise ValueError(
                "unix_socket transport requires a socket_path in the bootstrap, "
                f"but got None for server={self.bootstrap.server_name!r}"
            )

    def _send(self, request: dict[str, Any]) -> dict[str, Any]:
        from orbit.runtime.mcp.socket_protocol import send_request
        return send_request(
            self.bootstrap.socket_path,
            request,
            timeout_seconds=self.timeout_seconds,
        )

    def list_tools(self) -> list[McpToolDescriptor]:
        resp = self._send({"kind": "list_tools"})
        if not resp.get("ok"):
            raise RuntimeError(f"daemon list_tools failed: {resp.get('error', 'unknown')}")
        descriptors: list[McpToolDescriptor] = []
        for item in resp.get("payload", []):
            name = item.get("name")
            if not isinstance(name, str) or not name:
                continue
            descriptors.append(McpToolDescriptor(
                server_name=self.bootstrap.server_name,
                original_name=name,
                orbit_tool_name=name,
                description=item.get("description"),
                input_schema=item.get("inputSchema"),
            ))
        return descriptors

    async def async_list_tools(self) -> list[McpToolDescriptor]:
        return self.list_tools()

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        resp = self._send({"kind": "call_tool", "tool_name": tool_name, "arguments": arguments})
        if not resp.get("ok"):
            return ToolResult(ok=False, content=resp.get("error", "daemon call_tool failed"), data=None)
        payload = resp.get("payload", {})
        content = payload.get("content", "")
        is_error = bool(payload.get("isError", False))
        structured = payload.get("structuredContent")
        failure_layer = structured.get("failure_layer") if isinstance(structured, dict) else None
        return ToolResult(
            ok=(not is_error) and failure_layer is None,
            content=content,
            data={"failure_layer": failure_layer, "raw_result": payload},
        )

    async def async_call_tool(self, tool_name: str, arguments: dict[str, Any]) -> ToolResult:
        return self.call_tool(tool_name, arguments)

    def list_resources(self) -> list[McpResourceDescriptor]:
        return []

    def read_resource(self, uri: str) -> list[McpResourceContent]:
        raise NotImplementedError("resource reads not supported over daemon socket transport")

    def close(self) -> None:
        pass


def build_mcp_client(bootstrap: McpClientBootstrap) -> McpClient:
    if bootstrap.transport == "stdio":
        return StdioMcpClient(bootstrap=bootstrap)
    if bootstrap.transport == "unix_socket":
        return UnixSocketMcpClient(bootstrap=bootstrap)
    raise ValueError(f"unsupported MCP transport: {bootstrap.transport}")
