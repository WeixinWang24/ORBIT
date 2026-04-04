"""Prompt-toolkit based mock workbench for ORBIT.

This replaces the fragile raw-loop PTY prototype with a full-screen terminal UI
that handles layout and redraw more robustly.
"""

from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import FormattedTextControl
from prompt_toolkit.widgets import Frame

from .mock_adapter import MockOrbitInterfaceAdapter

SESSION_TABS = ["transcript", "events", "tool_calls", "artifacts"]


@dataclass
class WorkbenchState:
    mode: str = "sessions"
    selected_session: int = 0
    selected_approval: int = 0
    tab_index: int = 0
    show_help: bool = False


def _session_list_text(state: WorkbenchState, adapter: MockOrbitInterfaceAdapter) -> str:
    sessions = adapter.list_sessions()
    lines = ["Sessions"]
    for i, session in enumerate(sessions):
        prefix = ">" if i == state.selected_session and state.mode == "sessions" else " "
        lines.append(f"{prefix} {session.session_id}")
        lines.append(f"  {session.status} · {session.backend_name} · {session.model}")
    return "\n".join(lines)


def _approval_list_text(state: WorkbenchState, adapter: MockOrbitInterfaceAdapter) -> str:
    approvals = adapter.list_open_approvals()
    lines = ["Approvals"]
    if not approvals:
        lines.append("No pending approvals.")
        return "\n".join(lines)
    for i, approval in enumerate(approvals):
        prefix = ">" if i == state.selected_approval and state.mode == "approvals" else " "
        lines.append(f"{prefix} {approval.tool_name}")
        lines.append(f"  {approval.session_id} · {approval.status}")
    return "\n".join(lines)


def _main_text(state: WorkbenchState, adapter: MockOrbitInterfaceAdapter) -> str:
    if state.mode == "approvals":
        approvals = adapter.list_open_approvals()
        if not approvals:
            return "Approval Queue\n\nNo pending approvals."
        current = approvals[min(state.selected_approval, len(approvals) - 1)]
        lines = [
            "Approval Queue",
            f"tool={current.tool_name}",
            f"session={current.session_id}",
            f"status={current.status} · side_effect_class={current.side_effect_class}",
            "",
            current.summary,
            "",
            f"payload={current.payload}",
        ]
        return "\n".join(lines)

    sessions = adapter.list_sessions()
    if not sessions:
        return "No sessions available."
    current = sessions[min(state.selected_session, len(sessions) - 1)]
    tab = SESSION_TABS[state.tab_index]
    lines = [
        f"Session Workbench · tab={tab}",
        f"session={current.session_id}",
        f"conversation={current.conversation_id}",
        f"status={current.status} · backend={current.backend_name} · model={current.model}",
        "",
    ]
    if tab == "events":
        for event in adapter.list_events(current.session_id):
            lines.append(f"{event.event_type}: {event.payload}")
    elif tab == "tool_calls":
        for call in adapter.list_tool_calls(current.session_id):
            lines.append(f"{call.tool_name}: {call.status} · {call.summary}")
    elif tab == "artifacts":
        for artifact in adapter.list_artifacts(current.session_id):
            lines.append(f"{artifact.artifact_type}: {artifact.content}")
    else:
        for message in adapter.list_messages(current.session_id):
            label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
            lines.append(f"{label}: {message.content}")
    return "\n".join(lines)


def _status_text(state: WorkbenchState, adapter: MockOrbitInterfaceAdapter) -> str:
    status = adapter.get_workbench_status()
    lines = [
        "Status",
        f"stage={status['implementation_stage']}",
        f"runtime={status['runtime_integration']}",
        f"mode={state.mode}",
        f"tab={SESSION_TABS[state.tab_index] if state.mode == 'sessions' else 'approval_queue'}",
        "",
        "Keys",
        "j/k or arrows: move",
        "t/tab: next tab",
        "a: approvals",
        "b: back",
        "?: help",
        "q or Ctrl-C: quit",
    ]
    if state.show_help:
        lines.extend([
            "",
            "Help",
            "This is the prompt_toolkit-based full-screen mock workbench.",
            "It is still runtime-disconnected and driven by deterministic mock data.",
        ])
    return "\n".join(lines)


def run_workbench() -> None:
    adapter = MockOrbitInterfaceAdapter()
    state = WorkbenchState()

    session_control = FormattedTextControl(lambda: _session_list_text(state, adapter))
    main_control = FormattedTextControl(lambda: _main_text(state, adapter))
    status_control = FormattedTextControl(lambda: _status_text(state, adapter))

    root = HSplit([
        Window(height=1, content=FormattedTextControl(lambda: "ORBIT Workbench · prompt_toolkit full-screen mock")),
        VSplit([
            Frame(Window(content=session_control, wrap_lines=False), title="Navigation"),
            Frame(Window(content=main_control, wrap_lines=True), title="Main"),
            Frame(Window(content=status_control, wrap_lines=True), title="Status"),
        ]),
    ])

    kb = KeyBindings()

    @kb.add("q")
    @kb.add("c-c")
    def _quit(event) -> None:
        event.app.exit()

    @kb.add("?")
    def _help(event) -> None:
        state.show_help = not state.show_help
        event.app.invalidate()

    @kb.add("j")
    @kb.add("down")
    def _down(event) -> None:
        if state.mode == "approvals":
            approvals = adapter.list_open_approvals()
            if approvals:
                state.selected_approval = min(len(approvals) - 1, state.selected_approval + 1)
        else:
            sessions = adapter.list_sessions()
            if sessions:
                state.selected_session = min(len(sessions) - 1, state.selected_session + 1)
        event.app.invalidate()

    @kb.add("k")
    @kb.add("up")
    def _up(event) -> None:
        if state.mode == "approvals":
            state.selected_approval = max(0, state.selected_approval - 1)
        else:
            state.selected_session = max(0, state.selected_session - 1)
        event.app.invalidate()

    @kb.add("t")
    @kb.add("tab")
    def _tab(event) -> None:
        if state.mode == "sessions":
            state.tab_index = (state.tab_index + 1) % len(SESSION_TABS)
            event.app.invalidate()

    @kb.add("a")
    def _approvals(event) -> None:
        state.mode = "approvals"
        event.app.invalidate()

    @kb.add("b")
    def _back(event) -> None:
        state.mode = "sessions"
        event.app.invalidate()

    app = Application(layout=Layout(root), key_bindings=kb, full_screen=True)
    app.run()
