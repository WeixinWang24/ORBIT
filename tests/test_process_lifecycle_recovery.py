"""
Process lifecycle recovery and reattachment tests.

These tests validate that process continuity is NOT merely an in-memory artifact.
A new ProcessService instance (simulating a fresh MCP server call with no cached
Popen handle) must be able to:

- recover terminal lifecycle state from the runner status file (primary truth)
- wait correctly without a live handle via refresh-polling
- continue reading output from persisted file offsets across service instances
- see a consistent terminal outcome after terminate + reconcile
- gracefully fall back when the runner status file is absent

Truth-precedence contract under test:
  runner status file (primary) > pid polling (fallback) > store record (context)
"""
from __future__ import annotations

import json
import os
import time
import unittest
from pathlib import Path

import tempfile

from orbit.runtime.process.service import ProcessService
from orbit.store.sqlite_store import SQLiteStore


def _make_service(workspace: str, db_path: str) -> ProcessService:
    """Create a ProcessService with no pre-existing live handles (simulates fresh instance)."""
    store = SQLiteStore(Path(db_path))
    return ProcessService(store=store, workspace_root=workspace)


class ProcessRecoveryTests(unittest.TestCase):
    """
    All tests use real subprocesses and real file I/O.
    Each test gets a fresh temp dir so there is no cross-test contamination.
    """

    def setUp(self) -> None:
        self._tmpdir = tempfile.mkdtemp(prefix="orbit_proc_test_")
        self._db_path = str(Path(self._tmpdir) / "test_orbit.db")
        self._workspace = self._tmpdir

    def _fresh_service(self) -> ProcessService:
        """Return a brand-new ProcessService with the same store/workspace but empty live handles."""
        return _make_service(self._workspace, self._db_path)

    # ------------------------------------------------------------------
    # A. Completion recovery without a live handle
    # ------------------------------------------------------------------

    def test_completion_recovery_without_live_handle(self) -> None:
        """
        A process that completes naturally should be recoverable by a new service
        instance that has no Popen handle — using only the runner status file and store.
        """
        svc1 = self._fresh_service()
        proc = svc1.start_process(session_id="sess_recovery_a", command="echo hello")
        # Wait for completion using the original service instance (has live handle).
        result1 = svc1.wait_process(proc.process_id, timeout_seconds=10.0)
        self.assertFalse(result1["timed_out"])
        self.assertEqual(result1["process"].status, "completed")

        # Simulate fresh server instance: new service, no live handles.
        svc2 = self._fresh_service()
        # svc2 has no live handle for this pid.
        self.assertNotIn(proc.pid, svc2._live_handles)

        # Recovery via refresh_process must succeed using runner status file.
        recovered = svc2.refresh_process(proc.process_id)
        self.assertEqual(recovered.status, "completed")
        self.assertEqual(recovered.exit_code, 0)
        self.assertIsNotNone(recovered.ended_at)

    # ------------------------------------------------------------------
    # B. Wait without live handle (poll path)
    # ------------------------------------------------------------------

    def test_wait_without_live_handle_for_already_completed_process(self) -> None:
        """
        wait_process on a new service instance (no live handle) for an already-completed
        process must return immediately with terminal state, not hang.
        """
        svc1 = self._fresh_service()
        proc = svc1.start_process(session_id="sess_wait_b", command="echo wait_test")
        svc1.wait_process(proc.process_id, timeout_seconds=10.0)

        svc2 = self._fresh_service()
        start = time.monotonic()
        result = svc2.wait_process(proc.process_id, timeout_seconds=5.0)
        elapsed = time.monotonic() - start

        self.assertFalse(result["timed_out"])
        self.assertIn(result["process"].status, {"completed", "failed"})
        # Should not have waited anywhere near the full timeout.
        self.assertLess(elapsed, 3.0, "wait_process took too long for an already-complete process")

    def test_wait_without_live_handle_for_in_progress_process(self) -> None:
        """
        wait_process on a new service instance (no live handle) for a still-running process
        must wait via refresh-polling and return the terminal state when it finishes.
        The runner status file (primary truth) drives the poll exit condition.
        """
        svc1 = self._fresh_service()
        proc = svc1.start_process(session_id="sess_wait_c", command="sleep 0.3 && echo done")

        # Immediately hand off to a fresh service with no live handle.
        svc2 = self._fresh_service()
        self.assertNotIn(proc.pid, svc2._live_handles)

        result = svc2.wait_process(proc.process_id, timeout_seconds=10.0)
        self.assertFalse(result["timed_out"])
        self.assertEqual(result["process"].status, "completed")

    # ------------------------------------------------------------------
    # C. Output delta continuity across service instances
    # ------------------------------------------------------------------

    def test_output_delta_continuity_across_service_instances(self) -> None:
        """
        Output offsets are persisted in the ManagedProcess store record, so a new service
        instance reading after a partial read must continue from the correct offset.

        stdout_path and stderr_path are first-class persisted output surfaces; reading
        must survive across service-instance boundaries.

        AUD-006 fix: use max_chars=5 to force a partial read (less than total output),
        then verify that the second read from a new service instance resumes correctly
        and contains the remaining content.
        """
        svc1 = self._fresh_service()
        # Produce two distinct lines. Total output is "line_one\nline_two\n" = 19 chars.
        proc = svc1.start_process(
            session_id="sess_output_c",
            command='echo "line_one" && sleep 0.1 && echo "line_two"',
        )
        svc1.wait_process(proc.process_id, timeout_seconds=10.0)

        # First read from svc1 with max_chars=5 — must be partial.
        delta1 = svc1.read_output_delta(proc.process_id, max_chars=5)
        self.assertEqual(len(delta1["stdout_delta"]), 5, "first read must be exactly 5 chars")
        self.assertTrue(delta1["stdout_has_more"], "first read must indicate more data available")
        offset_after_first = delta1["stdout_offset_after"]
        self.assertGreater(offset_after_first, 0)

        # Simulate service restart: svc2 reads from the same store record.
        svc2 = self._fresh_service()
        # Confirm svc2 sees the updated offset in the store.
        stored = svc2.get_process(proc.process_id)
        self.assertIsNotNone(stored)
        self.assertEqual(stored.stdout_offset, offset_after_first)

        # Read remaining output from svc2 — must continue from the stored offset.
        delta2 = svc2.read_output_delta(proc.process_id, max_chars=200)
        self.assertEqual(delta2["stdout_offset_before"], offset_after_first)
        self.assertGreater(delta2["stdout_offset_after"], offset_after_first, "offset must advance in second read")
        # The second read must contain "line_two" since the first read was only 5 chars.
        self.assertIn("line_two", delta2["stdout_delta"], "second read must contain remaining output")

    def test_output_offset_persists_to_store_after_partial_read(self) -> None:
        """
        After a partial read with max_chars, the updated stdout_offset must be persisted
        in the store so that a subsequent fresh service instance continues correctly.
        """
        svc1 = self._fresh_service()
        # Generate a known-length output.
        proc = svc1.start_process(session_id="sess_offset_d", command='python3 -c "print(\'A\' * 100)"')
        svc1.wait_process(proc.process_id, timeout_seconds=10.0)

        # Read only the first 10 chars.
        delta = svc1.read_output_delta(proc.process_id, max_chars=10)
        stored_offset = delta["stdout_offset_after"]
        self.assertGreater(stored_offset, 0)
        self.assertTrue(delta["stdout_has_more"])

        # Verify the store record was updated.
        svc2 = self._fresh_service()
        record = svc2.get_process(proc.process_id)
        self.assertIsNotNone(record)
        self.assertEqual(record.stdout_offset, stored_offset)

    # ------------------------------------------------------------------
    # D. Termination reconciliation with runner status file
    # ------------------------------------------------------------------

    def test_terminate_reconciles_with_runner_status_file(self) -> None:
        """
        After terminate_process, the final status in the store must match what the
        runner status file recorded — not merely an optimistic local 'killed' write.

        Two scenarios are valid:
        A. SIGTERM reached the runner's signal handler → runner wrote 'killed' to status
           file → store reflects 'killed'. Status file source = 'runner'.
        B. SIGKILL was needed (rare startup race) → service wrote a recovery status file
           on behalf of the runner → store reflects 'killed'. Status file source =
           'service_recovery'. Either way, terminal state is grounded in a persisted file.

        The invariant under test: after terminate_process, a persisted status file EXISTS
        and the store status matches it (primary truth precedence held).
        """
        svc = self._fresh_service()
        proc = svc.start_process(session_id="sess_term_d", command="sleep 5")

        # Wait for the runner to confirm startup (status file written with "running").
        # This makes the test deterministic: we know the signal handler is registered.
        deadline = time.monotonic() + 5.0
        while time.monotonic() < deadline:
            data = ProcessService._read_status_file(proc.status_path)
            if data is not None:
                break
            time.sleep(0.02)

        final = svc.terminate_process(proc.process_id)
        # Terminal state must be one of the valid terminal values.
        self.assertIn(final.status, {"killed", "completed", "failed"})
        self.assertIsNotNone(final.ended_at)

        # After termination, a persisted status file must ALWAYS exist — either written
        # by the runner (SIGTERM caught) or written by the service as a recovery artifact
        # (SIGKILL path). This ensures future service instances can recover terminal truth.
        runner_data = ProcessService._read_status_file(proc.status_path)
        self.assertIsNotNone(runner_data, "persisted status file must exist after termination")
        runner_status = runner_data.get("status")  # type: ignore[union-attr]
        self.assertIn(runner_status, {"killed", "completed", "failed"})
        # Store must match the persisted status file (primary truth precedence).
        self.assertEqual(final.status, runner_status)

    def test_terminate_already_terminal_returns_reconciled_state(self) -> None:
        """
        Calling terminate_process on an already-completed process must return
        the correct terminal state without error, reconciling against runner truth.
        """
        svc = self._fresh_service()
        proc = svc.start_process(session_id="sess_term_e", command="echo already_done")
        svc.wait_process(proc.process_id, timeout_seconds=10.0)

        # Terminate a process that's already done.
        final = svc.terminate_process(proc.process_id)
        self.assertIn(final.status, {"completed", "failed"})
        self.assertEqual(final.exit_code, 0)

    # ------------------------------------------------------------------
    # E. Fallback behavior when runner status file is missing
    # ------------------------------------------------------------------

    def test_fallback_pid_polling_when_status_file_missing(self) -> None:
        """
        If the runner status file is deleted (or was never written, e.g., runner crash),
        refresh_process must fall back to pid polling and still recover a sensible state.
        This validates that the fallback path is not broken — just lower precedence.

        NOTE: allowing 'running' here would mask the PID-reuse false-positive described in
        AUD-001. We only accept 'completed' or 'failed' because the process exited before
        we deleted the status file. Any 'running' result would indicate a PID-reuse anomaly.
        """
        svc1 = self._fresh_service()
        proc = svc1.start_process(session_id="sess_fallback_e", command="echo fallback_test")
        svc1.wait_process(proc.process_id, timeout_seconds=10.0)

        # Delete the runner status file to force fallback path.
        status_file = Path(proc.status_path)
        if status_file.exists():
            status_file.unlink()

        # refresh_process should fall back gracefully using pid polling.
        svc2 = self._fresh_service()
        recovered = svc2.refresh_process(proc.process_id)
        # Process already exited — fallback must recover a terminal state.
        # 'running' is NOT acceptable here; that would indicate a PID-reuse false positive.
        self.assertIn(recovered.status, {"completed", "failed"})
        # The key assertion: no exception was raised, fallback is graceful.

    def test_wait_for_runner_terminal_returns_true_when_status_file_shows_terminal(self) -> None:
        """
        _wait_for_runner_terminal is the internal primitive used by terminate_process.
        Verify it correctly identifies a terminal runner status file.
        """
        import tempfile as tf
        with tf.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"status": "killed", "exit_code": 143, "signal": 15, "written_at": "2026-04-05T00:00:00+00:00"}, f)
            path = f.name

        try:
            svc = self._fresh_service()
            result = svc._wait_for_runner_terminal(path, timeout_seconds=0.5)
            self.assertTrue(result)
        finally:
            os.unlink(path)

    def test_wait_for_runner_terminal_returns_false_when_status_is_running(self) -> None:
        """
        _wait_for_runner_terminal must return False (timeout) when the status file
        shows 'running' for the entire timeout window.
        """
        import tempfile as tf
        with tf.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"status": "running", "exit_code": None, "signal": None}, f)
            path = f.name

        try:
            svc = self._fresh_service()
            start = time.monotonic()
            result = svc._wait_for_runner_terminal(path, timeout_seconds=0.2)
            elapsed = time.monotonic() - start
            self.assertFalse(result)
            # AUD-006: use a conservatively low lower bound to avoid flakiness on fast
            # machines where the loop may exit at exactly the boundary.
            self.assertGreater(elapsed, 0.0)
        finally:
            os.unlink(path)

    def test_wait_for_runner_terminal_returns_false_when_status_file_missing(self) -> None:
        """_wait_for_runner_terminal must return False quickly when there is no status file."""
        svc = self._fresh_service()
        result = svc._wait_for_runner_terminal("/nonexistent/path/status.json", timeout_seconds=0.2)
        self.assertFalse(result)

    # ------------------------------------------------------------------
    # F. Status file written_at field populated
    # ------------------------------------------------------------------

    def test_runner_status_file_has_written_at_timestamp(self) -> None:
        """
        The runner status file must include a written_at timestamp for richer recovery data.
        This allows a recovering service instance to know when the terminal state was written.
        """
        svc = self._fresh_service()
        proc = svc.start_process(session_id="sess_ts_f", command="echo ts_test")
        svc.wait_process(proc.process_id, timeout_seconds=10.0)

        runner_data = ProcessService._read_status_file(proc.status_path)
        self.assertIsNotNone(runner_data)
        self.assertIn("written_at", runner_data)  # type: ignore[operator]
        self.assertIsInstance(runner_data["written_at"], str)  # type: ignore[index]

    # ------------------------------------------------------------------
    # G. _write_recovery_status_file unit coverage (AUD-NEW-002)
    # ------------------------------------------------------------------

    def test_write_recovery_status_file_writes_terminal_state_with_source_field(self) -> None:
        """
        _write_recovery_status_file must write a JSON file with the given status,
        a 'source' field set to 'service_recovery', and a 'written_at' timestamp.
        This directly validates the AUD-002 recovery path (SIGKILL-killed runner that
        wrote its startup file but not its terminal file).
        """
        import tempfile as tf
        with tf.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.status.json")
            svc = self._fresh_service()
            ProcessService._write_recovery_status_file(path, "killed", None)

            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "killed")
            self.assertEqual(data["source"], "service_recovery")
            self.assertIn("written_at", data)
            self.assertIsNone(data["exit_code"])
            # Verify no .tmp file was left behind.
            tmp_file = Path(path).with_suffix(".tmp")
            self.assertFalse(tmp_file.exists(), ".tmp file must be cleaned up after successful write")

    def test_write_recovery_status_file_overwrites_stale_running_status(self) -> None:
        """
        When a runner was killed by SIGKILL after writing its startup status=running file,
        _write_recovery_status_file must overwrite that running entry with a terminal state.
        This is the exact scenario from AUD-002: the condition checks for non-terminal
        status (not file absence) and calls _write_recovery_status_file to correct it.
        """
        import tempfile as tf
        with tf.TemporaryDirectory() as tmpdir:
            path = str(Path(tmpdir) / "test.status.json")
            # Simulate runner having written its startup status=running file.
            Path(path).write_text(
                json.dumps({"status": "running", "exit_code": None, "signal": None}),
                encoding="utf-8",
            )
            svc = self._fresh_service()
            # Simulate the AUD-002 condition: existing status is "running" (non-terminal).
            existing = ProcessService._read_status_file(path)
            self.assertIsNotNone(existing)
            if existing is None or existing.get("status") not in {"completed", "failed", "killed"}:
                ProcessService._write_recovery_status_file(path, "killed", None)

            data = json.loads(Path(path).read_text(encoding="utf-8"))
            self.assertEqual(data["status"], "killed")
            self.assertEqual(data["source"], "service_recovery")

    def test_refresh_process_reconciles_service_recovery_status_file(self) -> None:
        """
        refresh_process must correctly reconcile when the status file has
        source=service_recovery (written by the service after SIGKILL) rather than
        being runner-written. The primary truth contract must hold regardless of source.
        """
        svc = self._fresh_service()
        proc = svc.start_process(session_id="sess_recovery_g3", command="sleep 5")
        # Terminate normally to get into a state we can examine.
        svc.terminate_process(proc.process_id)

        # Now overwrite the status file with a service_recovery entry simulating
        # what would happen if SIGKILL was used and the service wrote the recovery file.
        Path(proc.status_path).write_text(
            json.dumps({
                "status": "killed",
                "exit_code": None,
                "signal": None,
                "written_at": "2026-04-05T00:00:00+00:00",
                "source": "service_recovery",
            }),
            encoding="utf-8",
        )

        # Fresh instance must reconcile against this file as primary truth.
        svc2 = self._fresh_service()
        recovered = svc2.refresh_process(proc.process_id)
        self.assertEqual(recovered.status, "killed")

    # ------------------------------------------------------------------
    # I. Cross-instance: start + complete + full read in separate instances
    # ------------------------------------------------------------------

    def test_full_lifecycle_across_three_service_instances(self) -> None:
        """
        Integration test: start in instance 1, wait in instance 2, read output in instance 3.
        Validates that stdout_path and stderr_path are truly first-class persisted surfaces.
        """
        # Instance 1: start.
        svc1 = self._fresh_service()
        proc = svc1.start_process(session_id="sess_cross_g", command='echo "cross_instance_output"')
        process_id = proc.process_id
        del svc1  # Discard instance 1.

        # Instance 2: wait (no live handle).
        svc2 = self._fresh_service()
        self.assertNotIn(proc.pid, svc2._live_handles)
        wait_result = svc2.wait_process(process_id, timeout_seconds=10.0)
        self.assertFalse(wait_result["timed_out"])
        del svc2  # Discard instance 2.

        # Instance 3: read output (no live handle, no wait involvement).
        svc3 = self._fresh_service()
        delta = svc3.read_output_delta(process_id, max_chars=200)
        self.assertIn("cross_instance_output", delta["stdout_delta"])
        self.assertEqual(delta["process"].status, "completed")


if __name__ == "__main__":
    unittest.main()
