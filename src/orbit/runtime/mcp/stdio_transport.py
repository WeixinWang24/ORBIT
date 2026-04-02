from __future__ import annotations

"""Legacy experimental stdio MCP transport shim.

This file is intentionally retained as a protocol/debug baseline after ORBIT
switched its primary stdio MCP client path to the official Python `mcp` SDK.

It is no longer the preferred implementation for `StdioMcpClient`, but it can
still be useful for:
- debugging framing/protocol assumptions
- comparing SDK behavior with a minimal local shim
- fallback experimentation during early MCP development
"""

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any

from orbit.runtime.mcp.models import McpClientBootstrap


@dataclass
class StdioMcpTransport:
    bootstrap: McpClientBootstrap
    _process: subprocess.Popen[str] | None = field(default=None, init=False, repr=False)
    _next_id: int = field(default=1, init=False, repr=False)

    def start(self) -> None:
        if self._process is not None:
            return
        env = None
        if self.bootstrap.env:
            import os
            env = os.environ.copy()
            env.update(self.bootstrap.env)
        self._process = subprocess.Popen(
            [self.bootstrap.command, *self.bootstrap.args],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            env=env,
        )

    def request(self, method: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        self.start()
        if self._process is None or self._process.stdin is None or self._process.stdout is None:
            raise RuntimeError("MCP stdio transport not initialized")
        request_id = self._next_id
        self._next_id += 1
        payload: dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
        }
        if params is not None:
            payload["params"] = params
        self._process.stdin.write(json.dumps(payload) + "\n")
        self._process.stdin.flush()
        while True:
            line = self._process.stdout.readline()
            if line == "":
                stderr_text = ""
                if self._process.stderr is not None:
                    stderr_text = self._process.stderr.read()
                raise RuntimeError(f"MCP stdio transport closed while waiting for response to {method!r}. stderr={stderr_text!r}")
            message = json.loads(line)
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise RuntimeError(f"MCP error for {method!r}: {message['error']}")
            result = message.get("result")
            if not isinstance(result, dict):
                raise RuntimeError(f"MCP result for {method!r} must be an object, got: {result!r}")
            return result

    def close(self) -> None:
        if self._process is None:
            return
        try:
            if self._process.stdin is not None:
                self._process.stdin.close()
        finally:
            self._process.terminate()
            self._process.wait(timeout=5)
            self._process = None
