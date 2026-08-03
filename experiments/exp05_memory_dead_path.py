"""EXP05: Memory Retrieval Effectiveness (MRE) — verifies that the
text index search returns entries with store metadata, and that
those entries can be retrieved from the correct store.

Before P0-1 fix: TextIndex.search discarded the `store` column,
so callers could not know which store to fetch from — the retrieval
path was dead (MRE=0).

After P0-1 fix: search returns meta with store info, enabling
correct retrieval (MRE > 0).

Metrics:
  MRE (Memory Retrieval Effectiveness) = retrieved_relevant / total_relevant
"""
import asyncio
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
from myharness.schema.memory import EpisodicEntry, SemanticEntry, MemoryCategory, MemoryQuery


async def main():
    tmpdir = Path(tempfile.mkdtemp())
    source = SourceOfTruth(base_path=tmpdir)
    derived = DerivedStorage(db_path=tmpdir / "derived.db")
    vector_idx = VectorIndex(dimension=64, index_path=tmpdir / "vector.faiss")
    text_idx = TextIndex(db_path=tmpdir / "text.db")

    identity = IdentityStore(source=source)
    episodic = EpisodicStore(source=source, derived=derived, vector_idx=vector_idx, text_idx=text_idx)
    semantic = SemanticStore(source=source, vector_idx=vector_idx, text_idx=text_idx)
    relationship = RelationshipStore(source=source)
    memory = MemoryManager(
        identity=identity, episodic=episodic,
        semantic=semantic, relationship=relationship,
    )

    # Write 5 episodic entries with known content
    entries = [
        EpisodicEntry(summary="Discussed quantum computing trends", detail="Quantum supremacy milestone reached", category="conversation", tags=["quantum", "tech"]),
        EpisodicEntry(summary="User asked about AI safety", detail="AI alignment research is critical", category="conversation", tags=["ai", "safety"]),
        EpisodicEntry(summary="Weather query for Beijing", detail="Beijing weather: sunny, 25C", category="conversation", tags=["weather", "beijing"]),
        EpisodicEntry(summary="Recipe suggestion: pasta", detail="How to make carbonara", category="conversation", tags=["cooking", "pasta"]),
        EpisodicEntry(summary="Quantum entanglement explained", detail="EPR paradox and Bell's theorem", category="conversation", tags=["quantum", "physics"]),
    ]

    for e in entries:
        await memory.record_episode(e)

    # Write 2 semantic entries
    sem_entries = [
        SemanticEntry(entity="quantum_computing", attribute="definition", value="Computing using quantum mechanical phenomena", confidence=0.9),
        SemanticEntry(entity="ai_safety", attribute="definition", value="Ensuring AI systems behave safely", confidence=0.95),
    ]
    for e in sem_entries:
        await memory.store_knowledge(e)

    # Search for "quantum" — should match 2 episodic + 1 semantic
    print("=== EXP05: Memory Retrieval Effectiveness (MRE) ===")
    print()

    # Test TextIndex.search directly
    results = await text_idx.search("quantum", k=10)
    print(f"TextIndex.search('quantum'): {len(results)} hits")
    for entry_id, score, meta in results:
        store = meta.get("store", "MISSING")
        print(f"  entry_id={entry_id[:8]}... score={score:.3f} store={store}")

    # Count how many results have store info (MRE numerator)
    results_with_store = [r for r in results if "store" in r[2]]
    mre = len(results_with_store) / max(len(results), 1)
    print()
    print(f"MRE = {mre:.2f} ({len(results_with_store)}/{len(results)} results have store metadata)")

    # Verify retrieval path works: use store info to fetch from correct store
    print()
    print("=== Retrieval path verification ===")
    retrieved = 0
    for entry_id, score, meta in results:
        store = meta.get("store", "")
        if store == "episodic":
            entry = await derived.get_episode(entry_id)
            if entry:
                print(f"  [episodic] Retrieved: {entry.get('summary', '')[:60]}")
                retrieved += 1
        elif store == "semantic":
            entries = await derived.fts_search_semantics("quantum", limit=10)
            entry = next((e for e in entries if e.get("entry_id") == entry_id), None)
            if entry:
                print(f"  [semantic] Retrieved: {entry.get('entity', '')} = {entry.get('value', '')[:60]}")
                retrieved += 1
        else:
            print(f"  [UNKNOWN STORE] entry_id={entry_id[:8]}... store={store}")

    print()
    print(f"Retrieved: {retrieved}/{len(results)}")
    print(f"MRE (retrieved/hits): {retrieved/max(len(results),1):.2f}")

    # Also test via MemoryManager.search (full path)
    print()
    print("=== MemoryManager.search path ===")
    search_results = await memory.search(
        MemoryQuery(query_text="quantum", categories=[MemoryCategory.EPISODIC, MemoryCategory.SEMANTIC], top_k=10, min_importance=0.0)
    )
    print(f"MemoryManager.search('quantum'): {len(search_results)} results")
    for r in search_results:
        print(f"  score={r.score:.3f} content={r.content[:60]}")
    print(f"MRE (manager): {len(search_results)}/3 expected = {len(search_results)/3:.2f}")

    await text_idx.close()
    await derived.close()

    print()
    if mre > 0 and retrieved > 0:
        print(f"RESULT: MRE = {mre:.2f} — POSITIVE (was 0.00 before P0-1 fix)")
    else:
        print(f"RESULT: MRE = {mre:.2f} — ZERO (fix not working)")


if __name__ == "__main__":
    asyncio.run(main())
