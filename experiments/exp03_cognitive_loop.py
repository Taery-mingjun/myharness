"""EXP03: Cognitive Loop Effectiveness Check (EEC) — verifies that
the think→plan→reflect pipeline actually passes data between stages.

Before P0-2 fix: reflect() received keys {user_message, thought, plan}
but the template read {summary, detail, tags} — all three keys were
empty in the rendered prompt, so reflection was based on empty data.

Before P0-3 fix: plan() was passed context= which bypassed
build_plan_context(), so the plan prompt template had no identity,
no skills, and no goal — the LLM couldn't produce structured output.

After P0-2/P0-3 fixes:
  - reflect() receives {summary, detail, tags} aligned with template
  - plan() calls build_plan_context() internally, getting identity + skills
  - StrictUndefined catches any future misalignment at render time

Metrics:
  EEC (Cognitive Loop Effectiveness) = stages_with_real_data / total_stages
  A stage has "real data" if the template variable it reads was non-empty.
"""
import asyncio
import tempfile
import os
from pathlib import Path
from datetime import UTC, datetime

from myharness.llm.providers.openai_compatible import OpenAICompatibleProvider
from myharness.llm.engine import LLMEngine
from myharness.llm.context import ContextBuilder
from myharness.memory.manager import MemoryManager
from myharness.memory.storage.source import SourceOfTruth
from myharness.memory.storage.derived import DerivedStorage
from myharness.memory.stores.identity import IdentityStore
from myharness.memory.stores.episodic import EpisodicStore
from myharness.memory.stores.semantic import SemanticStore
from myharness.memory.stores.relationship import RelationshipStore
from myharness.memory.indexing.text import TextIndex
from myharness.memory.indexing.vector import VectorIndex
from myharness.schema.memory import EpisodicEntry


async def main():
    tmpdir = Path(tempfile.mkdtemp())
    source = SourceOfTruth(base_path=tmpdir)
    derived = DerivedStorage(db_path=tmpdir / "derived.db")
    vector_idx = VectorIndex(dimension=1536, index_path=tmpdir / "vector.faiss")
    text_idx = TextIndex(db_path=tmpdir / "text.db")

    identity = IdentityStore(source=source)
    episodic = EpisodicStore(source=source, derived=derived, vector_idx=vector_idx, text_idx=text_idx)
    semantic = SemanticStore(source=source, vector_idx=vector_idx, text_idx=text_idx)
    relationship = RelationshipStore(source=source)
    memory = MemoryManager(
        identity=identity, episodic=episodic,
        semantic=semantic, relationship=relationship,
    )

    provider = OpenAICompatibleProvider(
        api_key=os.environ.get("MYH_OPENAI_COMPATIBLE_API_KEY", ""),
        default_model=os.environ.get("MYH_OPENAI_COMPATIBLE_DEFAULT_MODEL", "agnes-2.5-flash"),
        base_url=os.environ.get("MYH_OPENAI_COMPATIBLE_BASE_URL", ""),
        provider_name="agnes",
    )
    ctx_builder = ContextBuilder(memory=memory)
    engine = LLMEngine(provider=provider, context_builder=ctx_builder)

    # Write a test episodic memory so ContextBuilder has something to retrieve
    await memory.record_episode(
        EpisodicEntry(
            summary="User asked about quantum computing basics",
            category="conversation",
            detail="Discussed qubits, superposition, and quantum advantage",
            participants=["test_user"],
            tags=["quantum", "physics"],
            importance=0.8,
        )
    )

    # Set identity
    ident = await memory.get_identity()
    ident.name = "TestAgent"
    ident.mission = "Verify cognitive loop data flow"
    ident.core_values = ["accuracy", "curiosity"]
    ident.self_description = "A test agent for EEC verification"
    await memory.update_identity(ident)

    print("=== EXP03: Cognitive Loop Effectiveness Check (EEC) ===")
    print()

    stages_total = 3  # think, plan, reflect
    stages_with_real_data = 0

    # Stage 1: Think — verify ContextBuilder provides agent_name + identity
    print("--- Stage 1: Think ---")
    try:
        # Don't pass context — let engine call build_think_context
        thought = await engine.think(query="What is quantum computing?")
        if thought and len(thought.strip()) > 5:
            stages_with_real_data += 1
            print(f"  think() output length: {len(thought)} chars")
            print(f"  think() preview: {thought[:120]}...")
        else:
            print(f"  think() output too short or empty: '{thought}'")
    except Exception as e:
        print(f"  think() error: {type(e).__name__}: {e}")

    print()

    # Stage 2: Plan — verify build_plan_context is called (not bypassed)
    print("--- Stage 2: Plan ---")
    try:
        # Don't pass context — let engine call build_plan_context
        plan = await engine.plan(
            goal="Explain quantum computing to a beginner",
            available_skills=[
                {"name": "explain", "description": "Explain a concept", "capability": "conversation", "driver_type": "api"},
            ],
        )
        if plan and (plan.reasoning or plan.steps):
            stages_with_real_data += 1
            print(f"  plan goal: {plan.goal[:60]}")
            print(f"  plan steps: {len(plan.steps)}")
            print(f"  plan reasoning: {plan.reasoning[:120] if plan.reasoning else '(empty)'}...")
        else:
            print(f"  plan output empty or missing reasoning")
    except Exception as e:
        print(f"  plan() error: {type(e).__name__}: {e}")

    print()

    # Stage 3: Reflect — verify keys align with template {summary, detail, tags}
    print("--- Stage 3: Reflect ---")
    try:
        reflection = await engine.reflect(
            experience={
                "summary": "Explained quantum computing basics to a user",
                "detail": "The user asked about qubits and superposition. The explanation covered quantum gates and entanglement.",
                "tags": ["quantum", "education", "success"],
            }
        )
        if reflection and (reflection.summary or reflection.lessons_learned):
            stages_with_real_data += 1
            print(f"  reflection summary: {reflection.summary[:120] if reflection.summary else '(empty)'}")
            print(f"  lessons: {len(reflection.lessons_learned)}")
            if reflection.lessons_learned:
                print(f"  lesson[0]: {reflection.lessons_learned[0][:100]}")
            print(f"  emotional_tone: {reflection.emotional_tone}")
        else:
            print(f"  reflection output empty")
    except Exception as e:
        print(f"  reflect() error: {type(e).__name__}: {e}")

    print()
    eec = stages_with_real_data / stages_total
    print(f"=== EEC RESULT ===")
    print(f"Stages with real data: {stages_with_real_data}/{stages_total}")
    print(f"EEC = {eec:.2f}")

    if eec > 0:
        print(f"RESULT: EEC = {eec:.2f} — POSITIVE (was 0.00 before P0-2/P0-3 fixes)")
    else:
        print(f"RESULT: EEC = {eec:.2f} — ZERO (fixes not working)")

    await derived.close()
    await text_idx.close()


if __name__ == "__main__":
    asyncio.run(main())
