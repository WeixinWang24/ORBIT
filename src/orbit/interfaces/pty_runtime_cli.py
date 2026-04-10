"""Runtime-first raw PTY CLI that uses `pty_workbench.py` as the interaction/visual reference.

Design rule:
- functionality reference: runtime-first raw runtime workbench / chat-first shell
- interaction + display reference: `pty_workbench.py`
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path
from datetime import datetime

_MODULE_IMPORT_TIMINGS: dict[str, float] = {}
_t = time.perf_counter()
from .adapter_protocol import RuntimeCliAdapter
_MODULE_IMPORT_TIMINGS['adapter_protocol_ms'] = round((time.perf_counter() - _t) * 1000, 2)
from . import termio as T
_MODULE_IMPORT_TIMINGS['runtime_adapter_ms'] = 'deferred'
_t = time.perf_counter()
_MODULE_IMPORT_TIMINGS['termio_ms'] = round((time.perf_counter() - _t) * 1000, 2)
_t = time.perf_counter()
from .input import ControlToken, ParsedFocus, ParsedKey, ParsedMouse, SequenceToken, TextToken, parse_sequence, read_chunk, tokenize_input_chunk
_MODULE_IMPORT_TIMINGS['input_ms'] = round((time.perf_counter() - _t) * 1000, 2)
_t = time.perf_counter()
from .pty_debug import debug_log
_MODULE_IMPORT_TIMINGS['pty_debug_ms'] = round((time.perf_counter() - _t) * 1000, 2)
_t = time.perf_counter()
from .pty_primitives import ScreenBuffer, alt_screen, bracketed_paste, focus_events, mouse_tracking, raw_mode, terminal_size
_MODULE_IMPORT_TIMINGS['pty_primitives_ms'] = round((time.perf_counter() - _t) * 1000, 2)
_t = time.perf_counter()
from .runtime_cli_handlers import handle_approvals_key, handle_chat_key, handle_info_panel_key, handle_inspect_key, handle_sessions_key
_MODULE_IMPORT_TIMINGS['runtime_cli_handlers_ms'] = round((time.perf_counter() - _t) * 1000, 2)
_t = time.perf_counter()
from .runtime_cli_render import FrameRender, frame_lines
_MODULE_IMPORT_TIMINGS['runtime_cli_render_ms'] = round((time.perf_counter() - _t) * 1000, 2)
_t = time.perf_counter()
from .runtime_cli_state import APPROVALS_MODE, CHAT_MODE, HELP_MODE, INSPECT_MODE, RuntimeCliState, SESSIONS_MODE, STATUS_MODE
_MODULE_IMPORT_TIMINGS['runtime_cli_state_ms'] = round((time.perf_counter() - _t) * 1000, 2)
PTY_IMPORT_PROFILE_TIMINGS = dict(_MODULE_IMPORT_TIMINGS)

PTY_INPUT_DEBUG_ENV = "ORBIT_PTY_INPUT_DEBUG"


def _pty_input_debug_path() -> Path | None:
    raw = os.environ.get(PTY_INPUT_DEBUG_ENV, "").strip().lower()
    if raw not in {"1", "true", "yes", "on"}:
        return None
    log_dir = Path(os.environ.get("ORBIT_LOG_DIR", str(Path(__file__).resolve().parents[3] / "logs")))
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


DEFERRED_CAPABILITIES = ['git', 'bash', 'process', 'obsidian_tools']


def _build_default_adapter(*, runtime_mode: str = "dev") -> RuntimeCliAdapter:
    adapter_import_started_at = time.perf_counter()
    from .runtime_adapter import RUNTIME_ADAPTER_IMPORT_PROFILE_TIMINGS, SESSION_MANAGER_IMPORT_PROFILE_TIMINGS, RuntimeAdapterConfig, SessionManagerRuntimeAdapter
    deferred_import_ms = round((time.perf_counter() - adapter_import_started_at) * 1000, 2)
    debug_log(f"pty_runtime_cli:runtime_adapter_deferred_import_ms={deferred_import_ms}")
    adapter_build_started_at = time.perf_counter()
    # Minimal baseline: only filesystem is synchronous.
    # git/bash/process/obsidian are activated in background after session-ready.
    adapter = SessionManagerRuntimeAdapter.build(
        RuntimeAdapterConfig.mcp_default(runtime_mode=runtime_mode)
    )
    debug_log(f"pty_runtime_cli:session_manager_runtime_adapter_build_ms={round((time.perf_counter() - adapter_build_started_at) * 1000, 2)}")
    if hasattr(adapter, 'startup_metrics') and isinstance(adapter.startup_metrics, dict):
        adapter.startup_metrics['runtime_adapter_deferred_import_ms'] = deferred_import_ms
        adapter.startup_metrics['lazy_activation_baseline'] = ['filesystem']
        adapter.startup_metrics['lazy_activation_deferred'] = list(DEFERRED_CAPABILITIES)
        heavy_runtime_adapter_imports = {k: v for k, v in RUNTIME_ADAPTER_IMPORT_PROFILE_TIMINGS.items() if isinstance(v, (int, float)) and v >= 50}
        if heavy_runtime_adapter_imports:
            adapter.startup_metrics['runtime_adapter_import_profile_timings'] = heavy_runtime_adapter_imports
        heavy_session_manager_imports = {k: v for k, v in SESSION_MANAGER_IMPORT_PROFILE_TIMINGS.items() if isinstance(v, (int, float)) and v >= 50}
        if heavy_session_manager_imports:
            adapter.startup_metrics['session_manager_import_profile_timings'] = heavy_session_manager_imports
    debug_log("pty_runtime_cli:using_session_manager_runtime_adapter (lazy baseline)")
    return adapter


def _start_background_submit(state: RuntimeCliState, adapter: RuntimeCliAdapter) -> None:
    session_id = state.pending_submit_session_id
    text = state.pending_submit_text
    approval_resolution = getattr(state, "_pending_approval_resolution", None)
    if not session_id or (not text and approval_resolution is None):
        state.runtime_busy = False
        return

    submit_started_perf = time.perf_counter()
    try:
        debug_log(
            f"pty_runtime_cli:submit_thread_start session_id={session_id} text_len={len(text)} approval={approval_resolution is not None}"
        )
    except Exception:
        pass

    def _worker() -> None:
        stream_completed_perf: float | None = None

        def _handle_partial_text(partial: str) -> None:
            state.assistant_inflight_text = partial
            state.assistant_inflight_dirty = True

        def _handle_stream_completed() -> None:
            nonlocal stream_completed_perf
            # Called right after the SSE stream ends, before slow post-stream work
            # (normalize_events, memory capture). Clears the streaming banner
            # immediately so the UI does not appear stuck in streaming state.
            stream_completed_perf = time.perf_counter()
            try:
                debug_log(
                    f"pty_runtime_cli:stream_completed session_id={session_id} elapsed_ms={round((stream_completed_perf - submit_started_perf) * 1000, 2)}"
                )
            except Exception:
                pass
            state.assistant_inflight_text = None
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
                    on_stream_completed=_handle_stream_completed,
                )
                try:
                    returned_at = time.perf_counter()
                    debug_log(
                        "pty_runtime_cli:adapter_send_returned "
                        f"session_id={session_id} elapsed_ms={round((returned_at - submit_started_perf) * 1000, 2)} "
                        f"post_stream_ms={round((returned_at - stream_completed_perf) * 1000, 2) if stream_completed_perf is not None else 'n/a'}"
                    )
                except Exception:
                    pass
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
            busy_clear_at = time.perf_counter()
            try:
                debug_log(
                    "pty_runtime_cli:submit_thread_finalize "
                    f"session_id={session_id} total_ms={round((busy_clear_at - submit_started_perf) * 1000, 2)} "
                    f"post_stream_to_busy_clear_ms={round((busy_clear_at - stream_completed_perf) * 1000, 2) if stream_completed_perf is not None else 'n/a'}"
                )
            except Exception:
                pass
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


def browse_runtime_cli(adapter: RuntimeCliAdapter | None = None, *, runtime_mode: str = "dev", chat_history_limit: int | None = None, app_started_at: float | None = None, startup_metrics: dict | None = None) -> None:
    debug_log("pty_runtime_cli:start")
    runtime_adapter = adapter
    state = RuntimeCliState()
    if startup_metrics:
        state.startup_metrics.update(startup_metrics)
    heavy_pty_imports = {k: v for k, v in PTY_IMPORT_PROFILE_TIMINGS.items() if isinstance(v, (int, float)) and v >= 50}
    if heavy_pty_imports:
        state.startup_metrics['pty_import_profile_timings'] = heavy_pty_imports
    cli_started_at = time.perf_counter()
    if app_started_at is not None:
        state.startup_metrics['app_to_cli_entry_ms'] = round((cli_started_at - app_started_at) * 1000, 2)
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

    def _warmup_worker() -> None:
        nonlocal runtime_adapter
        if runtime_adapter is None:
            state.warmup_done = True
            state.bg_activation_done = True
            return
        try:
            state.warmup_started = True
            warmup_started_at = time.perf_counter()

            # Phase 1: legacy warmup (embedding prefetch etc.)
            if hasattr(runtime_adapter, 'warmup_post_composer_capabilities'):
                timings = runtime_adapter.warmup_post_composer_capabilities()
                state.startup_metrics.update(timings)

            # Phase 2: real background incremental activation of deferred capabilities
            # Map obsidian_tools -> obsidian for the composer capability name
            cap_map = {'obsidian_tools': 'obsidian'}
            deferred = [cap_map.get(c, c) for c in DEFERRED_CAPABILITIES]
            state.bg_capabilities_pending = list(deferred)
            if state.bg_capabilities_pending and not state.runtime_busy:
                state.banner = (
                    "Session ready · loading extended tools in background: "
                    + ", ".join(state.bg_capabilities_pending)
                )

            if hasattr(runtime_adapter, 'background_activate_capabilities'):
                def _on_activated(cap: str, elapsed: float) -> None:
                    if cap in state.bg_capabilities_pending:
                        state.bg_capabilities_pending.remove(cap)
                    state.bg_capabilities_activated.append(cap)
                    if not state.runtime_busy:
                        if state.bg_capabilities_pending:
                            state.banner = (
                                "Session ready · loading extended tools in background: "
                                + ", ".join(state.bg_capabilities_pending)
                            )
                        else:
                            state.banner = "Extended tools loaded"
                    debug_log(f"pty_runtime_cli:bg_activated {cap} ({elapsed:.1f}ms)")

                def _on_failed(cap: str, exc: Exception) -> None:
                    if cap in state.bg_capabilities_pending:
                        state.bg_capabilities_pending.remove(cap)
                    state.bg_capabilities_failed.append(cap)
                    if not state.runtime_busy:
                        if state.bg_capabilities_pending:
                            state.banner = (
                                "Session ready · loading extended tools in background: "
                                + ", ".join(state.bg_capabilities_pending)
                            )
                        else:
                            state.banner = "Extended tool loading finished with some failures"
                    debug_log(f"pty_runtime_cli:bg_failed {cap} ({exc!r})")

                bg_metrics = runtime_adapter.background_activate_capabilities(
                    deferred,
                    on_capability_activated=_on_activated,
                    on_capability_failed=_on_failed,
                )
                state.startup_metrics.update(bg_metrics)

            state.bg_activation_done = True
            state.startup_metrics['warmup_worker_total_ms'] = round((time.perf_counter() - warmup_started_at) * 1000, 2)
            state.warmup_done = True
            state.warmup_error = None
            if state.pending_warmup_submit and state.composer.text.strip() and state.active_session_id:
                # Only non-slash messages are queued here (slash commands now bypass
                # the warmup gate and execute immediately in handle_chat_key).
                queued_text = state.composer.text.strip()
                state.pending_warmup_submit = False
                state.composer.text = ""
                state.banner = f"Submitting {len(queued_text)} chars to active session..."
                state.pending_submit_session_id = state.active_session_id
                state.pending_submit_text = queued_text
                state.runtime_busy = True
                state.completed_submit_banner = None
                state.completed_submit_error = None
        except Exception as exc:
            state.warmup_error = repr(exc)
            state.warmup_done = True
            state.bg_activation_done = True
            state.pending_warmup_submit = False
            debug_log(f"pty_runtime_cli:warmup_failed={exc!r}")

    def _startup_worker() -> None:
        nonlocal runtime_adapter
        startup_started_at = time.perf_counter()
        try:
            built = runtime_adapter or _build_default_adapter(runtime_mode=runtime_mode)
            state.startup_metrics['adapter_build_ms'] = round((time.perf_counter() - startup_started_at) * 1000, 2)
            if hasattr(built, 'startup_metrics') and isinstance(built.startup_metrics, dict):
                state.startup_metrics.update(built.startup_metrics)
            runtime_adapter = built
            sessions_started_at = time.perf_counter()
            sessions = built.list_sessions()
            state.startup_metrics['list_sessions_ms'] = round((time.perf_counter() - sessions_started_at) * 1000, 2)
            state.startup_metrics['build_profile_timings'] = getattr(getattr(built, 'session_manager', None), 'metadata', {}).get('build_profile_timings', {}) if hasattr(built, 'session_manager') else {}
            state.startup_metrics['session_manager_profile_timings'] = getattr(getattr(built, 'session_manager', None), 'metadata', {}).get('session_manager_profile_timings', {}) if hasattr(built, 'session_manager') else {}
            session_ready_started_at = time.perf_counter()
            if sessions:
                attach_started_at = time.perf_counter()
                initial_session = sessions[0]
                state.active_session_id = initial_session.session_id
                state.selected_session = 0
                state.startup_metrics['initial_session_attach_ms'] = round((time.perf_counter() - attach_started_at) * 1000, 2)
                state.banner = f"Attached to latest session {initial_session.session_id}"
            else:
                create_started_at = time.perf_counter()
                initial_session = built.create_session()
                state.active_session_id = initial_session.session_id
                state.selected_session = 0
                state.startup_metrics['initial_session_create_ms'] = round((time.perf_counter() - create_started_at) * 1000, 2)
                state.banner = f"Created new session {initial_session.session_id}"
            state.startup_metrics['session_ready_ms'] = round((time.perf_counter() - session_ready_started_at) * 1000, 2)
            state.startup_error = None
        except Exception as exc:
            state.startup_error = repr(exc)
            state.banner = "Startup failed"
            debug_log(f"pty_runtime_cli:startup_failed={exc!r}")
        finally:
            state.startup_metrics['startup_worker_total_ms'] = round((time.perf_counter() - startup_started_at) * 1000, 2)
            state.startup_loading = False

    threading.Thread(target=_startup_worker, name="orbit-pty-startup", daemon=True).start()
    screen = ScreenBuffer()
    in_paste = False
    pty_input_debug_path = _pty_input_debug_path()
    if pty_input_debug_path is not None:
        debug_log(f"pty_runtime_cli:input_debug_log={pty_input_debug_path}")

    last_busy_state = False
    with raw_mode(), alt_screen(), bracketed_paste(), focus_events():
        first_render_done = False
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
            if not first_render_done:
                state.startup_metrics['browse_runtime_cli_entry_to_first_frame_ms'] = round((time.perf_counter() - cli_started_at) * 1000, 2)
                if app_started_at is not None:
                    state.startup_metrics['app_main_to_first_frame_ms'] = round((time.perf_counter() - app_started_at) * 1000, 2)
                first_render_done = True
            if runtime_adapter is not None and not state.startup_loading and 'composer_unlocked_ms' not in state.startup_metrics:
                state.startup_metrics['composer_unlocked_ms'] = round((time.perf_counter() - cli_started_at) * 1000, 2)
                if not state.warmup_started and not state.warmup_done:
                    threading.Thread(target=_warmup_worker, name="orbit-pty-warmup", daemon=True).start()
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

            if runtime_adapter is not None and not state.startup_loading and 'composer_unlocked_ms' not in state.startup_metrics:
                state.startup_metrics['composer_unlocked_ms'] = round((time.perf_counter() - cli_started_at) * 1000, 2)
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
