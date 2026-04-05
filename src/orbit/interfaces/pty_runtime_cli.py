"""Runtime-first raw PTY CLI that uses `pty_workbench.py` as the interaction/visual reference.

Design rule:
- functionality reference: runtime-first raw runtime workbench / chat-first shell
- interaction + display reference: `pty_workbench.py`
"""

from __future__ import annotations

import os
import threading
import time
from pathlib import Path
from datetime import datetime

from .adapter_protocol import RuntimeCliAdapter
from .runtime_adapter import RuntimeAdapterConfig, SessionManagerRuntimeAdapter
from . import termio as T
from .input import ControlToken, ParsedFocus, ParsedKey, ParsedMouse, SequenceToken, TextToken, parse_sequence, read_chunk, tokenize_input_chunk
from .pty_debug import debug_log
from .pty_primitives import ScreenBuffer, alt_screen, bracketed_paste, focus_events, mouse_tracking, raw_mode, terminal_size
from .runtime_cli_handlers import handle_approvals_key, handle_chat_key, handle_info_panel_key, handle_inspect_key, handle_sessions_key
from .runtime_cli_render import FrameRender, frame_lines
from .runtime_cli_state import APPROVALS_MODE, CHAT_MODE, HELP_MODE, INSPECT_MODE, RuntimeCliState, SESSIONS_MODE, STATUS_MODE

PTY_INPUT_DEBUG_ENV = "ORBIT_PTY_INPUT_DEBUG"


def _pty_input_debug_path() -> Path | None:
    raw = os.environ.get(PTY_INPUT_DEBUG_ENV, "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return None
    log_dir = Path("/Volumes/2TB/MAS/openclaw-core/ORBIT/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir / f"pty-input-{datetime.now().strftime('%Y%m%d-%H%M%S')}.log"


def _append_pty_input_debug(path: Path | None, *, stage: str, state: RuntimeCliState, event: object) -> None:
    if path is None:
        return
    try:
        line = (
            f"[{datetime.now().isoformat()}] stage={stage} mode={state.mode} "
            f"selected_session={state.selected_session} event={event!r}\n"
        )
        with path.open("a", encoding="utf-8") as f:
            f.write(line)
    except Exception:
        pass


def _build_default_adapter() -> RuntimeCliAdapter:
    adapter = SessionManagerRuntimeAdapter.build(RuntimeAdapterConfig())
    debug_log("pty_runtime_cli:using_session_manager_runtime_adapter")
    return adapter


def _start_background_submit(state: RuntimeCliState, adapter: RuntimeCliAdapter) -> None:
    session_id = state.pending_submit_session_id
    text = state.pending_submit_text
    approval_resolution = getattr(state, "_pending_approval_resolution", None)
    if not session_id or (not text and approval_resolution is None):
        state.runtime_busy = False
        return

    def _worker() -> None:
        def _handle_partial_text(partial: str) -> None:
            state.assistant_inflight_text = partial
            state.assistant_inflight_dirty = True

        try:
            state.assistant_inflight_text = ""
            state.assistant_inflight_dirty = True
            if approval_resolution is not None:
                decision = approval_resolution.get("decision")
                reauth_tool_name = approval_resolution.get("reauth_tool_name")
                reauth_note = approval_resolution.get("reauth_note")
                if decision == "approve" and isinstance(reauth_tool_name, str) and reauth_tool_name:
                    adapter.reauthorize_tool_path(
                        session_id,
                        reauth_tool_name,
                        note=reauth_note,
                        source="chat_approval_picker",
                    )
                adapter.resolve_pending_approval(session_id, decision, reauth_note if decision == "reject" else None)
                state.completed_submit_banner = "Approval resolved"
                state.completed_submit_error = None
            else:
                adapter.send_user_message(
                    session_id,
                    text,
                    on_assistant_partial_text=_handle_partial_text,
                )
                state.completed_submit_banner = f"Submitted to {session_id}"
                state.completed_submit_error = None
        except Exception as exc:
            try:
                adapter.append_system_message(
                    session_id,
                    f"submit failed: {exc!r}",
                    kind="submit_error",
                )
            except Exception:
                pass
            state.completed_submit_banner = "Submit failed"
            state.completed_submit_error = repr(exc)
        finally:
            state.runtime_busy = False
            state.pending_submit_text = ""
            state.pending_submit_session_id = None
            state.assistant_inflight_text = None
            state.assistant_inflight_dirty = True
            state.approval_action_pending = False
            state.approval_action_label = None
            if hasattr(state, "_pending_approval_resolution"):
                delattr(state, "_pending_approval_resolution")
            state._submit_thread_started_at = None

    state._submit_thread_started_at = time.time()
    thread = threading.Thread(target=_worker, name="orbit-pty-submit", daemon=True)
    thread.start()


def _position_cursor_for_composer(rendered: FrameRender) -> None:
    try:
        import sys
        sys.stdout.write(T.cursor_position(rendered.composer_row, rendered.composer_col))
        sys.stdout.flush()
    except Exception:
        pass


def browse_runtime_cli(adapter: RuntimeCliAdapter | None = None, *, chat_history_limit: int | None = None) -> None:
    debug_log("pty_runtime_cli:start")
    runtime_adapter = adapter
    state = RuntimeCliState()
    env_limit = os.environ.get("ORBIT_CLI_CHAT_HISTORY_LIMIT", "").strip()
    resolved_limit = chat_history_limit
    if resolved_limit is None and env_limit:
        try:
            resolved_limit = max(1, int(env_limit))
        except ValueError:
            resolved_limit = None
    if resolved_limit is not None:
        state.chat_history_limit = resolved_limit
    state.banner = "Starting runtime adapter..."

    def _startup_worker() -> None:
        nonlocal runtime_adapter
        try:
            built = runtime_adapter or _build_default_adapter()
            runtime_adapter = built
            sessions = built.list_sessions()
            if sessions:
                initial_session = sessions[0]
                state.active_session_id = initial_session.session_id
                state.selected_session = 0
                state.banner = f"Attached to latest session {initial_session.session_id}"
            else:
                initial_session = built.create_session()
                state.active_session_id = initial_session.session_id
                state.selected_session = 0
                state.banner = f"Created new session {initial_session.session_id}"
            state.startup_error = None
        except Exception as exc:
            state.startup_error = repr(exc)
            state.banner = "Startup failed"
            debug_log(f"pty_runtime_cli:startup_failed={exc!r}")
        finally:
            state.startup_loading = False

    threading.Thread(target=_startup_worker, name="orbit-pty-startup", daemon=True).start()
    screen = ScreenBuffer()
    in_paste = False
    pty_input_debug_path = _pty_input_debug_path()
    if pty_input_debug_path is not None:
        debug_log(f"pty_runtime_cli:input_debug_log={pty_input_debug_path}")

    last_busy_state = False
    with raw_mode(), alt_screen(), bracketed_paste(), focus_events():
        while True:
            if state.runtime_busy and state._submit_thread_started_at is None and runtime_adapter is not None:
                _start_background_submit(state, runtime_adapter)

            if state.runtime_busy != last_busy_state:
                # Structural transition (busy on/off): full repaint is correct here
                # because the header gains/loses the busy banner line, changing the
                # overall frame layout.
                screen.invalidate()
                last_busy_state = state.runtime_busy

            # Streaming delta: consume the dirty flag but do NOT invalidate.
            # The diff engine handles incremental streaming updates line-by-line
            # without needing ERASE_SCREEN.  Setting has_streaming_update drives
            # the render-loop timeout below so the next render fires immediately.
            has_streaming_update = state.assistant_inflight_dirty
            if state.assistant_inflight_dirty:
                state.assistant_inflight_dirty = False

            if not state.runtime_busy and state.completed_submit_banner is not None:
                state.banner = state.completed_submit_banner
                state.completed_submit_banner = None
                screen.invalidate()

            width, height = terminal_size()
            rendered = frame_lines(state, runtime_adapter)
            screen.render(rendered.lines, width, height, force_full_repaint=False)
            if state.mode == CHAT_MODE:
                _position_cursor_for_composer(rendered)

            # Three-speed render cycle:
            #   0 ms  — streaming token just arrived: skip the wait, loop back
            #           immediately so the next diff fires without delay.
            #  16 ms  — busy but no new token yet: tight poll (~60 fps) so we
            #           catch the next token within one frame even if the dirty
            #           flag is set just after we cleared it above.
            #  50 ms  — idle: normal cadence, low CPU.
            if has_streaming_update:
                read_timeout_ms = 0.0
            elif state.runtime_busy:
                read_timeout_ms = 16.0
            else:
                read_timeout_ms = 50.0
            chunk = read_chunk(timeout_ms=read_timeout_ms)
            _append_pty_input_debug(pty_input_debug_path, stage="raw", state=state, event=chunk)
            if not chunk:
                debug_log("pty_runtime_cli:raw=<empty>")
                continue
            debug_log(f"pty_runtime_cli:raw={chunk!r}")

            if runtime_adapter is None or state.startup_loading:
                continue

            tokens = tokenize_input_chunk(chunk)
            for token in tokens:
                _append_pty_input_debug(pty_input_debug_path, stage="token", state=state, event=token)

                if isinstance(token, TextToken):
                    if in_paste:
                        continue
                    if state.mode == CHAT_MODE:
                        state.composer.insert_text(token.value)
                        screen.invalidate()
                        continue
                    for ch in token.value:
                        event = ParsedKey(name=ch, sequence=ch)
                        if state.mode == SESSIONS_MODE:
                            handle_sessions_key(state, runtime_adapter, event)
                        elif state.mode == APPROVALS_MODE:
                            handle_approvals_key(state, runtime_adapter, event)
                        elif state.mode == INSPECT_MODE:
                            handle_inspect_key(state, runtime_adapter, event)
                        elif state.mode in {HELP_MODE, STATUS_MODE}:
                            handle_info_panel_key(state, event)
                        screen.invalidate()
                    continue

                if isinstance(token, ControlToken):
                    raw = token.value
                else:
                    raw = token.value
                if raw == T.PASTE_START:
                    in_paste = True
                    continue
                if raw == T.PASTE_END:
                    in_paste = False
                    continue
                if in_paste:
                    continue

                event = parse_sequence(raw)
                _append_pty_input_debug(pty_input_debug_path, stage="parsed", state=state, event=event)
                debug_log(f"pty_runtime_cli:mode={state.mode} event={event!r}")
                if event is None:
                    continue

                if isinstance(event, ParsedFocus):
                    if not event.focused:
                        screen.invalidate()
                        continue
                    screen.invalidate()
                    state.assistant_inflight_dirty = True
                    continue
                if isinstance(event, ParsedMouse):
                    continue
                if not isinstance(event, ParsedKey):
                    continue

                name = event.name
                ctrl = event.ctrl
                if name == "escape":
                    debug_log(f"pty_runtime_cli:swallow_escape mode={state.mode}")
                    continue
                if ctrl and name == "c":
                    try:
                        screen.invalidate()
                        screen.render([T.DIM + "Exited ORBIT runtime CLI." + T.RESET], width, 1)
                    finally:
                        return

                invalidate = False
                if state.mode == CHAT_MODE:
                    invalidate = handle_chat_key(state, runtime_adapter, event)
                    if pty_input_debug_path is not None:
                        _append_pty_input_debug(
                            pty_input_debug_path,
                            stage="post_chat_key",
                            state=state,
                            event={
                                "event_name": event.name,
                                "composer_text": state.composer.text,
                                "banner": state.banner,
                            },
                        )
                elif state.mode == SESSIONS_MODE:
                    handle_sessions_key(state, runtime_adapter, event)
                elif state.mode == APPROVALS_MODE:
                    handle_approvals_key(state, runtime_adapter, event)
                elif state.mode == INSPECT_MODE:
                    handle_inspect_key(state, runtime_adapter, event)
                elif state.mode in {HELP_MODE, STATUS_MODE}:
                    handle_info_panel_key(state, event)

                if invalidate:
                    screen.invalidate()
