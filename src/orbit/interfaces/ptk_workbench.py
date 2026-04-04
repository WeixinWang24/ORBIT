"""Prompt-toolkit based runtime-first mock workbench for ORBIT."""

from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.application import Application
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.layout.containers import ConditionalContainer
from prompt_toolkit.widgets import Frame

from .chat_mock_adapter import MockOrbitChatAdapter

SESSION_TABS = ["transcript", "events", "tool_calls", "artifacts"]


@dataclass
class WorkbenchState:
    mode: str = "chat"
    input_mode: bool = True
    selected_session: int = 0
    selected_approval: int = 0
    tab_index: int = 0
    banner: str = "Agent Runtime mode · slash commands available via /help"


def _current_session_id(state: WorkbenchState, adapter: MockOrbitChatAdapter) -> str:
    sessions = adapter.list_sessions()
    if not sessions:
        session = adapter.create_session()
        return session.session_id
    state.selected_session = min(state.selected_session, len(sessions) - 1)
    return sessions[state.selected_session].session_id


def _module_text(state: WorkbenchState, adapter: MockOrbitChatAdapter, session_id: str) -> str:
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

    tab = SESSION_TABS[state.tab_index]
    lines = [f"Inspector · tab={tab}", ""]
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


def _main_text(state: WorkbenchState, adapter: MockOrbitChatAdapter) -> str:
    session_id = _current_session_id(state, adapter)
    sessions = adapter.list_sessions()
    session = next(s for s in sessions if s.session_id == session_id)

    if state.mode != "chat":
        return _module_text(state, adapter, session_id)

    transcript_lines = [
        "ORBIT Agent Runtime Chat",
        state.banner,
        f"session={session.session_id}",
        f"backend={session.backend_name} · model={session.model}",
        "",
    ]
    for message in adapter.list_messages(session_id):
        label = message.role.upper() if not message.message_kind else f"{message.role.upper()} [{message.message_kind}]"
        transcript_lines.append(label)
        transcript_lines.append(message.content)
        transcript_lines.append("")
    if len(transcript_lines) == 5:
        transcript_lines.append("No messages yet. Type below and press Enter.")
    return "\n".join(transcript_lines)


def _header_text(state: WorkbenchState, adapter: MockOrbitChatAdapter) -> str:
    session_id = _current_session_id(state, adapter)
    session = adapter.get_session(session_id)
    if state.mode == "chat":
        return f"ORBIT · Agent Runtime Chat · {session_id} · {session.backend_name}/{session.model}"
    if state.mode == "approvals":
        return f"ORBIT · Approvals · {session_id}"
    return f"ORBIT · Inspector · {SESSION_TABS[state.tab_index]} · {session_id}"


def _footer_text(state: WorkbenchState, adapter: MockOrbitChatAdapter) -> str:
    if state.input_mode:
        return "INSERT · Enter sends · /command routes modules · Esc -> nav · /help for commands"
    return "NAV · q quit · e edit · j/k move sessions or approvals · t switch inspector tab"


def run_workbench() -> None:
    adapter = MockOrbitChatAdapter()
    state = WorkbenchState()
    if not adapter.list_sessions():
        adapter.create_session()

    input_buffer = Buffer()

    main_control = FormattedTextControl(lambda: _main_text(state, adapter))
    input_window = Window(content=BufferControl(buffer=input_buffer, focus_on_click=True), height=Dimension(preferred=3))

    def in_nav_mode() -> bool:
        return not state.input_mode

    root = HSplit([
        Window(height=1, content=FormattedTextControl(lambda: _header_text(state, adapter))),
        Frame(Window(content=main_control, wrap_lines=True), title=lambda: "Agent Runtime Chat" if state.mode == 'chat' else ("Approvals" if state.mode == 'approvals' else f"Inspector · {SESSION_TABS[state.tab_index]}")),
        Frame(
            input_window,
            title=lambda: "Input [INSERT]" if state.input_mode else "Input [NAV]",
        ),
        Window(height=1, content=FormattedTextControl(lambda: _footer_text(state, adapter))),
        ConditionalContainer(
            content=Window(height=1, content=FormattedTextControl(lambda: f"Slash commands: {adapter.slash_help_text()}" if state.mode != 'chat' else "")),
            filter=Condition(lambda: state.mode != 'chat'),
        ),
    ])

    kb = KeyBindings()

    @kb.add("c-c")
    def _quit_force(event) -> None:
        event.app.exit()

    @kb.add("escape")
    def _escape_to_nav(event) -> None:
        state.input_mode = False
        event.app.layout.focus(root)
        event.app.invalidate()

    @kb.add("e", filter=Condition(in_nav_mode))
    def _edit_mode(event) -> None:
        state.input_mode = True
        event.app.layout.focus(input_window)
        event.app.invalidate()

    @kb.add("q", filter=Condition(in_nav_mode))
    def _quit(event) -> None:
        event.app.exit()

    @kb.add("j", filter=Condition(in_nav_mode))
    @kb.add("down", filter=Condition(in_nav_mode))
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

    @kb.add("k", filter=Condition(in_nav_mode))
    @kb.add("up", filter=Condition(in_nav_mode))
    def _up(event) -> None:
        if state.mode == "approvals":
            state.selected_approval = max(0, state.selected_approval - 1)
        else:
            state.selected_session = max(0, state.selected_session - 1)
        event.app.invalidate()

    @kb.add("t", filter=Condition(in_nav_mode))
    @kb.add("tab", filter=Condition(in_nav_mode))
    def _tab(event) -> None:
        if state.mode not in {"chat", "approvals"}:
            state.tab_index = (state.tab_index + 1) % len(SESSION_TABS)
            event.app.invalidate()

    def _route_slash_command(text: str) -> None:
        session_id = _current_session_id(state, adapter)
        parts = text.strip().split(maxsplit=1)
        command = parts[0]
        arg = parts[1].strip() if len(parts) > 1 else ""

        if command == "/help":
            adapter.append_system_message(session_id, adapter.slash_help_text(), kind="slash_help")
            state.mode = "chat"
            state.banner = "Slash help shown in transcript"
            return
        if command == "/new":
            adapter.create_session()
            state.selected_session = 0
            state.mode = "chat"
            state.banner = "Created new session"
            return
        if command == "/sessions":
            sessions = adapter.list_sessions()
            listing = "Stored sessions:\n" + "\n".join(f"- {s.session_id} ({s.status})" for s in sessions)
            adapter.append_system_message(session_id, listing, kind="sessions_list")
            state.mode = "chat"
            state.banner = "Session list inserted into transcript"
            return
        if command == "/attach":
            target = adapter.attach_session(arg)
            if target is None:
                adapter.append_system_message(session_id, f"Session not found: {arg}", kind="attach_error")
            else:
                sessions = adapter.list_sessions()
                state.selected_session = next(i for i, s in enumerate(sessions) if s.session_id == target.session_id)
                state.mode = "chat"
                state.banner = f"Attached to {target.session_id}"
            return
        if command == "/inspect":
            state.mode = "inspect"
            state.tab_index = 0
            return
        if command == "/chat":
            state.mode = "chat"
            state.banner = "Returned to agent runtime chat"
            return
        if command == "/approvals":
            state.mode = "approvals"
            return
        if command == "/events":
            state.mode = "inspect"
            state.tab_index = 1
            return
        if command == "/tools":
            state.mode = "inspect"
            state.tab_index = 2
            return
        if command == "/artifacts":
            state.mode = "inspect"
            state.tab_index = 3
            return
        if command == "/status":
            status_dump = f"session={session_id}\nmode={state.mode}\ninput_mode={'insert' if state.input_mode else 'nav'}\n{adapter.slash_help_text()}"
            adapter.append_system_message(session_id, status_dump, kind="status_dump")
            state.mode = "chat"
            state.banner = "Status dumped into transcript"
            return
        adapter.append_system_message(session_id, f"Unknown slash command: {text}", kind="slash_error")
        state.mode = "chat"
        state.banner = "Unknown slash command"

    @kb.add("enter")
    def _submit(event) -> None:
        if not state.input_mode:
            return
        text = input_buffer.text.strip()
        if not text:
            return
        if text.startswith("/"):
            _route_slash_command(text)
        else:
            session_id = _current_session_id(state, adapter)
            adapter.send_user_message(session_id, text)
            state.mode = "chat"
            state.banner = "Agent Runtime mode · slash commands available via /help"
        input_buffer.text = ""
        event.app.invalidate()

    app = Application(layout=Layout(root, focused_element=input_window), key_bindings=kb, full_screen=True)
    app.run()
