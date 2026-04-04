"""Thin application entrypoint wrapper for the runtime-first ORBIT CLI."""

from orbit.interfaces.pty_runtime_cli import browse_runtime_cli


if __name__ == "__main__":
    browse_runtime_cli()
