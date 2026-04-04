"""Prompt-toolkit based chat-first mock workbench for ORBIT."""

from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Frame

from .chat_mock_adapter import MockOrbitChatAdapter

SESSION_TABS = ["transcript", "events", "tool_calls", "artifacts"]


@dataclass
class WorkbenchState:
    mode: str = "chat"
    selected_session: int = 0
    selected_approval: int = 0
    tab_index: int = 0
    show_help: bool = False


def _current_session_id(state: WorkbenchState, adapter: MockOrbitChatAdapter) -> str:
    sessions = adapter.list_sessions()
    if not sessions:
        session = adapter.create_session()
        return session.session_id
    state.selected_session = min(state.selected_session, len(sessions) - 1)
    return sessions[state.selected_session].session_id


def _navigation_text(state: WorkbenchState, adapter: MockOrbitChatAdapter) -> str:
    sessions = adapter.list_sessions()
    lines = ["Sessions"]
    for i, session in enumerate(sessions):
        prefix = ">" if i == state.selected_session and state.mode in {"chat", "inspect"} else " "
        lines.append(f"{prefix} {session.session_id}")
        lines.append(f"  {session.status} · {session.backend_name} · {session.model}")
    return "\n".join(lines)


def _main_text(state: WorkbenchState, adapter: MockOrbitChatAdapter) -> str:
    if state.mode == "approvals":
        approvals = adapter.list_open_approvals()
        if not approvals:
            return "Approval Queue\n\nNo pending approvals."
        current = approvals[min(state.selected_approval, len(approvals) - 1)]
        return "\n".join([
            "Approval Queue",
            f"tool={current.tool_name}",
            f"session={current.session_id}",
            f"status={current.status} · side_effect_class={current.side_effect_class}",
            "",
            current.summary,
            "",
            f"payload={current.payload}",
        ])

    session_id = _current_session_id(state, adapter)
    sessions = adapter.list_sessions()
    session = next(s for s in sessions if s.session_id == session_id)
    if state.mode == "inspect":
        tab = SESSION_TABS[state.tab_index]
        lines = [
            f"Inspect · tab={tab}",
            f"session={session.session_id}",
            f"conversation={session.conversation_id}",
            "",
        ]
        if tab == "events":
            for event in adapter.list_events(session_id):
                lines.append(f"{event.event_type}: {event.payload}")
        elif tab == "tool_calls":
            for call in adapter.list_tool_calls(session_id):
                lines.append(f"{call.tool_name}: {call.status} · {call.summary}")
        elif tab == "artifacts":
            for artifact in adapter.list_artifacts(session_id):
                lines.append(f"{artifact.artifact_type}: {artifact.content}")
        else:
            for message in adapter.list_messages(session_id):
                label = message.role if not message.message_kind else f"{message.role}/{message.message_kind}"
                lines.append(f"{label}: {message.content}")
        return "\n".join(lines)

    transcript_lines = [
        f"ORBIT Chat Session",
        f"session={session.session_id}",
        f"backend={session.backend_name} · model={session.model}",
        "",
    ]
    for message in adapter.list_messages(session_id):
        label = message.role.upper() if not message.message_kind else f"{message.role.upper()} [{message.message_kind}]"
        transcript_lines.append(f"{label}")
        transcript_lines.append(message.content)
        transcript_lines.append("")
    if len(transcript_lines) == 4:
        transcript_lines.append("No messages yet. Type below and press Enter.")
    return "\n".join(transcript_lines)


def _status_text(state: WorkbenchState, adapter: MockOrbitChatAdapter) -> str:
    status = adapter.get_workbench_status()
    session_id = _current_session_id(state, adapter)
    session = adapter.get_session(session_id)
    lines = [
        "Status",
        f"stage={status['implementation_stage']}",
        f"runtime={status['runtime_integration']}",
        f"mode={state.mode}",
        f"session={session_id}",
        f"messages={session.message_count if session else 0}",
        "",
        "Keys",
        "j/k or arrows: move sessions/approvals",
        "enter: send message (input focused)",
        "i: inspect mode",
        "c: chat mode",
        "t/tab: next inspect tab",
        "a: approvals",
        "b: back",
        "n: new session",
        "?: help",
        "q or Ctrl-C: quit",
    ]
    if state.show_help:
        lines.extend([
            "",
            "Help",
            "This is the chat-first prompt_toolkit ORBIT workbench.",
            "Current runtime loop is still dummy-backed, but the UI shape is now usage-first.",
        ])
    return "\n".join(lines)


def run_workbench() -> None:
    adapter = MockOrbitChatAdapter()
    state = WorkbenchState()
    if not adapter.list_sessions():
        adapter.create_session()

    input_buffer = Buffer()

    navigation_control = FormattedTextControl(lambda: _navigation_text(state, adapter))
    main_control = FormattedTextControl(lambda: _main_text(state, adapter))
    status_control = FormattedTextControl(lambda: _status_text(state, adapter))

    root = HSplit([
        Window(height=1, content=FormattedTextControl(lambda: "ORBIT Workbench · chat-first prompt_toolkit mock")),
        VSplit([
            Frame(Window(content=navigation_control, wrap_lines=False), title="Navigation"),
            Frame(Window(content=main_control, wrap_lines=True), title="Conversation / Inspect"),
            Frame(Window(content=status_control, wrap_lines=True), title="Status"),
        ]),
        Frame(
            Window(content=BufferControl(buffer=input_buffer), height=Dimension(preferred=3)),
            title="Input (Enter to send in chat mode)",
        ),
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
        if state.mode == "inspect":
            state.tab_index = (state.tab_index + 1) % len(SESSION_TABS)
            event.app.invalidate()

    @kb.add("a")
    def _approvals(event) -> None:
        state.mode = "approvals"
        event.app.invalidate()

    @kb.add("b")
    def _back(event) -> None:
        state.mode = "chat"
        event.app.invalidate()

    @kb.add("i")
    def _inspect(event) -> None:
        state.mode = "inspect"
        event.app.invalidate()

    @kb.add("c")
    def _chat(event) -> None:
        state.mode = "chat"
        event.app.invalidate()

    @kb.add("n")
    def _new_session(event) -> None:
        adapter.create_session()
        state.selected_session = 0
        state.mode = "chat"
        event.app.invalidate()

    @kb.add("enter")
    def _send(event) -> None:
        if state.mode != "chat":
            return
        text = input_buffer.text.strip()
        if not text:
            return
        session_id = _current_session_id(state, adapter)
        adapter.send_user_message(session_id, text)
        input_buffer.text = ""
        event.app.invalidate()

    app = Application(layout=Layout(root), key_bindings=kb, full_screen=True)
    app.run()
