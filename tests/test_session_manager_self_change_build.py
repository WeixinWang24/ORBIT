"""Tests for self-change governance and build operation lifecycle.

Covers:
- evo mode guard on self-change plan creation and updates
- full self-change plan lifecycle (create -> status updates)
- has_active_evo_self_change
- build record lifecycle (create -> validate -> finalize)
- append_build_validation_step
- mark_build_rolled_back
- session metadata summary shapes
- emitted event types
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from orbit.models.builds import BuildRecord, SelfChangePlan, ValidationStep
from orbit.runtime import DummyExecutionBackend, SessionManager
from orbit.runtime.governance.self_change_service import SelfChangeGovernanceService
from orbit.interfaces.build_operation_service import BuildOperationService
from orbit.store.sqlite_store import SQLiteStore


def _make_manager(runtime_mode: str = "evo") -> SessionManager:
    tmp = tempfile.mkdtemp()
    store = SQLiteStore(db_path=Path(tmp) / "orbit.db")
    backend = DummyExecutionBackend()
    return SessionManager(
        store=store,
        backend=backend,
        workspace_root=tmp,
        runtime_mode=runtime_mode,  # type: ignore[arg-type]
    )


class TestSelfChangePlanGuard(unittest.TestCase):
    def test_create_plan_requires_evo_mode(self) -> None:
        manager = _make_manager(runtime_mode="dev")
        session = manager.create_session(backend_name="dummy", model="dummy")
        service = SelfChangeGovernanceService(manager)
        with self.assertRaises(ValueError) as ctx:
            service.create_plan(
                session_id=session.session_id,
                title="test plan",
                description="should fail",
            )
        self.assertIn("evo mode", str(ctx.exception))

    def test_update_plan_status_requires_evo_mode(self) -> None:
        evo_manager = _make_manager(runtime_mode="evo")
        evo_session = evo_manager.create_session(backend_name="dummy", model="dummy")
        evo_service = SelfChangeGovernanceService(evo_manager)
        plan = evo_service.create_plan(
            session_id=evo_session.session_id,
            title="plan for dev test",
            description="will try to update in dev mode",
        )
        dev_manager = _make_manager(runtime_mode="dev")
        dev_session = dev_manager.create_session(backend_name="dummy", model="dummy")
        dev_service = SelfChangeGovernanceService(dev_manager)
        with self.assertRaises(ValueError) as ctx:
            dev_service.update_plan_status(
                session_id=dev_session.session_id,
                plan=plan,
                status="approved",
            )
        self.assertIn("evo mode", str(ctx.exception))

    def test_update_plan_status_rejects_invalid_status(self) -> None:
        manager = _make_manager(runtime_mode="evo")
        session = manager.create_session(backend_name="dummy", model="dummy")
        service = SelfChangeGovernanceService(manager)
        plan = service.create_plan(
            session_id=session.session_id,
            title="invalid status test",
            description="test",
        )
        with self.assertRaises(ValueError) as ctx:
            service.update_plan_status(
                session_id=session.session_id,
                plan=plan,
                status="not_a_real_status",
            )
        self.assertIn("invalid self_change_plan status", str(ctx.exception))

    def test_has_active_evo_self_change_dev_mode_always_false(self) -> None:
        manager = _make_manager(runtime_mode="dev")
        session = manager.create_session(backend_name="dummy", model="dummy")
        service = SelfChangeGovernanceService(manager)
        self.assertFalse(service.has_active_evo_self_change(session_id=session.session_id))


class TestBuildRecordGuard(unittest.TestCase):
    def test_create_build_record_requires_evo_mode(self) -> None:
        manager = _make_manager(runtime_mode="dev")
        session = manager.create_session(backend_name="dummy", model="dummy")
        service = BuildOperationService(manager)
        with self.assertRaises(ValueError) as ctx:
            service.create_build_record(session_id=session.session_id)
        self.assertIn("evo mode", str(ctx.exception))

    def test_start_build_validation_requires_evo_mode(self) -> None:
        evo_manager = _make_manager(runtime_mode="evo")
        evo_session = evo_manager.create_session(backend_name="dummy", model="dummy")
        evo_service = BuildOperationService(evo_manager)
        record = evo_service.create_build_record(session_id=evo_session.session_id)
        dev_manager = _make_manager(runtime_mode="dev")
        dev_session = dev_manager.create_session(backend_name="dummy", model="dummy")
        dev_service = BuildOperationService(dev_manager)
        with self.assertRaises(ValueError) as ctx:
            dev_service.start_validation(session_id=dev_session.session_id, record=record)
        self.assertIn("evo mode", str(ctx.exception))

    def test_finalize_build_record_requires_evo_mode(self) -> None:
        evo_manager = _make_manager(runtime_mode="evo")
        evo_session = evo_manager.create_session(backend_name="dummy", model="dummy")
        evo_service = BuildOperationService(evo_manager)
        record = evo_service.create_build_record(session_id=evo_session.session_id)
        dev_manager = _make_manager(runtime_mode="dev")
        dev_session = dev_manager.create_session(backend_name="dummy", model="dummy")
        dev_service = BuildOperationService(dev_manager)
        with self.assertRaises(ValueError) as ctx:
            dev_service.finalize_build(
                session_id=dev_session.session_id,
                record=record,
                verdict="passed",
            )
        self.assertIn("evo mode", str(ctx.exception))

    def test_mark_build_rolled_back_requires_evo_mode(self) -> None:
        evo_manager = _make_manager(runtime_mode="evo")
        evo_session = evo_manager.create_session(backend_name="dummy", model="dummy")
        evo_service = BuildOperationService(evo_manager)
        record = evo_service.create_build_record(session_id=evo_session.session_id)
        dev_manager = _make_manager(runtime_mode="dev")
        dev_session = dev_manager.create_session(backend_name="dummy", model="dummy")
        dev_service = BuildOperationService(dev_manager)
        with self.assertRaises(ValueError) as ctx:
            dev_service.mark_rolled_back(
                session_id=dev_session.session_id,
                record=record,
            )
        self.assertIn("evo mode", str(ctx.exception))

    def test_start_build_validation_rejects_non_planned_record(self) -> None:
        manager = _make_manager(runtime_mode="evo")
        session = manager.create_session(backend_name="dummy", model="dummy")
        service = BuildOperationService(manager)
        record = service.create_build_record(session_id=session.session_id)
        finalized = service.finalize_build(
            session_id=session.session_id, record=record, verdict="failed"
        )
        with self.assertRaises(ValueError) as ctx:
            service.start_validation(session_id=session.session_id, record=finalized)
        self.assertIn("cannot start validation", str(ctx.exception))

    def test_finalize_rejects_already_finalized_record(self) -> None:
        manager = _make_manager(runtime_mode="evo")
        session = manager.create_session(backend_name="dummy", model="dummy")
        service = BuildOperationService(manager)
        record = service.create_build_record(session_id=session.session_id)
        finalized = service.finalize_build(
            session_id=session.session_id, record=record, verdict="passed"
        )
        with self.assertRaises(ValueError) as ctx:
            service.finalize_build(
                session_id=session.session_id, record=finalized, verdict="failed"
            )
        self.assertIn("cannot finalize", str(ctx.exception))

    def test_rollback_rejects_already_rolled_back(self) -> None:
        manager = _make_manager(runtime_mode="evo")
        session = manager.create_session(backend_name="dummy", model="dummy")
        service = BuildOperationService(manager)
        record = service.create_build_record(session_id=session.session_id)
        rolled = service.mark_rolled_back(session_id=session.session_id, record=record)
        with self.assertRaises(ValueError) as ctx:
            service.mark_rolled_back(session_id=session.session_id, record=rolled)
        self.assertIn("already rolled_back", str(ctx.exception))


class TestSelfChangePlanLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _make_manager(runtime_mode="evo")
        self.session = self.manager.create_session(backend_name="dummy", model="dummy")
        self.service = SelfChangeGovernanceService(self.manager)

    def test_create_plan_returns_self_change_plan(self) -> None:
        plan = self.service.create_plan(
            session_id=self.session.session_id,
            title="refactor foo",
            description="bounded refactor of module foo",
        )
        self.assertIsInstance(plan, SelfChangePlan)
        self.assertEqual(plan.status, "planned")
        self.assertEqual(plan.title, "refactor foo")
        self.assertEqual(plan.session_id, self.session.session_id)

    def test_create_plan_updates_session_metadata(self) -> None:
        plan = self.service.create_plan(
            session_id=self.session.session_id,
            title="patch bar",
            description="add new bar function",
        )
        session = self.manager.get_session(self.session.session_id)
        sc = session.metadata.get("self_change", {})
        self.assertEqual(sc.get("active_plan_id"), plan.plan_id)
        self.assertEqual(sc["last_plan"]["plan_id"], plan.plan_id)
        self.assertEqual(sc["last_plan"]["status"], "planned")

    def test_get_active_self_change_plan_returns_plan_id(self) -> None:
        plan = self.service.create_plan(
            session_id=self.session.session_id,
            title="add feature",
            description="add X feature",
        )
        active = self.service.get_active_plan_id(session_id=self.session.session_id)
        self.assertEqual(active, plan.plan_id)

    def test_has_active_evo_self_change_true_after_create(self) -> None:
        self.service.create_plan(
            session_id=self.session.session_id,
            title="some plan",
            description="desc",
        )
        self.assertTrue(self.service.has_active_evo_self_change(session_id=self.session.session_id))

    def test_update_plan_status_to_completed_clears_active(self) -> None:
        plan = self.service.create_plan(
            session_id=self.session.session_id,
            title="complete me",
            description="will complete",
        )
        updated = self.service.update_plan_status(
            session_id=self.session.session_id,
            plan=plan,
            status="completed",
        )
        self.assertEqual(updated.status, "completed")
        session = self.manager.get_session(self.session.session_id)
        sc = session.metadata.get("self_change", {})
        self.assertIsNone(sc.get("active_plan_id"))
        self.assertEqual(sc["last_plan"]["status"], "completed")

    def test_update_plan_status_emits_event(self) -> None:
        plan = self.service.create_plan(
            session_id=self.session.session_id,
            title="emit test",
            description="test event emission",
        )
        self.service.update_plan_status(
            session_id=self.session.session_id,
            plan=plan,
            status="approved",
        )
        events = self.manager.store.list_events_for_run(self.session.conversation_id)
        event_types = [e.event_type for e in events]
        self.assertIn("self_change_plan_created", event_types)
        self.assertIn("self_change_plan_status_changed", event_types)


class TestBuildRecordLifecycle(unittest.TestCase):
    def setUp(self) -> None:
        self.manager = _make_manager(runtime_mode="evo")
        self.session = self.manager.create_session(backend_name="dummy", model="dummy")
        self.build_service = BuildOperationService(self.manager)
        self.self_change_service = SelfChangeGovernanceService(self.manager)

    def test_create_build_record_returns_build_record(self) -> None:
        record = self.build_service.create_build_record(
            session_id=self.session.session_id,
            summary="initial build",
        )
        self.assertIsInstance(record, BuildRecord)
        self.assertEqual(record.status, "planned")
        self.assertEqual(record.session_id, self.session.session_id)

    def test_create_build_record_with_linked_plan(self) -> None:
        plan = self.self_change_service.create_plan(
            session_id=self.session.session_id,
            title="linked plan",
            description="plan linked to build",
        )
        record = self.build_service.create_build_record(
            session_id=self.session.session_id,
            linked_plan_id=plan.plan_id,
            summary="build for plan",
        )
        self.assertEqual(record.linked_plan_id, plan.plan_id)

    def test_create_build_record_updates_session_metadata(self) -> None:
        record = self.build_service.create_build_record(
            session_id=self.session.session_id,
        )
        session = self.manager.get_session(self.session.session_id)
        bm = session.metadata.get("build_management", {})
        self.assertEqual(bm.get("active_build_id"), record.build_id)
        self.assertEqual(bm["last_build"]["build_id"], record.build_id)
        self.assertEqual(bm["last_build"]["status"], "planned")

    def test_get_active_build_record_returns_id(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        active = self.build_service.get_active_build_record_id(session_id=self.session.session_id)
        self.assertEqual(active, record.build_id)

    def test_start_build_validation_transitions_to_validating(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        updated = self.build_service.start_validation(
            session_id=self.session.session_id,
            record=record,
        )
        self.assertEqual(updated.status, "validating")
        session = self.manager.get_session(self.session.session_id)
        bm = session.metadata.get("build_management", {})
        self.assertEqual(bm.get("active_build_id"), record.build_id)

    def test_append_build_validation_step(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        record = self.build_service.start_validation(
            session_id=self.session.session_id,
            record=record,
        )
        updated = self.build_service.append_validation_step(
            session_id=self.session.session_id,
            record=record,
            step_name="pytest",
            status="passed",
            output="all tests passed",
        )
        self.assertEqual(len(updated.validation_steps), 1)
        step = updated.validation_steps[0]
        self.assertIsInstance(step, ValidationStep)
        self.assertEqual(step.step_name, "pytest")
        self.assertEqual(step.status, "passed")
        self.assertEqual(step.output, "all tests passed")

    def test_finalize_build_record_passed(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        record = self.build_service.start_validation(
            session_id=self.session.session_id, record=record
        )
        finalized = self.build_service.finalize_build(
            session_id=self.session.session_id,
            record=record,
            verdict="passed",
            summary="all checks green",
        )
        self.assertEqual(finalized.status, "passed")
        self.assertEqual(finalized.summary, "all checks green")
        self.assertIsNotNone(finalized.finalized_at)
        session = self.manager.get_session(self.session.session_id)
        bm = session.metadata.get("build_management", {})
        self.assertIsNone(bm.get("active_build_id"))
        self.assertEqual(bm["last_build"]["status"], "passed")

    def test_finalize_build_record_failed(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        finalized = self.build_service.finalize_build(
            session_id=self.session.session_id,
            record=record,
            verdict="failed",
            summary="test failure",
        )
        self.assertEqual(finalized.status, "failed")

    def test_finalize_build_record_invalid_verdict_raises(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        with self.assertRaises(ValueError):
            self.build_service.finalize_build(
                session_id=self.session.session_id,
                record=record,
                verdict="unknown_verdict",
            )

    def test_mark_build_rolled_back(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        rolled = self.build_service.mark_rolled_back(
            session_id=self.session.session_id,
            record=record,
        )
        self.assertEqual(rolled.status, "rolled_back")
        self.assertIsNotNone(rolled.rolled_back_at)
        session = self.manager.get_session(self.session.session_id)
        bm = session.metadata.get("build_management", {})
        self.assertEqual(bm["last_build"]["status"], "rolled_back")

    def test_append_validation_step_updates_session_metadata(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        record = self.build_service.start_validation(
            session_id=self.session.session_id, record=record
        )
        record = self.build_service.append_validation_step(
            session_id=self.session.session_id,
            record=record,
            step_name="ruff",
            status="passed",
            output="no issues",
        )
        session = self.manager.get_session(self.session.session_id)
        bm = session.metadata.get("build_management", {})
        self.assertEqual(bm.get("active_build_id"), record.build_id)
        self.assertEqual(len(record.validation_steps), 1)
        self.assertEqual(record.validation_steps[0].step_name, "ruff")

    def test_build_lifecycle_events_emitted(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        record = self.build_service.start_validation(
            session_id=self.session.session_id, record=record
        )
        record = self.build_service.append_validation_step(
            session_id=self.session.session_id,
            record=record,
            step_name="mypy",
            status="passed",
        )
        self.build_service.finalize_build(
            session_id=self.session.session_id,
            record=record,
            verdict="passed",
        )
        events = self.manager.store.list_events_for_run(self.session.conversation_id)
        event_types = [e.event_type for e in events]
        self.assertIn("build_record_created", event_types)
        self.assertIn("build_validation_started", event_types)
        self.assertIn("build_validation_step_appended", event_types)
        self.assertIn("build_record_finalized", event_types)

    def test_rollback_emits_rolled_back_event(self) -> None:
        record = self.build_service.create_build_record(session_id=self.session.session_id)
        self.build_service.mark_rolled_back(
            session_id=self.session.session_id, record=record
        )
        events = self.manager.store.list_events_for_run(self.session.conversation_id)
        event_types = [e.event_type for e in events]
        self.assertIn("build_record_rolled_back", event_types)


if __name__ == "__main__":
    unittest.main()
