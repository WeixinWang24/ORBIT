from __future__ import annotations

import unittest

from orbit.interfaces.runtime_adapter import SessionManagerRuntimeAdapter, build_codex_session_manager
from orbit.runtime.governance.protocol.mode import mode_policy_summary, workspace_root_for_runtime_mode
from orbit.settings import DEFAULT_WORKSPACE_ROOT, REPO_ROOT


class CliSessionWiringTests(unittest.TestCase):
    def testbuild_codex_session_manager_registers_full_stack_mcp_tools_when_enabled(self):
        sm = build_codex_session_manager(
            model="gpt-5.4",
            enable_tools=True,
            enable_mcp_filesystem=True,
            enable_mcp_bash=True,
            enable_mcp_process=True,
        )

        tool_names = {tool.name for tool in sm.tool_registry.list_tools()}

        self.assertIn("read_file", tool_names)
        self.assertIn("search_files", tool_names)
        self.assertIn("todo_write", tool_names)
        self.assertIn("todo_read", tool_names)
        self.assertIn("web_fetch", tool_names)
        self.assertIn("run_bash", tool_names)
        self.assertIn("start_process", tool_names)
        self.assertIn("read_process_output", tool_names)
        self.assertIn("wait_process", tool_names)
        self.assertIn("terminate_process", tool_names)

        backend_registry = getattr(sm.backend, "tool_registry", None)
        self.assertIsNotNone(backend_registry)
        backend_tool_names = {tool.name for tool in backend_registry.list_tools()}
        self.assertEqual(tool_names, backend_tool_names)

    def testbuild_codex_session_manager_defaults_mount_codex_tooling_stack(self):
        sm = build_codex_session_manager(model="gpt-5.4")

        tool_names = {tool.name for tool in sm.tool_registry.list_tools()}
        self.assertIn("web_fetch", tool_names)
        self.assertIn("todo_read", tool_names)
        self.assertIn("todo_write", tool_names)

        backend_registry = getattr(sm.backend, "tool_registry", None)
        self.assertIsNotNone(backend_registry)
        backend_tool_names = {tool.name for tool in backend_registry.list_tools()}
        self.assertIn("web_fetch", backend_tool_names)
        self.assertIn("todo_read", backend_tool_names)
        self.assertIn("todo_write", backend_tool_names)

        inventory = sm.tool_registry.get("native__list_available_tools").invoke()
        self.assertTrue(inventory.ok)
        inventory_names = {tool["name"] for tool in inventory.data["tools"]}
        self.assertIn("web_fetch", inventory_names)
        self.assertIn("todo_read", inventory_names)
        self.assertIn("todo_write", inventory_names)

    def testbuild_codex_session_manager_defaults_to_dev_runtime_mode(self):
        sm = build_codex_session_manager(model="gpt-5.4")
        self.assertEqual(sm.runtime_mode, "dev")

        session = sm.create_session(backend_name="openai-codex", model="gpt-5.4")
        self.assertEqual(session.runtime_mode, "dev")

    def testbuild_codex_session_manager_accepts_evo_runtime_mode(self):
        sm = build_codex_session_manager(model="gpt-5.4", runtime_mode="evo")
        self.assertEqual(sm.runtime_mode, "evo")

        session = sm.create_session(backend_name="openai-codex", model="gpt-5.4")
        self.assertEqual(session.runtime_mode, "evo")

    def testworkspace_root_for_runtime_mode_distinguishes_dev_and_evo(self):
        self.assertEqual(workspace_root_for_runtime_mode("dev"), DEFAULT_WORKSPACE_ROOT)
        self.assertEqual(workspace_root_for_runtime_mode("evo"), REPO_ROOT)

    def testmode_policy_summary_distinguishes_dev_and_evo(self):
        self.assertEqual(mode_policy_summary("dev")["mode_policy_profile"], "dev-default")
        self.assertEqual(mode_policy_summary("dev")["self_runtime_visibility"], "workspace_only")
        self.assertEqual(mode_policy_summary("dev")["self_modification_posture"], "not_enabled")
        self.assertEqual(mode_policy_summary("evo")["mode_policy_profile"], "evo-phase-a")
        self.assertEqual(mode_policy_summary("evo")["self_runtime_visibility"], "repo_root")
        self.assertEqual(mode_policy_summary("evo")["self_modification_posture"], "phase_a_read_heavy")

    def testbuild_codex_session_manager_uses_workspace_folder_in_dev_mode(self):
        sm = build_codex_session_manager(model="gpt-5.4", runtime_mode="dev")
        self.assertEqual(sm.workspace_root, str(DEFAULT_WORKSPACE_ROOT))
        self.assertEqual(str(sm.backend.workspace_root), str(DEFAULT_WORKSPACE_ROOT))

    def testbuild_codex_session_manager_uses_repo_root_in_evo_mode(self):
        sm = build_codex_session_manager(model="gpt-5.4", runtime_mode="evo")
        self.assertEqual(sm.workspace_root, str(REPO_ROOT))
        self.assertEqual(str(sm.backend.workspace_root), str(REPO_ROOT))
        self.assertEqual(str(sm.tool_registry.get("native__read_file").workspace_root), str(REPO_ROOT))

    def testruntime_adapter_can_create_evo_session(self):
        adapter = SessionManagerRuntimeAdapter.build()
        session = adapter.create_session(runtime_mode="evo")
        self.assertEqual(session.status, "active")
        self.assertEqual(session.runtime_mode, "evo")

        stored = adapter.session_manager.get_session(session.session_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.runtime_mode, "evo")

    def testruntime_adapter_built_in_evo_mode_exposes_mode_and_workspace_in_audit_surface(self):
        adapter = SessionManagerRuntimeAdapter.build(config=type("Cfg", (), {"model": "gpt-5.4", "runtime_mode": "evo", "enable_tools": True, "enable_mcp_filesystem": True, "enable_mcp_git": True, "enable_mcp_bash": True, "enable_mcp_process": True})())
        session = adapter.create_session()
        self.assertEqual(session.runtime_mode, "evo")
        self.assertEqual(session.workspace_root, str(REPO_ROOT))
        self.assertEqual(session.mode_policy_profile, "evo-phase-a")
        self.assertEqual(session.self_runtime_visibility, "repo_root")
        self.assertEqual(session.self_modification_posture, "phase_a_read_heavy")

        stored = adapter.session_manager.get_session(session.session_id)
        self.assertIsNotNone(stored)
        mode_policy = stored.metadata.get("mode_policy")
        self.assertEqual(mode_policy["mode_policy_profile"], "evo-phase-a")
        self.assertEqual(mode_policy["self_runtime_visibility"], "repo_root")
        self.assertEqual(mode_policy["self_modification_posture"], "phase_a_read_heavy")
        self.assertEqual(mode_policy["workspace_root"], str(REPO_ROOT))

        fetched = adapter.get_session(session.session_id)
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.runtime_mode, "evo")
        self.assertEqual(fetched.workspace_root, str(REPO_ROOT))
        self.assertEqual(fetched.mode_policy_profile, "evo-phase-a")
        self.assertEqual(fetched.self_runtime_visibility, "repo_root")
        self.assertEqual(fetched.self_modification_posture, "phase_a_read_heavy")

        status = adapter.get_workbench_status()
        self.assertEqual(status["runtime_mode"], "evo")
        self.assertEqual(status["workspace_root"], str(REPO_ROOT))
        self.assertEqual(status["mode_policy_profile"], "evo-phase-a")
        self.assertEqual(status["self_runtime_visibility"], "repo_root")
        self.assertEqual(status["self_modification_posture"], "phase_a_read_heavy")


if __name__ == "__main__":
    unittest.main()
