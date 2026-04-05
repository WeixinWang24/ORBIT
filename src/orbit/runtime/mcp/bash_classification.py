from __future__ import annotations

_READ_ONLY_BASE_COMMANDS = {
    "pwd",
    "ls",
    "cat",
    "head",
    "tail",
    "wc",
    "grep",
    "rg",
    "find",
    "lsof",
    "ss",
    "netstat",
    "command",
}

_READ_ONLY_GIT_PREFIXES = {
    "git status",
    "git diff",
    "git log",
}

_READ_ONLY_FLAG_ALLOWLIST: dict[str, set[str]] = {
    "ls": {"-a", "-l", "-la", "-al", "-h", "-lh", "-hl"},
    "find": {"-name", "-type", "-maxdepth", "-mindepth"},
    "rg": {"-n", "-i", "-F", "-S", "-g", "--glob", "--hidden", "--no-ignore", "--files"},
    "grep": {"-n", "-i", "-F", "-E", "-R", "-r", "-l", "-L", "-c"},
}

_READ_ONLY_GIT_FLAG_ALLOWLIST: dict[str, set[str]] = {
    "git status": {"--short", "-s", "--branch", "-b"},
    "git diff": {"--stat", "--name-only", "--cached", "--staged"},
    "git log": {"--oneline", "-n", "--stat"},
}

_HIGH_RISK_TOKENS = ["\n", ";", "&&", "||", "|", ">", "<", "$(", "${", "`", "<<"]


def _tokens_are_read_only_safe(base_command: str, tokens: list[str]) -> bool:
    allowed = _READ_ONLY_FLAG_ALLOWLIST.get(base_command)
    if allowed is None:
        return True
    i = 1
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            if token not in allowed:
                return False
            if base_command == "find" and token in {"-name", "-type", "-maxdepth", "-mindepth"}:
                i += 2
                continue
            if base_command in {"rg", "grep"} and token in {"-g", "--glob"}:
                i += 2
                continue
        i += 1
    return True


def _git_tokens_are_read_only_safe(prefix: str, tokens: list[str]) -> bool:
    allowed = _READ_ONLY_GIT_FLAG_ALLOWLIST.get(prefix)
    if allowed is None:
        return True
    i = 2
    while i < len(tokens):
        token = tokens[i]
        if token.startswith("-"):
            if token not in allowed:
                return False
            if prefix == "git log" and token == "-n":
                i += 2
                continue
        i += 1
    return True


def _classify_simple_segment(stripped: str) -> tuple[str, str]:
    if not stripped:
        return "ambiguous", "empty_segment"
    tokens = stripped.split()
    first_word = tokens[0] if tokens else ""
    if "=" in first_word and not first_word.startswith(("./", "/")):
        return "ambiguous", "env_assignment_prefix"
    if first_word in _READ_ONLY_BASE_COMMANDS:
        if _tokens_are_read_only_safe(first_word, tokens):
            return "read_only", f"read_only_base_command:{first_word}"
        return "mutating", f"non_allowlisted_flags:{first_word}"
    for prefix in _READ_ONLY_GIT_PREFIXES:
        prefix_tokens = prefix.split()
        if tokens[: len(prefix_tokens)] == prefix_tokens:
            if _git_tokens_are_read_only_safe(prefix, tokens):
                return "read_only", "read_only_git_command"
            return "mutating", f"non_allowlisted_flags:{prefix.replace(' ', '_')}"
    return "mutating", "non_allowlisted_command"


def _classify_read_only_chain(command: str) -> tuple[str, str] | None:
    normalized = command.replace("(", " ").replace(")", " ")
    for op in ["&&", "||", "|"]:
        normalized = normalized.replace(op, " ; ")
    segments = [segment.strip() for segment in normalized.split(";") if segment.strip()]
    if len(segments) <= 1:
        return None
    reasons: list[str] = []
    for segment in segments:
        classification, reason = _classify_simple_segment(segment)
        if classification != "read_only":
            return None
        reasons.append(reason)
    return "read_only", "read_only_chain:" + ",".join(reasons)


def classify_bash_command(command: str) -> tuple[str, str]:
    stripped = command.strip()
    if not stripped:
        return "ambiguous", "empty_command"
    if stripped.startswith(" ") or stripped.startswith("\t"):
        return "ambiguous", "leading_whitespace_fragment"
    chain_result = _classify_read_only_chain(command)
    if chain_result is not None:
        return chain_result
    for token in _HIGH_RISK_TOKENS:
        if token in command:
            return "ambiguous", f"contains_{token.encode('unicode_escape').decode('ascii')}"
    return _classify_simple_segment(stripped)
