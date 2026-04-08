from __future__ import annotations

import unittest


class ApplyUnifiedPatchSessionRuntimeTests(unittest.TestCase):
    @unittest.skip(
        "Retired legacy apply_unified_patch contract: current native registry exposes apply_exact_hunk-style patch mutation instead. Rebuild this test against the canonical native patch contract before re-enabling."
    )
    def test_apply_unified_patch_is_blocked_without_fresh_full_read_grounding(self) -> None:
        pass

    @unittest.skip(
        "Retired legacy apply_unified_patch contract: current native registry exposes apply_exact_hunk-style patch mutation instead. Rebuild this test against the canonical native patch contract before re-enabling."
    )
    def test_apply_unified_patch_executes_after_fresh_full_read_grounding(self) -> None:
        pass


if __name__ == "__main__":
    unittest.main()
