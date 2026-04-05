from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace

from orbit.interfaces.contracts import InterfaceApproval, InterfaceArtifact, InterfaceEvent, InterfaceMessage, InterfaceSession, InterfaceToolCall
from orbit.interfaces.input import ParsedKey
from orbit.interfaces.pty_runtime_router import route_slash_command, submit_composer
from orbit.interfaces.runtime_cli_handlers import (
    handle_approvals_key,
    handle_chat_key,
    handle_info_panel_key,
    handle_inspect_key,
    handle_sessions_key,
)
from orbit.interfaces.runtime_cli_render import frame_lines
from orbit.interfaces.runtime_cli_state import (
    APPROVALS_MODE,
    CHAT_MODE,
    HELP_MODE,
    INSPECT_MODE,
    SESSIONS_MODE,
    STATUS_MODE,
    RuntimeCliState,
)


class MockOrbitChatAdapter:
    def __init__(self, *, runtime_mode: str = "dev", workspace_root: str = "/mock/workspace") -> None:
        self.runtime_mode = runtime_mode
        self.workspace_root = workspace_root
        self._sessions: list[InterfaceSession] = []
        self._messages: dict[str, list[InterfaceMessage]] = {}
        self._artifacts: dict[str, list[InterfaceArtifact]] = {}
        self._next = 0
        self.create_session()

    def _new_session_id(self) -> str:
        self._next += 1
        return f"mock-session-{self._next}"

    def create_session(self, *, backend_name: str = "mock", model: str | None = None) -> InterfaceSession:
        session_id = self._new_session_id()
        mode_policy_profile = "evo-phase-a" if self.runtime_mode == "evo" else "dev-default"
        self_runtime_visibility = "repo_root" if self.runtime_mode == "evo" else "workspace_only"
        self_modification_posture = "phase_a_read_heavy" if self.runtime_mode == "evo" else "not_enabled"
        session = InterfaceSession(
            session_id=session_id,
            conversation_id=f"conv-{session_id}",
            backend_name=backend_name,
            model=model or "mock-model",
            runtime_mode=self.runtime_mode,
            workspace_root=self.workspace_root,
            mode_policy_profile=mode_policy_profile,
            self_runtime_visibility=self_runtime_visibility,
            self_modification_posture=self_modification_posture,
            updated_at=datetime.now(timezone.utc),
            status="active",
        )
        self._sessions.insert(0, session)
        self._messages[session_id] = []
        return session

    def attach_session(self, session_id: str) -> InterfaceSession | None:
        return next((s for s in self._sessions if s.session_id == session_id), None)

    def get_session(self, session_id: str) -> InterfaceSession | None:
        return self.attach_session(session_id)

    def list_sessions(self) -> list[InterfaceSession]:
        return list(self._sessions)

    def list_messages(self, session_id: str) -> list[InterfaceMessage]:
        return list(self._messages.get(session_id, []))

    def list_events(self, session_id: str) -> list[InterfaceEvent]:
        return []

    def list_artifacts(self, session_id: str) -> list[InterfaceArtifact]:
        return list(self._artifacts.get(session_id, []))

    def list_tool_calls(self, session_id: str) -> list[InterfaceToolCall]:
        return []

    def list_open_approvals(self) -> list[InterfaceApproval]:
        return []

    def send_user_message(self, session_id: str, text: str) -> list[InterfaceMessage]:
        self._messages.setdefault(session_id, []).append(
            InterfaceMessage(session_id=session_id, role="user", content=text, turn_index=len(self._messages[session_id]) + 1)
        )
        self._messages[session_id].append(
            InterfaceMessage(session_id=session_id, role="assistant", content="mock reply", turn_index=len(self._messages[session_id]) + 1)
        )
        return self.list_messages(session_id)

    def append_system_message(self, session_id: str, text: str, *, kind: str = "system") -> InterfaceMessage:
        message = InterfaceMessage(
            session_id=session_id,
            role="assistant",
            content=text,
            turn_index=len(self._messages.setdefault(session_id, [])) + 1,
            message_kind=kind,
            metadata={"message_kind": kind},
        )
        self._messages[session_id].append(message)
        return message

    def slash_help_text(self) -> str:
        return "mock help"

    def slash_help_page(self) -> str:
        return "mock help page"

    def get_workbench_status(self) -> dict:
        return {
            "adapter_kind": "mock",
            "runtime_mode": self.runtime_mode,
            "workspace_root": self.workspace_root,
            "mode_policy_profile": "evo-phase-a" if self.runtime_mode == "evo" else "dev-default",
            "self_runtime_visibility": "repo_root" if self.runtime_mode == "evo" else "workspace_only",
            "self_modification_posture": "phase_a_read_heavy" if self.runtime_mode == "evo" else "not_enabled",
            "active_build_id": "stable-build-001" if self.runtime_mode == "evo" else None,
            "candidate_build_id": "candidate-build-002" if self.runtime_mode == "evo" else None,
            "last_known_good_build_id": "stable-build-000" if self.runtime_mode == "evo" else None,
            "session_count": len(self._sessions),
            "approval_count": 0,
            "registered_tool_count": 1,
            "registered_tool_names": ["native__list_available_tools"],
        }

    def get_pending_approval(self, session_id: str):
        return None

    def resolve_pending_approval(self, session_id: str, decision: str, note: str | None = None):
        return None

    def reauthorize_tool_path(self, session_id: str, tool_name: str, note: str | None = None, source: str = "runtime_cli"):
        return None

    def get_session_state_payload(self, session_id: str) -> dict | None:
        session = self.get_session(session_id)
        return session.model_dump(mode="json") if session is not None else None

    def append_context_artifact(self, session_id: str, artifact_type: str, content: str, source: str):
        artifact = InterfaceArtifact(session_id=session_id, artifact_type=artifact_type, content=content, source=source)
        self._artifacts.setdefault(session_id, []).append(artifact)
        return artifact

    def clear_session(self, session_id: str) -> bool:
        self._sessions = [s for s in self._sessions if s.session_id != session_id]
        self._messages.pop(session_id, None)
        return True

    def clear_all_sessions(self) -> bool:
        self._sessions = []
        self._messages = {}
        return True

    def wipe_session_history(self) -> bool:
        return self.clear_all_sessions()


def test_runtime_cli_mainline_semantics_roundtrip() -> None:
    adapter = MockOrbitChatAdapter()
    state = RuntimeCliState()

    state.composer.text = "/sessions"
    submit_composer(state, adapter)
    assert state.mode == SESSIONS_MODE

    handle_sessions_key(state, adapter, ParsedKey(name="a", sequence="a"))
    assert state.mode == APPROVALS_MODE

    handle_approvals_key(state, adapter, ParsedKey(name="s", sequence="s"))
    assert state.mode == SESSIONS_MODE

    handle_sessions_key(state, adapter, ParsedKey(name="enter", sequence="\r"))
    assert state.mode == CHAT_MODE
    assert state.banner.startswith("Attached to ")

    state.composer.text = "/events"
    submit_composer(state, adapter)
    assert state.mode == INSPECT_MODE
    assert state.tab_index == 1

    handle_inspect_key(state, adapter, ParsedKey(name="tab", sequence="\t"))
    assert state.tab_index == 2

    handle_inspect_key(state, adapter, ParsedKey(name="tab", sequence="\x1b[Z", shift=True))
    assert state.tab_index == 1

    handle_inspect_key(state, adapter, ParsedKey(name="c", sequence="c"))
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/help")
    assert state.mode == HELP_MODE

    handle_info_panel_key(state, ParsedKey(name="c", sequence="c"))
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/status")
    assert state.mode == STATUS_MODE

    route_slash_command(state, adapter, "/self-audit")
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/show")
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/state")
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/detach")
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/clear")
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/clear-all")
    assert state.mode == CHAT_MODE

    adapter.create_session()
    adapter.create_session()
    state.active_session_id = adapter.list_sessions()[1].session_id
    state.selected_session = 1
    assert handle_chat_key(state, adapter, ParsedKey(name="right", sequence="\x1b[C")) is True
    assert state.active_session_id == adapter.list_sessions()[2].session_id
    assert handle_chat_key(state, adapter, ParsedKey(name="left", sequence="\x1b[D")) is True
    assert state.active_session_id == adapter.list_sessions()[1].session_id

    route_slash_command(state, adapter, "/pending")
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/approve test-note")
    assert state.mode == CHAT_MODE

    chat_frame = frame_lines(RuntimeCliState(mode=CHAT_MODE), adapter).lines
    assert any("[INPUT]" in line for line in chat_frame)

    nav_frame = frame_lines(RuntimeCliState(mode=SESSIONS_MODE), adapter).lines
    assert any("[NAV]" in line for line in nav_frame)


def test_self_audit_is_blocked_in_non_evo_mode() -> None:
    adapter = MockOrbitChatAdapter()
    state = RuntimeCliState()

    route_slash_command(state, adapter, "/self-audit")

    assert state.mode == CHAT_MODE
    assert state.banner == "Self-audit requires evo mode"
    session_id = adapter.list_sessions()[0].session_id
    messages = adapter.list_messages(session_id)
    assert any(msg.message_kind == "self_audit_blocked" for msg in messages)


def test_self_audit_is_available_in_evo_mode() -> None:
    adapter = MockOrbitChatAdapter(runtime_mode="evo", workspace_root="/Volumes/2TB/MAS/openclaw-core/ORBIT")
    state = RuntimeCliState()

    route_slash_command(state, adapter, "/self-audit")

    assert state.mode == CHAT_MODE
    assert state.banner == "Self-audit bootstrap ready"
    session_id = adapter.list_sessions()[0].session_id
    messages = adapter.list_messages(session_id)
    ready_messages = [msg for msg in messages if msg.message_kind == "self_audit_report"]
    assert ready_messages
    assert "SELF-AUDIT BOOTSTRAP REPORT" in ready_messages[-1].content
    assert "runtime_mode=evo" in ready_messages[-1].content
    assert "self_modification_posture=phase_a_read_heavy" in ready_messages[-1].content
    assert "native_list_available_tools_present=True" in ready_messages[-1].content
    assert "build_state:" in ready_messages[-1].content
    assert "active_build_id=stable-build-001" in ready_messages[-1].content
    assert "candidate_build_id=candidate-build-002" in ready_messages[-1].content
    assert "last_known_good_build_id=stable-build-000" in ready_messages[-1].content
    assert "first_evidence_collection:" in ready_messages[-1].content
    assert "src/orbit/runtime/governance/protocol/mode.py: exists=True bytes=" in ready_messages[-1].content
    assert "header=from __future__ import annotations" in ready_messages[-1].content
    assert "phase_a_evidence_checklist:" in ready_messages[-1].content
    assert "STRUCTURED_PAYLOAD_JSON" in ready_messages[-1].content
    assert '"artifact_type": "self_audit_bootstrap"' in ready_messages[-1].content
    assert '"schema_version": "v1"' in ready_messages[-1].content
    assert '"phase": "phase_a"' in ready_messages[-1].content
    assert '"report_kind": "self_audit_bootstrap"' in ready_messages[-1].content
    assert '"build_state"' in ready_messages[-1].content
    assert '"active_build_id": "stable-build-001"' in ready_messages[-1].content
    assert '"source_paths"' in ready_messages[-1].content
    assert '"key_runtime_paths"' in ready_messages[-1].content

    artifacts = adapter.list_artifacts(session_id)
    bootstrap_artifacts = [art for art in artifacts if art.artifact_type == "self_audit_bootstrap"]
    assert bootstrap_artifacts
    assert bootstrap_artifacts[-1].source == "self_audit_entrypoint"
    assert '"artifact_type": "self_audit_bootstrap"' in bootstrap_artifacts[-1].content
    assert '"schema_version": "v1"' in bootstrap_artifacts[-1].content
