from __future__ import annotations

from pathlib import Path


def resolve_workspace_root(raw_root: str | Path) -> Path:
    root = Path(raw_root).expanduser().resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"workspace root is invalid: {root}")
    return root


def resolve_workspace_child_path(*, workspace_root: Path, raw_path: str) -> Path:
    if not isinstance(raw_path, str) or not raw_path.strip():
        raise ValueError("raw_path must be a non-empty string")
    workspace_resolved = workspace_root.resolve()
    candidate = Path(raw_path)
    resolved = candidate.resolve() if candidate.is_absolute() else (workspace_resolved / candidate).resolve()
    try:
        resolved.relative_to(workspace_resolved)
    except ValueError as exc:
        raise ValueError(f"path escapes workspace: {raw_path!r}") from exc
    return resolved


def resolve_workspace_child_paths(*, workspace_root: Path, raw_paths: list[str] | None) -> list[Path]:
    if not raw_paths:
        return []
    result: list[Path] = []
    for raw in raw_paths:
        if not isinstance(raw, str) or not raw.strip():
            continue
        result.append(resolve_workspace_child_path(workspace_root=workspace_root, raw_path=raw))
    return result


def resolve_workspace_optional_file(*, workspace_root: Path, raw_path: str | None) -> Path | None:
    if not raw_path or not str(raw_path).strip():
        return None
    return resolve_workspace_child_path(workspace_root=workspace_root, raw_path=raw_path)
