from __future__ import annotations

import os
import unittest
from unittest.mock import patch

from orbit.knowledge.context_integration import knowledge_bundle_to_context_fragments, knowledge_preflight_to_context_fragments
from orbit.knowledge.models import KnowledgeAnchor, KnowledgeBundle, KnowledgeNote
from orbit.knowledge.obsidian_service import ObsidianKnowledgeService
from orbit.knowledge.retrieval import retrieve_knowledge_bundle
from orbit.models import ConversationMessage, ConversationSession, MessageRole
from orbit.runtime.providers.openai_codex import OpenAICodexConfig, OpenAICodexExecutionBackend
from src.mcp_servers.apps.obsidian.stdio_server import _check_availability_result, _get_vault_metadata_result, _search_notes_result


class ObsidianSearchFirstSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous = os.environ.get("ORBIT_OBSIDIAN_VAULT_ROOT")
        os.environ["ORBIT_OBSIDIAN_VAULT_ROOT"] = "/Volumes/2TB/MAS/vio_vault"

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("ORBIT_OBSIDIAN_VAULT_ROOT", None)
        else:
            os.environ["ORBIT_OBSIDIAN_VAULT_ROOT"] = self._previous

    def test_obsidian_search_matches_runtime_first_cli_notes(self) -> None:
        result = _search_notes_result(
            query="ORBIT runtime first CLI",
            path="08_Agent_Workspace/Dev/Vio/Memory_KB",
            max_results=5,
            search_in=["title", "summary", "path"],
        )
        titles = [item["title"] for item in result["matches"]]
        self.assertGreaterEqual(result["match_count"], 3)
        self.assertIn("Decision - Runtime-first CLI as primary interface", titles)
        self.assertIn("Project - ORBIT", titles)
        self.assertEqual(result["query_tokens"], ["orbit", "runtime", "first", "cli"])


class ObsidianVaultMetadataFirstSliceTests(unittest.TestCase):
    def setUp(self) -> None:
        self._previous = os.environ.get("ORBIT_OBSIDIAN_VAULT_ROOT")
        os.environ["ORBIT_OBSIDIAN_VAULT_ROOT"] = "/Volumes/2TB/MAS/vio_vault"

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("ORBIT_OBSIDIAN_VAULT_ROOT", None)
        else:
            os.environ["ORBIT_OBSIDIAN_VAULT_ROOT"] = self._previous

    def test_obsidian_vault_metadata_returns_scope_summary(self) -> None:
        result = _get_vault_metadata_result(
            path="08_Agent_Workspace/ORBIT_dev",
            include_top_level_entries=True,
            max_entries=10,
        )
        self.assertEqual(result["path_scope"], "08_Agent_Workspace/ORBIT_dev")
        self.assertEqual(result["vault_name"], "vio_vault")
        self.assertGreater(result["note_count"], 0)
        self.assertGreater(result["directory_count"], 0)
        self.assertTrue(result["excluded_hidden_entries"])
        self.assertIn("top_level_entries", result)
        names = [item["name"] for item in result["top_level_entries"]]
        self.assertIn("00_Overview", names)

    def test_obsidian_availability_reports_vault_only_without_cli(self) -> None:
        with patch("src.mcp_servers.apps.obsidian.stdio_server.shutil.which", return_value=None):
            result = _check_availability_result()
        self.assertTrue(result["available"])
        self.assertEqual(result["availability_level"], "vault_only")
        self.assertEqual(result["recommended_mode"], "mcp_vault_direct")
        self.assertFalse(result["obsidian_cli_found"])


class KnowledgeBundleFirstSliceTests(unittest.TestCase):
    def test_retrieve_knowledge_bundle_prefers_decision_anchor_for_planning_query(self) -> None:
        service = ObsidianKnowledgeService(vault_root="/Volumes/2TB/MAS/vio_vault")
        bundle = retrieve_knowledge_bundle(
            query=type("Q", (), {"query_text": "Need ORBIT runtime first CLI project and decision guidance", "scope_path": None, "preferred_note_types": [], "limit": 5})(),
            obsidian_service=service,
        )
        self.assertIsNotNone(bundle.primary_anchor)
        self.assertEqual(bundle.primary_anchor.anchor_kind, "decision")
        self.assertEqual(bundle.primary_anchor.note.title, "Decision - Runtime-first CLI as primary interface")
        self.assertTrue(any(note.title == "Project - ORBIT" for note in bundle.supporting_notes))

    def test_obsidian_service_get_vault_metadata_returns_structured_metadata(self) -> None:
        service = ObsidianKnowledgeService(vault_root="/Volumes/2TB/MAS/vio_vault")
        metadata = service.get_vault_metadata(path="08_Agent_Workspace/ORBIT_dev", max_entries=5)
        self.assertEqual(metadata["path_scope"], "08_Agent_Workspace/ORBIT_dev")
        self.assertEqual(metadata["vault_name"], "vio_vault")
        self.assertGreater(metadata["note_count"], 0)
        self.assertIn("top_level_entries", metadata)

    def test_obsidian_service_check_availability_returns_structured_status(self) -> None:
        service = ObsidianKnowledgeService(vault_root="/Volumes/2TB/MAS/vio_vault")
        availability = service.check_availability()
        self.assertIn(availability["availability_level"], {"full", "vault_only", "fallback_only", "unavailable"})
        self.assertIn("recommended_mode", availability)
        self.assertIn("checks", availability)

    def test_context_integration_emits_knowledge_fragments(self) -> None:
        decision = KnowledgeNote(path="kb/decision.md", title="Decision", note_type="decision", summary="Decision summary")
        bundle = KnowledgeBundle(
            query_text="decision guidance",
            primary_anchor=KnowledgeAnchor(note=decision, anchor_kind="decision", match_surfaces=["title"], score=3.0),
            decision_notes=[decision],
            procedural_notes=[KnowledgeNote(path="kb/procedure.md", title="Procedure", note_type="procedure", summary="Procedure summary")],
            summary="Summary",
            planning_guidance="Guidance",
            confidence=0.9,
            metadata={"retrieval_mode": "obsidian_anchor_bundle_v1"},
        )
        fragments = knowledge_bundle_to_context_fragments(bundle)
        names = [fragment.fragment_name for fragment in fragments]
        self.assertIn("knowledge_guidance_summary", names)
        self.assertIn("knowledge_planning_guidance", names)
        self.assertIn("knowledge_decision_notes", names)

    def test_preflight_context_integration_emits_preflight_fragments(self) -> None:
        fragments = knowledge_preflight_to_context_fragments(
            availability={
                "availability_level": "vault_only",
                "recommended_mode": "mcp_vault_direct",
                "vault_root_configured": True,
                "vault_root_exists": True,
                "vault_root_readable": True,
                "obsidian_cli_found": False,
                "warnings": ["obsidian CLI not found on PATH"],
                "checks": {"vault_root_exists": True},
            },
            vault_metadata={
                "vault_name": "vio_vault",
                "path_scope": "",
                "note_count": 42,
                "directory_count": 7,
                "latest_modified_at_epoch": 123,
                "top_level_entries": [{"name": "08_Agent_Workspace"}],
            },
        )
        names = [fragment.fragment_name for fragment in fragments]
        self.assertIn("knowledge_availability_preflight", names)
        self.assertIn("knowledge_vault_metadata", names)


class ProviderKnowledgeInjectionTests(unittest.TestCase):
    def test_provider_injects_knowledge_auxiliary_fragments(self) -> None:
        backend = OpenAICodexExecutionBackend(OpenAICodexConfig(enable_tools=False), workspace_root="/Volumes/2TB/MAS/openclaw-core/ORBIT")
        session = ConversationSession(
            session_id="s1",
            conversation_id="c1",
            backend_name="openai_codex",
            model="gpt-5",
        )
        session.runtime_mode = "dev"
        bundle = KnowledgeBundle(
            query_text="decision guidance",
            primary_anchor=KnowledgeAnchor(
                note=KnowledgeNote(
                    path="08_Agent_Workspace/Dev/Vio/Memory_KB/40_Decisions/Decision - Runtime-first CLI as primary interface.md",
                    title="Decision - Runtime-first CLI as primary interface",
                    note_type="decision",
                    summary="Decision summary",
                ),
                anchor_kind="decision",
                match_surfaces=["title"],
                score=4.0,
            ),
            decision_notes=[KnowledgeNote(path="kb/decision.md", title="Decision", note_type="decision", summary="Decision summary")],
            procedural_notes=[KnowledgeNote(path="kb/procedure.md", title="Procedure", note_type="procedure", summary="Procedure summary")],
            summary="Summary",
            planning_guidance="Guidance",
            confidence=0.9,
            metadata={"retrieval_mode": "obsidian_anchor_bundle_v1"},
        )
        mocked_service = type("MockedObsidianService", (), {
            "check_availability": lambda self: {
                "availability_level": "vault_only",
                "recommended_mode": "mcp_vault_direct",
                "vault_root_configured": True,
                "vault_root_exists": True,
                "vault_root_readable": True,
                "obsidian_cli_found": False,
                "warnings": [],
                "checks": {"vault_root_exists": True},
            },
            "get_vault_metadata": lambda self, max_entries=5: {
                "vault_name": "vio_vault",
                "path_scope": "",
                "note_count": 42,
                "directory_count": 7,
                "latest_modified_at_epoch": 123,
                "top_level_entries": [{"name": "08_Agent_Workspace"}],
            },
        })()
        with patch("orbit.runtime.providers.openai_codex.ObsidianKnowledgeService", return_value=mocked_service):
            with patch("orbit.runtime.providers.openai_codex.retrieve_knowledge_bundle", return_value=bundle):
                payload = backend.build_request_payload_from_messages(
                    [ConversationMessage(session_id="s1", role=MessageRole.USER, content="Need decision guidance", turn_index=1)],
                    session=session,
                )
        assembly = session.metadata.get("_pending_context_assembly", {})
        aux = assembly.get("auxiliary_context_fragments", [])
        names = [item.get("fragment_name") for item in aux]
        self.assertEqual(payload.get("prompt_cache_key"), "s1")
        self.assertIn("knowledge_availability_preflight", names)
        self.assertIn("knowledge_vault_metadata", names)
        self.assertIn("knowledge_guidance_summary", names)
        self.assertTrue(any(name and name.startswith("knowledge_primary_anchor:") for name in names))
        self.assertIn("knowledge_decision_notes", names)


if __name__ == "__main__":
    unittest.main()
