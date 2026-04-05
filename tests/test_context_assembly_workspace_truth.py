from __future__ import annotations

import unittest

from orbit.models import ConversationMessage, MessageRole
from orbit.runtime.execution.context_assembly import build_text_only_prompt_assembly_plan


class ContextAssemblyWorkspaceTruthTests(unittest.TestCase):
    def test_runtime_workspace_truth_fragment_is_present_and_authoritative(self) -> None:
        plan = build_text_only_prompt_assembly_plan(
            backend_name='openai-codex',
            model='gpt-5.4',
            messages=[ConversationMessage(session_id='s1', role=MessageRole.USER, content='where am i?', turn_index=1)],
            workspace_root='/tmp/orbit-root',
            runtime_mode='evo',
        )
        fragments = {fragment.fragment_name: fragment for fragment in plan.instruction_fragments}
        self.assertIn('runtime_workspace_truth', fragments)
        self.assertIn('/tmp/orbit-root', fragments['runtime_workspace_truth'].content)
        self.assertEqual(fragments['runtime_workspace_truth'].metadata['runtime_mode'], 'evo')
        self.assertGreater(fragments['runtime_workspace_truth'].priority, fragments['runtime_mode'].priority)


if __name__ == '__main__':
    unittest.main()
