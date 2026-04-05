from __future__ import annotations

from dataclasses import dataclass
from threading import Lock
from typing import Dict, Tuple

from orbit.runtime.mcp.client import PersistentStdioMcpClient
from orbit.runtime.mcp.models import McpClientBootstrap


def _bootstrap_key(bootstrap: McpClientBootstrap) -> Tuple[str, str, tuple[str, ...], tuple[tuple[str, str], ...]]:
    return (
        bootstrap.server_name,
        bootstrap.command,
        tuple(bootstrap.args),
        tuple(sorted((bootstrap.env or {}).items())),
    )


@dataclass
class PersistentMcpClientRegistry:
    _clients: Dict[Tuple[str, str, tuple[str, ...], tuple[tuple[str, str], ...]], PersistentStdioMcpClient]
    _lock: Lock

    def __init__(self) -> None:
        self._clients = {}
        self._lock = Lock()

    def get_or_create(self, bootstrap: McpClientBootstrap) -> PersistentStdioMcpClient:
        key = _bootstrap_key(bootstrap)
        with self._lock:
            client = self._clients.get(key)
            if client is None:
                client = PersistentStdioMcpClient(bootstrap=bootstrap)
                self._clients[key] = client
            return client

    def close_all(self) -> None:
        with self._lock:
            clients = list(self._clients.values())
            self._clients.clear()
        for client in clients:
            try:
                client.close()
            except Exception:
                pass


PERSISTENT_MCP_CLIENT_REGISTRY = PersistentMcpClientRegistry()
