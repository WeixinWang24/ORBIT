"""Tests for runtime adapter self-change and build projection.

Covers:
- InterfaceSession carries new fields (active_self_change_plan_id, active_build_record_id,
  last_build_status, last_build_summary, build_policy_profile)
- get_workbench_status() includes build_policy_profile and aggregation fields
- build_policy_profile is "evo-phase-a-build" in evo mode, "none" in dev mode
- Projection populated correctly from session metadata after build/plan lifecycle calls
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.interfaces.build_operation_service import BuildOperationService
from orbit.interfaces.contracts import InterfaceSession
from orbit.interfaces.runtime_adapter import SessionManagerRuntimeAdapter
from orbit.runtime import DummyExecutionBackend, SessionManager
from orbit.runtime.governance.self_change_service import SelfChangeGovernanceService
from orbit.store.sqlite_store import SQLiteStore


def _make_adapter(runtime_mode: str = "evo") -> SessionManagerRuntimeAdapter:
    tmp = tempfile.mkdtemp()
    store = SQLiteStore(db_path=Path(tmp) / "orbit.db")
    backend = DummyExecutionBackend()
    manager = SessionManager(
        store=store,
        backend=backend,
        workspace_root=tmp,
        runtime_mode=runtime_mode,  # type: ignore[arg-type]
    )
    return SessionManagerRuntimeAdapter(session_manager=manager)


class TestInterfaceSessionBuildFields(unittest.TestCase):
    def test_interface_session_has_build_fields(self) -> None:
        adapter = _make_adapter(runtime_mode="dev")
        raw = adapter.session_manager.create_session(backend_name="dummy", model="dummy")
        session = adapter.get_session(raw.session_id)
        self.assertIsInstance(session, InterfaceSession)
        self.assertIsNone(session.active_self_change_plan_id)
        self.assertIsNone(session.active_build_record_id)
        self.assertIsNone(session.last_build_status)
        self.assertIsNone(session.last_build_summary)
        self.assertEqual(session.build_policy_profile, "none")

    def test_evo_mode_session_has_evo_build_policy(self) -> None:
        adapter = _make_adapter(runtime_mode="evo")
        raw = adapter.session_manager.create_session(backend_name="dummy", model="dummy")
        session = adapter.get_session(raw.session_id)
        self.assertEqual(session.build_policy_profile, "evo-phase-a-build")


class TestWorkbenchStatusBuildFields(unittest.TestCase):
    def test_workbench_status_has_build_policy_profile_dev(self) -> None:
        adapter = _make_adapter(runtime_mode="dev")
        status = adapter.get_workbench_status()
        self.assertIn("build_policy_profile", status)
        self.assertEqual(status["build_policy_profile"], "none")
        self.assertIn("active_self_change_plan_ids", status)
        self.assertIn("active_build_record_ids", status)
        self.assertIn("last_build_statuses", status)

    def test_workbench_status_has_build_policy_profile_evo(self) -> None:
        adapter = _make_adapter(runtime_mode="evo")
        status = adapter.get_workbench_status()
        self.assertEqual(status["build_policy_profile"], "evo-phase-a-build")

    def test_workbench_status_aggregates_active_plans(self) -> None:
        adapter = _make_adapter(runtime_mode="evo")
        session = adapter.session_manager.create_session(backend_name="dummy", model="dummy")
        plan = SelfChangeGovernanceService(adapter.session_manager).create_plan(
            session_id=session.session_id,
            title="agg test plan",
            description="for aggregation",
        )
        status = adapter.get_workbench_status()
        self.assertIn(plan.plan_id, status["active_self_change_plan_ids"])

    def test_workbench_status_aggregates_active_builds(self) -> None:
        adapter = _make_adapter(runtime_mode="evo")
        session = adapter.session_manager.create_session(backend_name="dummy", model="dummy")
        record = BuildOperationService(adapter.session_manager).create_build_record(
            session_id=session.session_id,
            summary="aggregation build",
        )
        status = adapter.get_workbench_status()
        self.assertIn(record.build_id, status["active_build_record_ids"])


class TestSessionProjectionAfterLifecycle(unittest.TestCase):
    def test_session_projects_active_plan_id(self) -> None:
        adapter = _make_adapter(runtime_mode="evo")
        session_obj = adapter.session_manager.create_session(backend_name="dummy", model="dummy")
        plan = SelfChangeGovernanceService(adapter.session_manager).create_plan(
            session_id=session_obj.session_id,
            title="projection plan",
            description="test projection",
        )
        mapped = adapter.get_session(session_obj.session_id)
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped.active_self_change_plan_id, plan.plan_id)

    def test_session_projects_active_build_id(self) -> None:
        adapter = _make_adapter(runtime_mode="evo")
        session_obj = adapter.session_manager.create_session(backend_name="dummy", model="dummy")
        record = BuildOperationService(adapter.session_manager).create_build_record(
            session_id=session_obj.session_id,
        )
        mapped = adapter.get_session(session_obj.session_id)
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped.active_build_record_id, record.build_id)

    def test_session_projects_last_build_status_after_finalize(self) -> None:
        adapter = _make_adapter(runtime_mode="evo")
        session_obj = adapter.session_manager.create_session(backend_name="dummy", model="dummy")
        record = BuildOperationService(adapter.session_manager).create_build_record(
            session_id=session_obj.session_id,
        )
        BuildOperationService(adapter.session_manager).finalize_build(
            session_id=session_obj.session_id,
            record=record,
            verdict="passed",
            summary="green",
        )
        mapped = adapter.get_session(session_obj.session_id)
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped.last_build_status, "passed")
        self.assertEqual(mapped.last_build_summary, "green")
        self.assertIsNone(mapped.active_build_record_id)

    def test_session_projects_rolled_back_build(self) -> None:
        adapter = _make_adapter(runtime_mode="evo")
        session_obj = adapter.session_manager.create_session(backend_name="dummy", model="dummy")
        record = BuildOperationService(adapter.session_manager).create_build_record(
            session_id=session_obj.session_id,
        )
        BuildOperationService(adapter.session_manager).mark_rolled_back(
            session_id=session_obj.session_id,
            record=record,
        )
        mapped = adapter.get_session(session_obj.session_id)
        self.assertIsNotNone(mapped)
        self.assertEqual(mapped.last_build_status, "rolled_back")


if __name__ == "__main__":
    unittest.main()
