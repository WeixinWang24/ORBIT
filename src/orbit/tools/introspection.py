from __future__ import annotations

from typing import Any

from .base import Tool, ToolResult


class ListAvailableToolsTool(Tool):
    name = "native__list_available_tools"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "none"

    def __init__(self, registry_getter):
        self._registry_getter = registry_getter

    def invoke(self) -> ToolResult:
        registry = self._registry_getter()
        tools = [self._serialize_tool(tool) for tool in registry.list_tools()]
        excluded_inventory_tools = {"native__list_available_tools", "native__describe_tool"}
        tools = [tool for tool in tools if tool.get("name") not in excluded_inventory_tools]
        grouped: dict[str, list[dict[str, Any]]] = {}
        enriched_tools = [self._enrich_tool_metadata(tool) for tool in tools]
        for tool in enriched_tools:
            group_name = tool.get("server_name") or ("native" if tool.get("tool_source") == "native" else "unknown")
            grouped.setdefault(group_name, []).append(tool)
        servers = [
            {
                "server_name": group_name,
                "purpose": self._group_purpose(group_name),
                "when_to_use": self._group_when_to_use(group_name),
                "when_not_to_use": self._group_when_not_to_use(group_name),
                "tool_count": len(items),
                "tool_names": sorted(item["name"] for item in items),
            }
            for group_name, items in sorted(grouped.items(), key=lambda pair: pair[0])
        ]
        capability_family_groups: dict[str, list[dict[str, Any]]] = {}
        for tool in enriched_tools:
            family_name = str(tool.get("capability_family") or "unknown")
            capability_family_groups.setdefault(family_name, []).append(tool)
        capability_families = [
            {
                "family_name": family_name,
                "summary": self._family_summary(family_name),
                "maturity": self._family_maturity(family_name),
                "lifecycle_status": self._family_lifecycle_status(family_name),
                "workflow_closure_status": self._family_workflow_closure_status(family_name),
                "tool_names": sorted(item["name"] for item in items),
                "known_limits": self._family_known_limits(family_name),
                "recommended_when_to_use": self._family_when_to_use(family_name),
                "recommended_when_not_to_use": self._family_when_not_to_use(family_name),
            }
            for family_name, items in sorted(capability_family_groups.items(), key=lambda pair: pair[0])
        ]
        tool_names = [tool["name"] for tool in enriched_tools]
        return ToolResult(
            ok=True,
            content=(
                f"{len(enriched_tools)} tools available across {len(servers)} capability groups and {len(capability_families)} capability families. "
                "The authoritative callable set is in canonical_tool_names. Treat that field as the exact callable inventory."
            ),
            data={
                "tool_count": len(enriched_tools),
                "callable_tool_count": len(enriched_tools),
                "inventory_excludes": ["native__list_available_tools", "native__describe_tool"],
                "usage_guidance": {
                    "summary": "This tool always returns the full callable inventory once per decision point. Then either call native__describe_tool for one exact non-inventory tool or execute the chosen tool.",
                    "canonical_field_guidance": "canonical_tool_names is the authoritative exact callable set returned by this inventory. Use those names directly when choosing tools.",
                    "attribute_guidance": "Tool source, server_name, side_effect_class, requires_approval, governance policy, capability family, maturity, closure status, and related guidance are returned as attributes on each tool object rather than as input filters.",
                    "anti_loop_guidance": "This inventory intentionally excludes self-introspection tools from the candidate set to reduce self-referential loops. Do not repeatedly call native__list_available_tools; inspect the returned attributes instead.",
                    "detail_handoff_tool": "native__describe_tool",
                },
                "recommended_next_actions": [
                    "Inspect canonical_tool_names for the full exact callable set.",
                    "Inspect capability_families to see which workflows are already implemented versus still limited.",
                    "If one tool looks relevant, call native__describe_tool with that exact tool name.",
                    "If the task is clear enough, execute the chosen tool instead of listing again.",
                ],
                "servers": servers,
                "capability_families": capability_families,
                "canonical_tool_names": tool_names,
                "tool_names": tool_names,
                "tools": sorted(enriched_tools, key=lambda item: item["name"]),
            },
        )

    def _serialize_tool(self, tool: Tool) -> dict[str, Any]:
        descriptor = getattr(tool, "descriptor", None)
        return {
            "name": tool.name,
            "tool_source": getattr(tool, "tool_source", "native"),
            "server_name": getattr(tool, "server_name", None),
            "original_name": getattr(tool, "original_name", None),
            "description": getattr(descriptor, "description", None),
            "input_schema": getattr(descriptor, "input_schema", None),
            "side_effect_class": getattr(tool, "side_effect_class", "safe"),
            "requires_approval": bool(getattr(tool, "requires_approval", False)),
            "governance_policy_group": getattr(tool, "governance_policy_group", "system_environment"),
            "environment_check_kind": getattr(tool, "environment_check_kind", "none"),
        }

    def _enrich_tool_metadata(self, tool: dict[str, Any]) -> dict[str, Any]:
        enriched = dict(tool)
        capability_family = self._tool_capability_family(tool)
        enriched["callable_name"] = str(tool.get("name") or "")
        enriched["purpose_summary"] = self._tool_purpose_summary(tool)
        enriched["use_when"] = self._tool_use_when(tool)
        enriched["avoid_when"] = self._tool_avoid_when(tool)
        enriched["related_tools"] = self._tool_related_tools(tool)
        enriched["capability_family"] = capability_family
        enriched["family_summary"] = self._family_summary(capability_family)
        enriched["maturity"] = self._family_maturity(capability_family)
        enriched["lifecycle_status"] = self._family_lifecycle_status(capability_family)
        enriched["workflow_role"] = self._tool_workflow_role(tool, capability_family)
        enriched["workflow_closure_status"] = self._family_workflow_closure_status(capability_family)
        enriched["status_note"] = self._tool_status_note(tool, capability_family)
        enriched["known_limits"] = self._family_known_limits(capability_family)
        return enriched

    def _group_purpose(self, group_name: str) -> str:
        return {
            "native": "Runtime-native coordination, introspection, and core file tools.",
            "filesystem": "Workspace file reading, search, and file mutation tools.",
            "git": "Repository inspection and version-control tools.",
            "bash": "One-shot shell command execution inside the workspace.",
            "process": "Managed long-running process lifecycle and output tools.",
        }.get(group_name, "Capability group for related tools.")

    def _group_when_to_use(self, group_name: str) -> str:
        return {
            "native": "Use when you need runtime-level help, inventory, or a narrow built-in capability.",
            "filesystem": "Use when reading files, searching code/text, or mutating files directly.",
            "git": "Use when inspecting repo state, diffs, branches, staging, and commits.",
            "bash": "Use when you need a shell command, tests, builds, or other repo command execution.",
            "process": "Use when a task needs a long-running process you may poll, tail, or terminate later.",
        }.get(group_name, "Use when a tool in this capability family clearly matches the task.")

    def _group_when_not_to_use(self, group_name: str) -> str:
        return {
            "native": "Do not prefer native tools when a more specific MCP tool matches the task better.",
            "filesystem": "Do not use filesystem tools for repo-state questions better answered by git tools.",
            "git": "Do not use git tools for raw file reading or generic shell workflows better handled elsewhere.",
            "bash": "Do not use run_bash when a more specific tool already exists for the task.",
            "process": "Do not use process tools for one-shot shell commands that should just run and return.",
        }.get(group_name, "Avoid this group when another capability family is a clearer fit.")

    def _tool_purpose_summary(self, tool: dict[str, Any]) -> str:
        name = str(tool.get("name") or "")
        description = str(tool.get("description") or "").strip()
        if description:
            return description
        return f"Tool for {name}."

    def _tool_use_when(self, tool: dict[str, Any]) -> str:
        name = str(tool.get("name") or "")
        capability_family = self._tool_capability_family(tool)
        server = str(tool.get("server_name") or ("native" if tool.get("tool_source") == "native" else ""))
        if name == "run_bash":
            return "Use when you need to execute a one-shot shell command such as tests, builds, grep-like shell workflows, or repo commands."
        if capability_family == "runtime_tool_introspection":
            return "Use when you need the current callable tool inventory or a precise description of one available tool before deciding what to run."
        if capability_family == "grounded_filesystem_mutation":
            return "Use when you need approval-gated single-file mutation inside the workspace, especially after fresh grounding has already established read readiness."
        if capability_family == "filesystem_discovery_search":
            return "Use when you need workspace discovery, content search, or multi-language code navigation across the current Python-first and TS/JS-partial first slice."
        if capability_family == "planning_todos":
            return "Use when you need session-scoped structured todo tracking rather than freeform notes."
        if capability_family == "web_retrieval":
            return "Use when you need bounded remote text retrieval from a URL with strict SSL verification by default, not full browser automation."
        if capability_family == "browser_verification":
            return "Use when you need browser-backed Web UI truth for page opening, bounded snapshot inspection, lightweight interaction, console inspection, or screenshot evidence in the current first slice."
        if capability_family == "git_inspection":
            return "Use when the task is about repository state, diffs, commit history, or bounded repo inspection."
        if capability_family == "git_mutation":
            return "Use when you need approval-gated staging, restore, commit, or switching to an existing branch."
        if capability_family == "shell_execution":
            return "Use when a shell command is the clearest way to perform the task."
        if capability_family == "process_lifecycle":
            return "Use when a task needs a managed background process whose lifecycle and output must persist across service-instance boundaries and be inspected or terminated later."
        if server == "git":
            return "Use when the task is about repository state, diffs, branches, staging, commits, or checkout."
        if server == "filesystem":
            return "Use when reading files, searching workspace content, or directly mutating files."
        if server == "process":
            return "Use when a task needs a managed background process you can inspect or terminate later."
        if server == "bash":
            return "Use when a shell command is the clearest way to perform the task."
        return "Use when this tool is the clearest direct match for the task."

    def _tool_avoid_when(self, tool: dict[str, Any]) -> str:
        name = str(tool.get("name") or "")
        capability_family = self._tool_capability_family(tool)
        server = str(tool.get("server_name") or ("native" if tool.get("tool_source") == "native" else ""))
        if name == "run_bash":
            return "Avoid when a more specific native or MCP tool already exists for the task."
        if capability_family == "runtime_tool_introspection":
            return "Avoid repeated self-introspection loops once you already have enough inventory information to choose or execute a tool."
        if capability_family == "grounded_filesystem_mutation":
            return "Avoid when the task is still exploratory, when fresh grounding is absent, or when a semantic multi-file refactor is required."
        if capability_family == "filesystem_discovery_search":
            return "Avoid when repo-state or branch-aware answers are better served by git tools, or when the task needs deeper architecture-aware or parity-level TS/JS semantic analysis beyond the current first slice."
        if capability_family == "planning_todos":
            return "Avoid when you actually need long-term workspace memory or architecture notes rather than session-scoped task tracking."
        if capability_family == "web_retrieval":
            return "Avoid when the task needs browser automation, DOM interaction, screenshots, console/network observation, or a trust model that assumes bypassing certificate verification."
        if capability_family == "browser_verification":
            return "Avoid when bounded text retrieval alone is sufficient, or when the task needs a fuller browser automation suite beyond open/snapshot/click/type/console/screenshot."
        if capability_family == "git_inspection":
            return "Avoid for raw file content reading or generic shell execution."
        if capability_family == "git_mutation":
            return "Avoid when you need branch creation, reset, stash, merge, or rebase workflows that are not yet first-class tools here."
        if server == "git":
            return "Avoid for raw file content reading or generic shell execution."
        if server == "filesystem":
            return "Avoid when repo-state or branch-aware answers are better served by git tools."
        return "Avoid when a more specific tool already matches the task better."

    def _tool_related_tools(self, tool: dict[str, Any]) -> list[str]:
        name = str(tool.get("name") or "")
        server = str(tool.get("server_name") or ("native" if tool.get("tool_source") == "native" else ""))
        related_map = {
            "run_bash": ["start_process", "read_process_output", "wait_process"],
            "git_status": ["git_changed_files", "git_diff", "git_log"],
            "git_add": ["git_status", "git_diff", "git_commit"],
            "git_commit": ["git_status", "git_diff", "git_log"],
            "native__list_available_tools": ["native__describe_tool"],
            "native__describe_tool": ["native__list_available_tools"],
            "get_symbols_overview": ["find_symbol", "find_references", "read_symbol_body"],
            "find_symbol": ["get_symbols_overview", "find_references", "read_symbol_body"],
            "find_references": ["find_symbol", "read_symbol_body"],
            "read_symbol_body": ["get_symbols_overview", "find_symbol", "find_references"],
            "replace_in_file": ["read_file", "apply_unified_patch"],
            "apply_unified_patch": ["read_file", "replace_in_file"],
        }
        if name in related_map:
            return related_map[name]
        if server == "git":
            return ["git_status", "git_diff", "git_changed_files"]
        if server == "filesystem":
            return ["read_file", "search_files", "get_symbols_overview"]
        if server == "process":
            return ["start_process", "read_process_output", "wait_process", "terminate_process"]
        return []

    def _tool_capability_family(self, tool: dict[str, Any]) -> str:
        name = str(tool.get("name") or "")
        server = str(tool.get("server_name") or "")
        native_read_tools = {"native__read_file"}
        grounded_mutation_tools = {
            "native__write_file",
            "native__replace_in_file",
            "native__replace_all_in_file",
            "native__replace_block_in_file",
            "native__apply_exact_hunk",
            "write_file",
            "replace_in_file",
            "replace_all_in_file",
            "replace_block_in_file",
            "apply_exact_hunk",
            "apply_unified_patch",
        }
        filesystem_discovery_tools = {
            "read_file",
            "read_text_file",
            "read_media_file",
            "read_multiple_files",
            "list_directory",
            "list_directory_with_sizes",
            "directory_tree",
            "search_files",
            "glob",
            "grep",
            "get_file_info",
            "list_allowed_directories",
            "get_symbols_overview",
            "find_symbol",
            "find_references",
            "read_symbol_body",
        }
        planning_todo_tools = {"todo_read", "todo_write"}
        git_inspection_tools = {"git_status", "git_diff", "git_log", "git_show", "git_changed_files"}
        git_mutation_tools = {"git_add", "git_restore", "git_unstage", "git_commit", "git_checkout_branch"}
        process_tools = {"start_process", "read_process_output", "wait_process", "terminate_process"}

        if name in {"native__list_available_tools", "native__describe_tool"}:
            return "runtime_tool_introspection"
        if name in native_read_tools:
            return "native_filesystem_read"
        if name in grounded_mutation_tools:
            return "grounded_filesystem_mutation"
        if name in filesystem_discovery_tools:
            return "filesystem_discovery_search"
        if name in planning_todo_tools:
            return "planning_todos"
        if name == "web_fetch":
            return "web_retrieval"
        if name in {"browser_open", "browser_snapshot", "browser_click", "browser_type", "browser_console", "browser_screenshot"}:
            return "browser_verification"
        if name in git_inspection_tools:
            return "git_inspection"
        if name in git_mutation_tools:
            return "git_mutation"
        if name == "run_bash":
            return "shell_execution"
        if name in process_tools:
            return "process_lifecycle"
        if server == "git":
            return "git_inspection"
        if server == "filesystem":
            return "filesystem_discovery_search"
        if server == "bash":
            return "shell_execution"
        if server == "process":
            return "process_lifecycle"
        return "uncategorized"

    def _tool_workflow_role(self, tool: dict[str, Any], capability_family: str) -> str:
        name = str(tool.get("name") or "")
        if capability_family == "runtime_tool_introspection":
            return "inventory" if name == "native__list_available_tools" else "describe"
        if capability_family in {"native_filesystem_read", "filesystem_discovery_search", "git_inspection", "web_retrieval"}:
            return "inspect"
        if capability_family in {"grounded_filesystem_mutation", "git_mutation"}:
            return "mutate"
        if capability_family == "planning_todos":
            return "plan"
        if capability_family == "shell_execution":
            return "execute"
        if capability_family == "process_lifecycle":
            return "manage_runtime_process"
        return "general"

    def _tool_status_note(self, tool: dict[str, Any], capability_family: str) -> str:
        name = str(tool.get("name") or "")
        if capability_family == "runtime_tool_introspection":
            return "This tool is part of ORBIT's live runtime introspection surface over the assembled ToolRegistry truth; it is meant to reduce guessing about already-available tools."
        if capability_family == "grounded_filesystem_mutation":
            return "This tool belongs to ORBIT's live grounded filesystem mutation family, where approval and runtime-local grounding readiness both matter; it is not a planning stub."
        if capability_family == "git_inspection":
            return "This tool belongs to ORBIT's live MCP git inspection family, already runtime-wired and provider-exposed for bounded repository inspection."
        if capability_family == "git_mutation":
            return "This tool belongs to ORBIT's live MCP git mutation first slice, covering basic stage/restore/commit/existing-branch-checkout workflows."
        if capability_family == "web_retrieval":
            return "This tool is a retrieval-oriented first slice for bounded remote text fetches with strict certificate verification by default. SSL verification failures are reported separately from generic network failures; this is not a browser automation surface."
        if capability_family == "browser_verification":
            return "This tool belongs to ORBIT's browser-backed verification and light-interaction first slice. An MCP-hosted browser family now exists, but under the current stdio MCP client lifecycle browser continuity is not yet preserved across successive calls, so the native path remains the currently validated continuity-bearing implementation."
        if capability_family == "planning_todos":
            return "This tool is a session-scoped planning helper, not long-term workspace memory."
        if capability_family == "filesystem_discovery_search":
            return "This tool belongs to ORBIT's active filesystem discovery/search and code-navigation surface; TS/JS semantic first-slice support is present, but parity with Python and architecture-graph tooling remain incomplete."
        if capability_family == "native_filesystem_read":
            return "This is a live native read capability for direct file inspection in the workspace."
        if capability_family == "shell_execution":
            return "This is a live shell execution capability; prefer more specific tools first when available."
        if capability_family == "process_lifecycle":
            return "This is a live managed-process capability family for longer-running runtime tasks. Runner status files are the primary terminal truth, pid polling is fallback-only, and stdout/stderr offsets are treated as first-class persisted surfaces."
        return f"{name} is available in the assembled ORBIT runtime tool surface."

    def _family_summary(self, family_name: str) -> str:
        return {
            "runtime_tool_introspection": "Runtime-native inventory and per-tool explanation over the assembled ToolRegistry truth.",
            "native_filesystem_read": "Runtime-native single-file reading for direct workspace inspection.",
            "grounded_filesystem_mutation": "Approval-gated, grounding-aware single-file mutation family for exact edits and patch-style changes.",
            "filesystem_discovery_search": "Workspace discovery, content search, and multi-language code-navigation first slice.",
            "planning_todos": "Session-scoped structured todo planning helpers.",
            "web_retrieval": "Bounded remote text retrieval without browser-session semantics, using strict SSL verification by default.",
            "browser_verification": "Browser-backed Web UI verification and light-interaction surface for page open, bounded structured snapshot, click/type actions, console capture, and screenshot capture.",
            "git_inspection": "Read-oriented repository inspection family for status, diffs, history, and bounded commit/file views.",
            "git_mutation": "Approval-gated first-slice git mutation family for staging, restore, commit, and switching to an existing branch.",
            "shell_execution": "One-shot shell command execution surface.",
            "process_lifecycle": "Managed background process lifecycle and persisted output observation surface, with runner-status-first truth precedence.",
            "uncategorized": "Tools not yet mapped into a more specific capability family.",
        }.get(family_name, "Capability family in the ORBIT runtime tool surface.")

    def _family_maturity(self, family_name: str) -> str:
        return {
            "runtime_tool_introspection": "active",
            "native_filesystem_read": "active",
            "grounded_filesystem_mutation": "active_first_slice",
            "filesystem_discovery_search": "active",
            "planning_todos": "active_first_slice",
            "web_retrieval": "active_first_slice",
            "browser_verification": "active_first_slice",
            "git_inspection": "active_first_slice",
            "git_mutation": "active_first_slice",
            "shell_execution": "active",
            "process_lifecycle": "active_first_slice",
            "uncategorized": "partial",
        }.get(family_name, "partial")

    def _family_lifecycle_status(self, family_name: str) -> str:
        return {
            "runtime_tool_introspection": "runtime_native",
            "native_filesystem_read": "runtime_native",
            "grounded_filesystem_mutation": "runtime_wired_and_provider_exposed",
            "filesystem_discovery_search": "runtime_wired_and_provider_exposed",
            "planning_todos": "runtime_wired_and_provider_exposed",
            "web_retrieval": "runtime_wired_and_provider_exposed",
            "browser_verification": "runtime_native",
            "git_inspection": "runtime_wired_and_provider_exposed",
            "git_mutation": "runtime_wired_and_provider_exposed",
            "shell_execution": "runtime_wired_and_provider_exposed",
            "process_lifecycle": "runtime_wired_and_provider_exposed",
            "uncategorized": "partial",
        }.get(family_name, "partial")

    def _family_workflow_closure_status(self, family_name: str) -> str:
        return {
            "runtime_tool_introspection": "closed_for_callable_inventory_and_single_tool_description",
            "native_filesystem_read": "closed_for_basic_single_file_native_read",
            "grounded_filesystem_mutation": "closed_for_grounded_single_file_exact_mutation_first_slice",
            "filesystem_discovery_search": "closed_for_workspace_discovery_and_multi_language_symbol_navigation_first_slice",
            "planning_todos": "closed_for_session_scoped_structured_todo_tracking",
            "web_retrieval": "closed_for_bounded_remote_text_retrieval",
            "browser_verification": "closed_for_browser_open_snapshot_click_type_console_screenshot_first_slice",
            "git_inspection": "closed_for_basic_repository_inspection",
            "git_mutation": "closed_for_basic_stage_restore_commit_and_existing_branch_checkout",
            "shell_execution": "closed_for_one_shot_shell_command_execution",
            "process_lifecycle": "closed_for_truth_hardened_managed_background_process_control_first_slice",
            "uncategorized": "not_classified",
        }.get(family_name, "not_classified")

    def _family_known_limits(self, family_name: str) -> list[str]:
        return {
            "runtime_tool_introspection": [
                "does not yet provide a fully canonical roadmap or gap-analysis judgment",
                "family summaries are heuristic runtime metadata rather than reviewed KB truth",
            ],
            "native_filesystem_read": [
                "not a repo-state tool",
                "not a semantic symbol reader",
            ],
            "grounded_filesystem_mutation": [
                "no transactional multi-file refactor support yet",
                "no semantic rename support yet",
                "unified patch support is currently a bounded single-file first slice",
            ],
            "filesystem_discovery_search": [
                "TS/JS semantic first slice is present but remains partial relative to Python",
                "project-level architecture graphing is not yet first-class",
            ],
            "planning_todos": [
                "not long-term workspace memory",
                "not architecture knowledge persistence",
            ],
            "web_retrieval": [
                "not browser automation",
                "no DOM interaction, screenshots, or console/network inspection",
                "strict SSL verification remains enabled by default; this first slice does not provide a bypass flag",
                "SSL verification failures are surfaced separately from generic network failures",
            ],
            "browser_verification": [
                "no multi-tab orchestration or auth-profile management yet",
                "snapshot is intentionally bounded and does not expose a full raw DOM or general JS-eval surface",
                "element targeting is snapshot-local and currently depends on the latest snapshot projection",
            ],
            "git_inspection": [
                "no dedicated blame tool yet",
                "no richer history-analysis helpers beyond bounded log/show",
            ],
            "git_mutation": [
                "no branch creation tool yet",
                "no stash/reset/rebase/merge helpers yet",
            ],
            "shell_execution": [
                "less structured than a dedicated diagnostic or browser capability family",
            ],
            "process_lifecycle": [
                "process orchestration remains a bounded first slice rather than a named service manager",
                "stall detection and interactive-prompt watchdog behavior are not yet present",
                "completion notifications are not yet emitted; callers must poll",
                "runner-status truth is primary, but last-resort local fallback still exists when no persisted terminal artifact can be recovered",
            ],
            "uncategorized": [
                "tool family metadata has not yet been explicitly mapped",
            ],
        }.get(family_name, ["no explicit limits recorded"])

    def _family_when_to_use(self, family_name: str) -> str:
        return {
            "runtime_tool_introspection": "Use when deciding among currently callable tools and you want runtime truth rather than guessing from source layout.",
            "native_filesystem_read": "Use when you need a direct native read of one workspace file.",
            "grounded_filesystem_mutation": "Use when making exact single-file edits with approval and fresh grounding already in place or clearly intended.",
            "filesystem_discovery_search": "Use when exploring the workspace, searching text, or navigating the current multi-language symbol surface.",
            "planning_todos": "Use when you need structured short-horizon task tracking inside the current work session.",
            "web_retrieval": "Use when you need bounded text retrieval from a URL.",
            "browser_verification": "Use when you need browser-backed page verification, bounded UI-state inspection, light interaction, console inspection, or screenshot evidence.",
            "git_inspection": "Use when understanding repo state, diffs, or commit history.",
            "git_mutation": "Use when staging, restoring, committing, or switching to an already-existing branch.",
            "shell_execution": "Use when a one-shot shell command is the clearest implementation path.",
            "process_lifecycle": "Use when you need a managed background process with persisted lifecycle truth, incremental output reads, and later inspection or termination across service-instance boundaries.",
            "uncategorized": "Use when the tool still matches the task more clearly than any mapped family.",
        }.get(family_name, "Use when this family is the clearest fit.")

    def _family_when_not_to_use(self, family_name: str) -> str:
        return {
            "runtime_tool_introspection": "Do not keep relisting the inventory once you already know the relevant tool.",
            "native_filesystem_read": "Do not use for repo-state questions or semantic code navigation better handled elsewhere.",
            "grounded_filesystem_mutation": "Do not use for speculative exploration or multi-file semantic refactors not covered by the current first slice.",
            "filesystem_discovery_search": "Do not use when repo-aware git answers or browser/runtime interactions are the actual need.",
            "planning_todos": "Do not use as a substitute for durable workspace memory or architecture notes.",
            "web_retrieval": "Do not use when the task needs browser automation or rendered-page observation.",
            "browser_verification": "Do not treat this first slice as a full browser automation suite or a replacement for richer interaction tooling that does not yet exist.",
            "git_inspection": "Do not use for plain file-content reading or generic shell execution.",
            "git_mutation": "Do not use when the task needs unsupported higher-risk git workflows such as rebase or merge automation.",
            "shell_execution": "Do not use when a more specific first-class tool already exists.",
            "process_lifecycle": "Do not use for commands that should simply execute and return immediately.",
            "uncategorized": "Do not assume uncategorized tools represent a complete capability family.",
        }.get(family_name, "Avoid this family when another one is clearly more specific.")


class DescribeToolTool(Tool):
    name = "native__describe_tool"
    side_effect_class = "safe"
    requires_approval = False
    governance_policy_group = "system_environment"
    environment_check_kind = "none"

    def __init__(self, registry_getter):
        self._registry_getter = registry_getter
        self._inventory_helper = ListAvailableToolsTool(registry_getter)

    def invoke(self, *, name: str) -> ToolResult:
        if not isinstance(name, str) or not name.strip():
            return ToolResult(ok=False, content="name must be a non-empty string")
        registry = self._registry_getter()
        try:
            tool = registry.get(name)
        except KeyError:
            return ToolResult(ok=False, content=f"tool not found: {name}")
        payload = self._inventory_helper._enrich_tool_metadata(self._inventory_helper._serialize_tool(tool))
        return ToolResult(ok=True, content=f"described tool {tool.name}", data=payload)
