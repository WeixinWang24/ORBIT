"""Minimal SSH local-forward tunnel helper for ORBIT."""

from __future__ import annotations

import socket
import subprocess
import time
from contextlib import contextmanager
from dataclasses import dataclass


@dataclass
class SshTunnelConfig:
    """Describe the minimal local-forward tunnel settings."""

    ssh_host: str
    local_port: int = 8000
    remote_host: str = "127.0.0.1"
    remote_port: int = 8000


class SshTunnelError(RuntimeError):
    """Raised when ORBIT cannot establish or use an SSH tunnel."""


class SshTunnelManager:
    """Keep a minimal reusable SSH local-forward tunnel alive for ORBIT requests."""

    def __init__(self):
        self._process: subprocess.Popen | None = None

    @staticmethod
    def port_is_open(host: str, port: int) -> bool:
        """Return True when a TCP port currently accepts local connections."""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.settimeout(0.2)
            return sock.connect_ex((host, port)) == 0

    def ensure_tunnel(self, config: SshTunnelConfig, wait_seconds: float = 5.0) -> str:
        """Ensure a reusable SSH tunnel exists and is listening on the local port."""
        if not config.ssh_host.strip():
            raise SshTunnelError("ssh_host is required for automatic tunnel mode")

        if self._process is not None and self._process.poll() is None and self.port_is_open("127.0.0.1", config.local_port):
            return f"http://127.0.0.1:{config.local_port}"

        if self.port_is_open("127.0.0.1", config.local_port):
            return f"http://127.0.0.1:{config.local_port}"

        command = [
            "ssh",
            "-N",
            "-L",
            f"{config.local_port}:{config.remote_host}:{config.remote_port}",
            config.ssh_host,
        ]
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        start = time.time()
        while time.time() - start < wait_seconds:
            if process.poll() is not None:
                raise SshTunnelError("SSH tunnel process exited before tunnel became ready")
            if self.port_is_open("127.0.0.1", config.local_port):
                self._process = process
                return f"http://127.0.0.1:{config.local_port}"
            time.sleep(0.1)

        process.terminate()
        try:
            process.wait(timeout=2)
        except Exception:
            process.kill()
        raise SshTunnelError("Timed out waiting for SSH tunnel to become ready")

    def close(self) -> None:
        """Terminate the managed SSH tunnel if ORBIT created one."""
        if self._process is None:
            return
        if self._process.poll() is None:
            self._process.terminate()
            try:
                self._process.wait(timeout=2)
            except Exception:
                self._process.kill()
        self._process = None


@contextmanager
def open_ssh_tunnel(config: SshTunnelConfig, wait_seconds: float = 5.0):
    """Compatibility context manager for code paths that still expect scoped tunnel usage."""
    manager = SshTunnelManager()
    local_base = manager.ensure_tunnel(config, wait_seconds=wait_seconds)
    try:
        yield local_base
    finally:
        manager.close()
