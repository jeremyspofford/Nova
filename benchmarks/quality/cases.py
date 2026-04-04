"""Benchmark test case definitions for AI quality measurement.

Each case defines: setup (engrams to seed), input (user messages),
expected behaviors, and scoring criteria.
"""
from dataclasses import dataclass, field


@dataclass
class BenchmarkCase:
    name: str
    category: str  # factual_recall, multi_turn, contradiction, tool_selection, temporal, hallucination
    description: str
    seed_engrams: list[dict] = field(default_factory=list)  # {content, node_type, source_type}
    messages: list[str] = field(default_factory=list)  # User messages to send in sequence
    expect_memory_hit: bool = False  # Should the response reference seeded knowledge?
    expect_tool_call: str | None = None  # Tool name expected to be called
    expect_no_hallucination: bool = False  # Should say "I don't know" when no data?
    expect_newer_wins: bool = False  # For contradiction: newer info should override


BENCHMARK_CASES: list[BenchmarkCase] = [
    # ── Factual Recall ──
    BenchmarkCase(
        name="simple_preference_recall",
        category="factual_recall",
        description="Recall a stated preference after seeding it as an engram",
        seed_engrams=[
            {"content": "The user's favorite programming language is Rust", "node_type": "preference", "source_type": "chat"},
        ],
        messages=["What's my favorite programming language?"],
        expect_memory_hit=True,
    ),
    BenchmarkCase(
        name="entity_recall",
        category="factual_recall",
        description="Recall a factual statement about a named entity",
        seed_engrams=[
            {"content": "Nova is deployed on a machine with an AMD RX 7900 XTX GPU", "node_type": "fact", "source_type": "chat"},
        ],
        messages=["What GPU does my Nova machine have?"],
        expect_memory_hit=True,
    ),

    # ── Contradiction Handling ──
    BenchmarkCase(
        name="preference_update",
        category="contradiction",
        description="Newer preference should override older one",
        seed_engrams=[
            {"content": "The user prefers Python for all backend work", "node_type": "preference", "source_type": "chat"},
            {"content": "The user has switched to Go for backend services", "node_type": "preference", "source_type": "chat"},
        ],
        messages=["What language do I prefer for backend work?"],
        expect_memory_hit=True,
        expect_newer_wins=True,
    ),

    # ── Tool Selection ──
    BenchmarkCase(
        name="health_check_tool",
        category="tool_selection",
        description="Should use check_service_health tool when asked about service status",
        seed_engrams=[],
        messages=["Is the memory service healthy right now?"],
        expect_tool_call="check_service_health",
    ),

    # ── No Hallucination ──
    BenchmarkCase(
        name="unknown_topic",
        category="hallucination",
        description="Should admit ignorance when no relevant memories exist",
        seed_engrams=[],
        messages=["What's my cat's name?"],
        expect_no_hallucination=True,
    ),

    # ── Temporal ──
    BenchmarkCase(
        name="recent_work_recall",
        category="temporal",
        description="Recall what was worked on recently based on dated engrams",
        seed_engrams=[
            {"content": "Last week the user was debugging the cortex thinking loop", "node_type": "episode", "source_type": "chat"},
        ],
        messages=["What was I working on last week?"],
        expect_memory_hit=True,
    ),
]
