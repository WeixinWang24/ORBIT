from __future__ import annotations

from orbit.memory.extraction import extract_durable_candidates
from orbit.models import MemoryType


def test_extract_durable_candidates_supports_chinese_and_mixed_patterns():
    candidates = extract_durable_candidates(
        user_text="我更喜欢 concise 一点的 ORBIT 回答，记得先把 transcript store 做完。",
        assistant_text="决定：以后按 architecture-first 来讲。经验：retrieval 结果要保持可见。",
    )

    by_type = {candidate.memory_type: candidate for candidate in candidates}

    assert MemoryType.USER_PREFERENCE in by_type
    assert MemoryType.TODO in by_type
    assert MemoryType.DECISION in by_type
    assert MemoryType.LESSON in by_type

    assert "我更喜欢" in by_type[MemoryType.USER_PREFERENCE].summary_text
    assert "记得" not in by_type[MemoryType.TODO].summary_text
    assert "先把 transcript store 做完" in by_type[MemoryType.TODO].summary_text
    assert not by_type[MemoryType.DECISION].summary_text.lower().startswith("决定")
    assert not by_type[MemoryType.LESSON].summary_text.lower().startswith("经验")
