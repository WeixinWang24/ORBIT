from __future__ import annotations


def truncate_text(text: str, max_chars: int) -> tuple[str, bool]:
    if len(text) <= max_chars:
        return text, False
    return text[:max_chars], True


def preferred_raw_output(*, stdout: str, stderr: str) -> str:
    if stdout.strip():
        return stdout
    if stderr.strip():
        return stderr
    return ""
