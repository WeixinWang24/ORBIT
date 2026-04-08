from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from orbit.models import ManagedProcess
from orbit.store.base import OrbitStore


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ProcessService:
    """
    Service layer for managed process lifecycle.

    Lifecycle truth precedence (highest to lowest):
    1. Runner status file (primary truth): written atomically by managed_process_runner.py.
       Survives service-instance boundaries. Never depends on Popen handle availability.
       Checked first in all terminal-state determinations.
    2. PID polling (fallback only): used when the runner status file is absent or not yet
       terminal. Less reliable across service-instance boundaries. Results from pid polling
       must not override a runner status file that already shows a terminal state.
    3. Store record (context): the persisted ManagedProcess in OrbitStore reflects the last
       reconciled view. Always updated to match the highest-precedence truth found.

    Termination semantics:
    Termination is treated as a lifecycle transition REQUEST, not an optimistic local overwrite.
    The correct sequence is: signal → wait for runner confirmation → escalate if needed →
    reconcile store from runner truth. Never write "killed" to the store as the first step.
    """

    def __init__(self, *, store: OrbitStore, workspace_root: str):
        self.store = store
        self.workspace_root = Path(workspace_root).resolve()
        self.log_dir = self.workspace_root / ".orbit_process"
        self.log_dir.mkdir(parents=True, exist_ok=True)
        # In-memory live Popen handles. Intentionally ephemeral: a new service instance
        # starts with an empty map and recovers lifecycle truth from the runner status file.
        self._live_handles: dict[int, subprocess.Popen[str]] = {}

    def _resolve_cwd(self, cwd: str | None) -> Path:
        if cwd is None or not str(cwd).strip():
            return self.workspace_root
        candidate = Path(cwd)
        resolved = candidate.resolve() if candidate.is_absolute() else (self.workspace_root / candidate).resolve()
        try:
            resolved.relative_to(self.workspace_root)
        except ValueError as exc:
            raise ValueError("cwd escapes workspace") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise ValueError("cwd is not an existing directory")
        return resolved

    def start_process(self, *, session_id: str, command: str, cwd: str | None = None) -> ManagedProcess:
        if not isinstance(command, str) or not command.strip():
            raise ValueError("command must be a non-empty string")
        resolved_cwd = self._resolve_cwd(cwd)
        seed = ManagedProcess(
            session_id=session_id,
            command=command,
            cwd=str(resolved_cwd),
            stdout_path=str(self.log_dir / "pending.stdout.log"),
            stderr_path=str(self.log_dir / "pending.stderr.log"),
            status_path=str(self.log_dir / "pending.status.json"),
        )
        stdout_path = self.log_dir / f"{seed.process_id}.stdout.log"
        stderr_path = self.log_dir / f"{seed.process_id}.stderr.log"
        status_path = self.log_dir / f"{seed.process_id}.status.json"
        runner_path = Path(__file__).resolve().parent / "managed_process_runner.py"
        popen = subprocess.Popen(
            [sys.executable, str(runner_path), str(status_path), str(stdout_path), str(stderr_path), command],
            cwd=str(resolved_cwd),
            text=True,
            start_new_session=True,
        )
        process = seed.model_copy(update={
            "pid": popen.pid,
            "stdout_path": str(stdout_path),
            "stderr_path": str(stderr_path),
            "status_path": str(status_path),
            "status": "running",
            "started_at": utc_now(),
            "updated_at": utc_now(),
        })
        self._live_handles[popen.pid] = popen
        self.store.save_managed_process(process)
        return process

    def get_process(self, process_id: str) -> ManagedProcess | None:
        return self.store.get_managed_process(process_id)

    def refresh_process(self, process_id: str) -> ManagedProcess:
        """
        Refresh the stored process state from persisted truth sources.

        Truth precedence applied here:
        1. Runner status file (primary): if it shows a terminal state, that is the answer.
           No pid polling is performed once a terminal runner status is confirmed.
        2. PID polling (fallback): used only when the runner status file is absent or
           does not yet show a terminal state. Never overrides a confirmed runner terminal.
        """
        process = self.store.get_managed_process(process_id)
        if process is None:
            raise ValueError("unknown process_id")
        if process.pid is None:
            return process

        # Step 1: check runner status file (PRIMARY truth source).
        persisted = self._read_status_file(process.status_path)
        if persisted is not None and persisted.get("status") in {"completed", "failed", "killed"}:
            code = persisted.get("exit_code")
            status = persisted.get("status")
        else:
            # Step 2: pid polling (FALLBACK only — runner status file absent or not yet terminal).
            code = self._poll_pid(process.pid)
            if code is None:
                # Process still running; no update needed.
                return process
            status = "completed" if code == 0 else ("killed" if process.status == "killed" else "failed")

        updated = process.model_copy(update={
            "status": status,
            "exit_code": code,
            "ended_at": process.ended_at or utc_now(),
            "updated_at": utc_now(),
        })
        self.store.save_managed_process(updated)
        self._cleanup_live_handle(process.pid)
        return updated

    def read_output_delta(self, process_id: str, *, max_chars: int = 12000) -> dict[str, Any]:
        process = self.refresh_process(process_id)
        stdout_delta, stdout_offset, stdout_has_more, stdout_original_chars = self._read_delta(process.stdout_path, process.stdout_offset, max_chars)
        stderr_delta, stderr_offset, stderr_has_more, stderr_original_chars = self._read_delta(process.stderr_path, process.stderr_offset, max_chars)
        previous_stdout_offset = process.stdout_offset
        previous_stderr_offset = process.stderr_offset
        updated = process.model_copy(update={
            "stdout_offset": stdout_offset,
            "stderr_offset": stderr_offset,
            "updated_at": utc_now(),
        })
        self.store.save_managed_process(updated)
        return {
            "process": updated,
            "stdout_delta": stdout_delta,
            "stderr_delta": stderr_delta,
            "stdout_has_more": stdout_has_more,
            "stderr_has_more": stderr_has_more,
            "stdout_original_chars": stdout_original_chars,
            "stderr_original_chars": stderr_original_chars,
            "stdout_offset_before": previous_stdout_offset,
            "stderr_offset_before": previous_stderr_offset,
            "stdout_offset_after": stdout_offset,
            "stderr_offset_after": stderr_offset,
        }

    def wait_process(self, process_id: str, *, timeout_seconds: float = 30.0) -> dict[str, Any]:
        process = self.store.get_managed_process(process_id)
        if process is None:
            raise ValueError("unknown process_id")
        if process.pid is None:
            return {"process": process, "timed_out": False}
        live = self._live_handles.get(process.pid)
        if live is not None:
            try:
                live.wait(timeout=timeout_seconds)
                refreshed = self.refresh_process(process_id)
                return {"process": refreshed, "timed_out": False}
            except subprocess.TimeoutExpired:
                refreshed = self.refresh_process(process_id)
                return {"process": refreshed, "timed_out": True}
        # No live handle: a new service instance or the handle was cleaned up.
        # Poll refresh_process (which checks runner status file first) until terminal.
        deadline = time.monotonic() + max(timeout_seconds, 0.0)
        while time.monotonic() < deadline:
            refreshed = self.refresh_process(process_id)
            if refreshed.status != "running":
                return {"process": refreshed, "timed_out": False}
            time.sleep(0.05)
        refreshed = self.refresh_process(process_id)
        return {"process": refreshed, "timed_out": refreshed.status == "running"}

    def terminate_process(
        self,
        process_id: str,
        *,
        escalation_timeout_seconds: float = 3.0,
    ) -> ManagedProcess:
        """
        Terminate a managed process.

        Termination is a lifecycle transition REQUEST, not an optimistic local overwrite.
        Sequence:
        1. Send SIGTERM to the process group (request termination).
        2. Wait for the runner status file to confirm a terminal state (primary truth).
        3. If the runner has not confirmed within the escalation window, send SIGKILL.
        4. Wait briefly for SIGKILL confirmation from the runner status file.
        5. Reconcile final state from runner truth via refresh_process.
           Only if the runner status file is absent/incomplete, fall back to writing
           "killed" locally as a last resort.

        This ensures the store reflects persisted runner truth rather than a local
        optimistic write that may not match what the runner actually recorded.
        """
        process = self.store.get_managed_process(process_id)
        if process is None:
            raise ValueError("unknown process_id")

        # Already terminal in the store — still reconcile against runner truth.
        if process.status in {"completed", "failed", "killed"}:
            return self.refresh_process(process_id)

        if process.pid is not None:
            # Only send signals if the process appears to still be running.
            if self._poll_pid(process.pid) is None:
                # Step 1: wait briefly for the runner to write its initial status file.
                # This confirms the runner has started and registered its SIGTERM handler.
                # Without this, a very early terminate call races with runner startup:
                # SIGTERM arrives before the handler is registered → default SIGTERM
                # kills the runner before it can write terminal state to the status file.
                if not self._read_status_file(process.status_path):
                    self._wait_for_runner_startup(process.status_path, timeout_seconds=2.0)

                # Step 2: SIGTERM to the entire process group (runner + child command).
                # Invariant: process.pid == pgid because the runner was started with
                # start_new_session=True (see start_process), which makes the runner
                # the leader of a new process group where pgid == pid. If the launch
                # path ever changes (e.g., a subprocess wrapper that changes the session),
                # this killpg call would target the wrong group and must be re-evaluated.
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except OSError:
                    pass  # Already gone; proceed to reconciliation.

                # Step 3: wait for runner status file (primary truth) to confirm terminal.
                confirmed = self._wait_for_runner_terminal(
                    process.status_path, timeout_seconds=escalation_timeout_seconds
                )

                # Step 4: escalate to SIGKILL if runner has not confirmed termination.
                if not confirmed:
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except OSError:
                        pass
                    # Brief wait for SIGKILL confirmation from runner status file.
                    self._wait_for_runner_terminal(process.status_path, timeout_seconds=1.0)
                    # AUD-002: check for non-terminal status, not file absence.
                    # SIGKILL cannot be caught; the runner may have written its startup
                    # status=running file but never its terminal file. Overwrite with a
                    # service-written recovery entry so future instances find terminal truth.
                    existing = self._read_status_file(process.status_path)
                    if existing is None or existing.get("status") not in {"completed", "failed", "killed"}:
                        self._write_recovery_status_file(process.status_path, "killed", None)

        # Step 5: reconcile final state from runner truth (primary) with pid fallback.
        refreshed = self.refresh_process(process_id)
        if refreshed.status == "running":
            # AUD-003: guard against phantom kill. A process with pid=None reaches here
            # because refresh_process returns early for pid-None records. Do not silently
            # write 'killed' for a process that may never have existed as a real OS process.
            if process.pid is None:
                warnings.warn(
                    f"terminate_process: process {process_id} has pid=None and status=running "
                    "in the store — cannot confirm any real process was stopped. "
                    "Marking as killed per last-resort fallback.",
                    RuntimeWarning,
                    stacklevel=2,
                )
            # Runner status file absent or incomplete; write killed as last-resort fallback.
            final = refreshed.model_copy(update={
                "status": "killed",
                "updated_at": utc_now(),
                "ended_at": refreshed.ended_at or utc_now(),
            })
            self.store.save_managed_process(final)
            self._cleanup_live_handle(process.pid)
            return final
        self._cleanup_live_handle(process.pid)
        return refreshed

    def _wait_for_runner_terminal(self, status_path: str | None, *, timeout_seconds: float) -> bool:
        """
        Poll the runner status file until it shows a terminal state or the timeout expires.
        Returns True if a terminal state was confirmed by the runner, False if timed out.

        The runner status file is the PRIMARY source of terminal lifecycle truth.
        This method is the correct way to await confirmation of process termination.
        Pid polling is fallback-only for cases where the status file is missing.
        """
        if not status_path:
            return False
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            data = self._read_status_file(status_path)
            if data is not None and data.get("status") in {"completed", "failed", "killed"}:
                return True
            time.sleep(0.05)
        return False

    def _wait_for_runner_startup(self, status_path: str | None, *, timeout_seconds: float) -> bool:
        """
        Wait until the runner status file exists (any content), confirming the runner
        process has started and registered its signal handlers. Returns True if the file
        appeared within the timeout, False otherwise.

        Used by terminate_process to avoid racing with runner startup: sending SIGTERM
        before the runner has registered its handler triggers the default SIGTERM action
        (process death without writing terminal state). Waiting for startup confirmation
        eliminates this race window.
        """
        if not status_path:
            return False
        deadline = time.monotonic() + timeout_seconds
        while time.monotonic() < deadline:
            if Path(status_path).exists():
                return True
            time.sleep(0.02)
        return False

    @staticmethod
    def _write_recovery_status_file(status_path: str | None, status: str, exit_code: int | None) -> None:
        """
        Write a recovery status file on behalf of a runner that was killed before it
        could write its own (e.g., killed by SIGKILL which cannot be caught).
        This ensures future service instances can recover terminal truth from the
        status file rather than falling back to pid polling or store-only state.

        Marked as a service-written recovery entry (not runner-written) via `source` field.
        """
        if not status_path:
            return
        p = Path(status_path)
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "status": status,
                "exit_code": exit_code,
                "signal": None,
                "written_at": datetime.now(timezone.utc).isoformat(),
                "source": "service_recovery",
            }
            # AUD-001: atomic write via temp file + os.replace to prevent partial reads.
            # AUD-001 residual: clean up .tmp on os.replace failure to avoid accumulation.
            tmp_path = p.with_suffix(".tmp")
            try:
                tmp_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
                os.replace(tmp_path, p)
            except Exception:
                tmp_path.unlink(missing_ok=True)
                raise
        except Exception as exc:
            # AUD-005: emit observable warning rather than swallowing silently.
            # Failure here means future instances must fall back to pid polling for
            # terminal truth — which is fragile on PID reuse.
            warnings.warn(
                f"_write_recovery_status_file: failed to write recovery status for {status_path}: {exc}",
                RuntimeWarning,
                stacklevel=2,
            )

    def _poll_pid(self, pid: int) -> int | None:
        """
        Check whether a PID has exited and return its exit code if so, or None if running.

        FALLBACK ONLY: This method is used only when the runner status file is absent or
        does not yet show a terminal state. It must not be used to override runner status
        file truth. Limitations: os.waitpid only works for direct children; for non-child
        PIDs, falls back to os.kill(pid, 0) existence probe which does not recover exit codes.
        """
        live = self._live_handles.get(pid)
        if live is not None:
            code = live.poll()
            if code is None:
                return None
            return code
        try:
            waited_pid, status = os.waitpid(pid, os.WNOHANG)
            if waited_pid == 0:
                return None
            if os.WIFEXITED(status):
                return os.WEXITSTATUS(status)
            if os.WIFSIGNALED(status):
                return 128 + os.WTERMSIG(status)
            return 1
        except ChildProcessError:
            try:
                os.kill(pid, 0)
                return None
            except OSError:
                return 1
        except OSError:
            return 1

    def _cleanup_live_handle(self, pid: int | None) -> None:
        if pid is None:
            return
        live = self._live_handles.pop(pid, None)
        if live is None:
            return
        try:
            if live.stdout is not None:
                live.stdout.close()
        except Exception:
            pass
        try:
            if live.stderr is not None:
                live.stderr.close()
        except Exception:
            pass
        try:
            live.wait(timeout=0.1)
        except Exception:
            pass

    @staticmethod
    def _read_delta(path: str, offset: int, max_chars: int) -> tuple[str, int, bool, int]:
        """
        Read a delta from a persisted output file starting at the given byte offset.
        stdout_path and stderr_path are first-class persisted output surfaces, not
        incidental side artifacts. Output continuity across service instances depends
        on these files and the offsets stored in the ManagedProcess record.
        """
        p = Path(path)
        if not p.exists():
            return "", offset, False, 0
        with open(p, "r", encoding="utf-8", errors="replace") as fh:
            fh.seek(offset)
            data = fh.read(max_chars)
            new_offset = fh.tell()
            next_chunk = fh.read(1)
            has_more = bool(next_chunk)
            original_chars = len(data) + (1 if has_more else 0)
            return data, new_offset, has_more, original_chars

    @staticmethod
    def _read_status_file(path: str | None) -> dict[str, Any] | None:
        """
        Read the runner status file. This is the PRIMARY source of terminal lifecycle truth.
        Returns None if the file is absent, unreadable, or malformed — callers must treat
        None as "truth not yet available" and fall back to pid polling if needed.
        """
        if not path:
            return None
        p = Path(path)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
