from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class UnifiedPatchHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    section_header: str
    lines: list[str]


_HUNK_HEADER_RE = re.compile(
    r"^@@\s+-(?P<old_start>\d+)(?:,(?P<old_count>\d+))?\s+\+(?P<new_start>\d+)(?:,(?P<new_count>\d+))?\s+@@(?P<section>.*)$"
)


def parse_unified_patch(patch: str) -> tuple[str | None, list[UnifiedPatchHunk]]:
    if not isinstance(patch, str) or not patch.strip():
        raise ValueError("patch must be a non-empty string")

    lines = patch.splitlines()
    current_path: str | None = None
    hunks: list[UnifiedPatchHunk] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if line.startswith("+++ "):
            plus_path = line[4:].strip()
            if plus_path.startswith("b/"):
                plus_path = plus_path[2:]
            current_path = plus_path
            index += 1
            continue
        if line.startswith("@@ "):
            match = _HUNK_HEADER_RE.match(line)
            if match is None:
                raise ValueError(f"invalid unified patch hunk header: {line}")
            hunk_lines: list[str] = []
            index += 1
            while index < len(lines):
                candidate = lines[index]
                if candidate.startswith("@@ "):
                    break
                if candidate.startswith("--- ") or candidate.startswith("+++ "):
                    break
                if candidate.startswith((" ", "+", "-")) or candidate == "\\ No newline at end of file":
                    hunk_lines.append(candidate)
                    index += 1
                    continue
                raise ValueError(f"invalid unified patch body line: {candidate}")
            hunks.append(
                UnifiedPatchHunk(
                    old_start=int(match.group("old_start")),
                    old_count=int(match.group("old_count") or "1"),
                    new_start=int(match.group("new_start")),
                    new_count=int(match.group("new_count") or "1"),
                    section_header=(match.group("section") or "").strip(),
                    lines=hunk_lines,
                )
            )
            continue
        index += 1

    if not hunks:
        raise ValueError("patch must include at least one unified diff hunk")
    return current_path, hunks


def apply_unified_patch_to_text(original_text: str, hunks: list[UnifiedPatchHunk]) -> dict[str, Any]:
    original_lines = original_text.splitlines(keepends=True)
    result_lines: list[str] = []
    cursor = 0
    applied_hunks = 0

    for hunk in hunks:
        expected_old_lines = _extract_expected_old_lines(hunk.lines)
        replacement_lines = _extract_replacement_lines(hunk.lines)
        start_index = max(0, hunk.old_start - 1)

        if start_index < cursor:
            return {
                "ok": False,
                "failure_layer": "tool_semantic",
                "failure_kind": "overlapping_hunks",
                "change_summary": "overlapping hunks are not supported",
                "applied_hunk_count": applied_hunks,
            }

        end_index = start_index + len(expected_old_lines)
        actual_slice = original_lines[start_index:end_index]
        if actual_slice != expected_old_lines:
            return {
                "ok": False,
                "failure_layer": "tool_semantic",
                "failure_kind": "hunk_context_mismatch",
                "change_summary": f"hunk starting at old line {hunk.old_start} did not match current file contents",
                "applied_hunk_count": applied_hunks,
                "failed_hunk": {
                    "old_start": hunk.old_start,
                    "old_count": hunk.old_count,
                    "new_start": hunk.new_start,
                    "new_count": hunk.new_count,
                    "section_header": hunk.section_header,
                },
            }

        result_lines.extend(original_lines[cursor:start_index])
        result_lines.extend(replacement_lines)
        cursor = end_index
        applied_hunks += 1

    result_lines.extend(original_lines[cursor:])
    return {
        "ok": True,
        "updated_text": "".join(result_lines),
        "applied_hunk_count": applied_hunks,
        "hunk_count": len(hunks),
        "change_summary": f"applied {applied_hunks} unified patch hunk(s)",
    }


def apply_unified_patch_to_file(*, workspace_root: Path, path: str, patch: str) -> dict[str, Any]:
    if not isinstance(path, str) or not path.strip():
        raise ValueError("path must be a non-empty string")
    candidate = Path(path)
    if candidate.is_absolute():
        raise ValueError("absolute paths are not allowed")

    workspace_root = workspace_root.resolve()
    target = (workspace_root / candidate).resolve()
    try:
        target.relative_to(workspace_root)
    except ValueError as exc:
        raise ValueError("path escapes workspace") from exc
    if not target.exists() or not target.is_file():
        raise ValueError("path is not a file")

    declared_path, hunks = parse_unified_patch(patch)
    if declared_path and declared_path not in {path, str(candidate), target.name}:
        return {
            "ok": False,
            "failure_layer": "tool_semantic",
            "failure_kind": "patch_path_mismatch",
            "change_summary": f"patch declared path {declared_path} but tool target path is {path}",
        }

    original_text = target.read_text(encoding="utf-8")
    applied = apply_unified_patch_to_text(original_text, hunks)
    if not applied.get("ok"):
        return applied

    target.write_text(applied["updated_text"], encoding="utf-8")
    return {
        "ok": True,
        "mutation_kind": "apply_unified_patch",
        "path": path,
        "hunk_count": applied["hunk_count"],
        "applied_hunk_count": applied["applied_hunk_count"],
        "change_summary": applied["change_summary"],
    }


def _extract_expected_old_lines(lines: list[str]) -> list[str]:
    extracted: list[str] = []
    for line in lines:
        if line == "\\ No newline at end of file":
            continue
        prefix = line[:1]
        body = line[1:]
        if prefix in {" ", "-"}:
            extracted.append(body + "\n")
    return extracted


def _extract_replacement_lines(lines: list[str]) -> list[str]:
    extracted: list[str] = []
    for line in lines:
        if line == "\\ No newline at end of file":
            continue
        prefix = line[:1]
        body = line[1:]
        if prefix in {" ", "+"}:
            extracted.append(body + "\n")
    return extracted
