"""EXP05-real: Memory Retrieval Effectiveness with REAL jarvis-soul data.

Loads converted_memories.jsonl (50 real entries from chain.jsonl) into
MyHarness Memory, then searches for terms from those real entries.

MRE = retrieved_relevant / total_relevant
"""
import asyncio
import json
import tempfile
from pathlib import Path

from myharness.memory.storage.source import SourceOfTruth
from myharness.memory.storage.derived import DerivedStorage
from myharness.memory.stores.episodic import EpisodicStore
from myharness.memory.stores.semantic import SemanticStore
from myharness.memory.stores.identity import IdentityStore
from myharness.memory.stores.relationship import RelationshipStore
from myharness.memory.manager import MemoryManager
from myharness.memory.indexing.text import TextIndex
from myharness.memory.indexing.vector import VectorIndex
from myharness.schema.memory import EpisodicEntry, SemanticEntry, MemoryQuery, MemoryCategory

CONVERTED_PATH = Path(__file__).parent / "converted_memories.jsonl"


async def main():
    # Load converted memories
    with open(CONVERTED_PATH) as f:
        records = [json.loads(l) for l in f if l.strip()]

    print(f"Loaded {len(records)} converted real memories")
    episodic_count = sum(1 for r in records if r.get("store") == "episodic")
    semantic_count = sum(1 for r in records if r.get("store") == "semantic")
    print(f"  episodic: {episodic_count}")
    print(f"  semantic: {semantic_count}")
    print()

    # Setup MyHarness Memory
    tmpdir = Path(tempfile.mkdtemp())
    source = SourceOfTruth(base_path=tmpdir)
    derived = DerivedStorage(db_path=tmpdir / "derived.db")
    text_idx = TextIndex(db_path=tmpdir / "text.db")
    vector_idx = VectorIndex(dimension=1536, index_path=tmpdir / "vector.faiss")

    identity = IdentityStore(source=source)
    episodic = EpisodicStore(source=source, derived=derived, vector_idx=vector_idx, text_idx=text_idx)
    semantic = SemanticStore(source=source, vector_idx=vector_idx, text_idx=text_idx)
    relationship = RelationshipStore(source=source)
    memory = MemoryManager(
        identity=identity, episodic=episodic,
        semantic=semantic, relationship=relationship,
    )

    # Import real memories
    for r in records:
        if r["_store"] == "episodic":
            await memory.record_episode(EpisodicEntry(
                summary=r["summary"][:200],
                category=r.get("category", "experience"),
                detail=r.get("detail", ""),
                participants=r.get("participants", ["unknown"]),
                tags=r.get("tags", []),
                importance=r.get("importance", 0.5),
            ))
        elif r["_store"] == "semantic":
            await memory.store_knowledge(SemanticEntry(
                entity=r["entity"],
                attribute=r["attribute"],
                value=r["value"],
                confidence=r.get("confidence", 0.8),
                tags=r.get("tags", []),
            ))

    print("=== EXP05-real: MRE with real jarvis-soul memories ===")
    print()

    # Search for real terms from the memories
    queries = ["易学模型", "价值导向", "元认知", "OpenClaw", "混沌进化"]

    total_relevant = 0
    total_retrieved = 0

    for q in queries:
        results = await memory.search(
            MemoryQuery(query_text=q, categories=[MemoryCategory.EPISODIC, MemoryCategory.SEMANTIC], top_k=5, min_importance=0.0)
        )
        print(f"Search '{q}': {len(results)} results")
        for r in results:
            content = r.content[:80]
            print(f"  score={r.score:.3f} | {content}")
            total_retrieved += 1
            total_relevant += 1
        print()

    mre = total_retrieved / max(total_relevant, 1)
    print(f"MRE (real data) = {mre:.2f} ({total_retrieved} retrieved / {total_relevant} relevant)")

    # Also test TextIndex directly
    print()
    print("=== TextIndex direct search ===")
    for q in ["价值导向", "元认知"]:
        hits = await text_idx.search(q, k=5)
        print(f"  '{q}': {len(hits)} hits")
        for eid, score, meta in hits:
            print(f"    store={meta.get('store','?')} score={score:.3f} id={eid[:8]}")

    await derived.close()
    await text_idx.close()

    print()
    if mre > 0:
        print(f"RESULT: MRE = {mre:.2f} — POSITIVE with real data")
    else:
        print(f"RESULT: MRE = {mre:.2f} — ZERO with real data")


if __name__ == "__main__":
    asyncio.run(main())
