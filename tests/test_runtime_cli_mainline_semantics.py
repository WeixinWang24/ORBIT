from __future__ import annotations

from orbit.interfaces.chat_mock_adapter import MockOrbitChatAdapter
from orbit.interfaces.input import ParsedKey
from orbit.interfaces.pty_runtime_router import route_slash_command, submit_composer
from orbit.interfaces.runtime_cli_handlers import (
    handle_approvals_key,
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


def test_runtime_cli_mainline_semantics_roundtrip() -> None:
    """Protect the current runtime-first PTY CLI semantic spine.

    This test intentionally covers the high-value interaction path that the new
    CLI UI is converging around:
    - slash routing into workbench surfaces
    - sessions <-> approvals route hops
    - inspect tab cycling
    - return-to-chat transitions
    - [INPUT] vs [NAV] render markers

    It is meant as a regression guard while the new CLI surface replaces older
    legacy/test entrypoints.
    """

    adapter = MockOrbitChatAdapter()
    state = RuntimeCliState()

    state.composer_text = "/sessions"
    submit_composer(state, adapter)
    assert state.mode == SESSIONS_MODE

    handle_sessions_key(state, adapter, ParsedKey(name="a", sequence="a"))
    assert state.mode == APPROVALS_MODE

    handle_approvals_key(state, adapter, ParsedKey(name="s", sequence="s"))
    assert state.mode == SESSIONS_MODE

    handle_sessions_key(state, adapter, ParsedKey(name="enter", sequence="\r"))
    assert state.mode == CHAT_MODE
    assert state.banner.startswith("Attached to ")

    state.composer_text = "/events"
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

    route_slash_command(state, adapter, "/pending")
    assert state.mode == CHAT_MODE

    route_slash_command(state, adapter, "/approve test-note")
    assert state.mode == CHAT_MODE

    chat_frame = frame_lines(RuntimeCliState(mode=CHAT_MODE), adapter)
    assert any("[INPUT]" in line for line in chat_frame)

    nav_frame = frame_lines(RuntimeCliState(mode=SESSIONS_MODE), adapter)
    assert any("[NAV]" in line for line in nav_frame)
