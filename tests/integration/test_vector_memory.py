"""Integration tests for vector memory — proving embeddings actually flow.

These tests exist because vector memory previously failed *silently*: entries
were persisted, full-text search worked, and nothing logged an error — but
``EpisodicEntry.embedding`` was never populated, so the FAISS index stayed
empty forever and semantic recall degraded to keyword matching without anyone
noticing.

A passing "memory works" test is therefore not enough. These tests assert on
the vector index size and on embedding-driven ranking specifically.
"""

from __future__ import annotations

import pytest

from myharness.memory.embedder import Embedder, NullEmbedder
from myharness.schema.memory import EpisodicEntry, MemoryCategory, MemoryQuery

pytestmark = pytest.mark.asyncio

DIM = 64


class FakeEmbeddingPort:
    """Deterministic embedding port — no network, reproducible similarity.

    Produces a bag-of-words vector so that texts sharing vocabulary land close
    together in L2 space. This makes semantic ranking assertions meaningful
    without depending on a real embedding model.
    """

    def __init__(self, dimension: int = DIM) -> None:
        self.dimension = dimension
        self.call_count = 0
        self.embedded_texts: list[str] = []

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        texts = [text] if isinstance(text, str) else list(text)
        self.call_count += 1
        self.embedded_texts.extend(texts)

        vectors: list[list[float]] = []
        for item in texts:
            vector = [0.0] * self.dimension
            for token in item.lower().split():
                vector[hash(token) % self.dimension] += 1.0
            vectors.append(vector)
        return vectors


class BrokenEmbeddingPort:
    """An embedding port that always fails — models a provider outage."""

    def __init__(self) -> None:
        self.call_count = 0

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        self.call_count += 1
        raise RuntimeError("embedding backend unreachable")


@pytest.fixture
def fake_port() -> FakeEmbeddingPort:
    return FakeEmbeddingPort()


@pytest.fixture
def vector_memory(
    identity_store, episodic_store, semantic_store, relationship_store, fake_port
):
    """A MemoryManager wired to a deterministic, offline embedding port."""
    from myharness.memory.manager import MemoryManager

    return MemoryManager(
        identity=identity_store,
        episodic=episodic_store,
        semantic=semantic_store,
        relationship=relationship_store,
        embedder=Embedder(port=fake_port, dimension=DIM),
    )


class TestEmbeddingGeneration:
    """The write path must vectorize entries without callers doing it."""

    async def test_record_episode_populates_embedding(
        self, vector_memory, fake_port
    ):
        entry = EpisodicEntry(
            category="conversation",
            summary="User asked about the deployment pipeline",
            detail="They wanted to know how releases reach production.",
        )
        assert entry.embedding is None, "precondition: caller supplies no vector"

        await vector_memory.record_episode(entry)

        assert fake_port.call_count == 1, "memory must embed on write"
        # Summary AND detail are embedded — recall should work from either.
        embedded = fake_port.embedded_texts[0]
        assert "deployment pipeline" in embedded
        assert "releases reach production" in embedded

    async def test_recorded_entry_reaches_the_vector_index(
        self, vector_memory, episodic_store
    ):
        """The regression that started this: index stayed empty on every write."""
        index = episodic_store._vector_idx
        assert index.size == 0

        await vector_memory.record_episode(
            EpisodicEntry(category="conversation", summary="First memory")
        )
        await vector_memory.record_episode(
            EpisodicEntry(category="conversation", summary="Second memory")
        )

        assert index.size == 2, (
            "entries were persisted but never indexed — vector recall is dead"
        )

    async def test_caller_supplied_embedding_is_respected(
        self, vector_memory, fake_port
    ):
        """A precomputed vector must not trigger a redundant embedding call."""
        entry = EpisodicEntry(
            category="conversation",
            summary="Already vectorized",
            embedding=[0.5] * DIM,
        )

        await vector_memory.record_episode(entry)

        assert fake_port.call_count == 0


class TestVectorSearch:
    """The read path must vectorize the query, not just keyword-match."""

    async def test_search_embeds_the_query(self, vector_memory, fake_port):
        await vector_memory.record_episode(
            EpisodicEntry(category="conversation", summary="Kubernetes rollout notes")
        )
        calls_after_write = fake_port.call_count

        await vector_memory.search(
            MemoryQuery(
                query_text="kubernetes rollout",
                categories=[MemoryCategory.EPISODIC],
                top_k=5,
            )
        )

        assert fake_port.call_count > calls_after_write, (
            "query was not embedded — search silently fell back to keywords"
        )

    async def test_semantically_similar_entry_is_retrieved(self, vector_memory):
        await vector_memory.record_episode(
            EpisodicEntry(
                category="conversation",
                summary="database migration strategy for postgres",
            )
        )
        await vector_memory.record_episode(
            EpisodicEntry(
                category="conversation",
                summary="favourite pizza toppings discussion",
            )
        )

        results = await vector_memory.search(
            MemoryQuery(
                query_text="database migration strategy for postgres",
                categories=[MemoryCategory.EPISODIC],
                top_k=5,
            )
        )

        assert results, "vector search returned nothing"
        assert "database migration" in results[0].content.lower(), (
            f"wrong entry ranked first: {results[0].content!r}"
        )

    async def test_precomputed_query_embedding_is_not_overwritten(
        self, vector_memory, fake_port
    ):
        await vector_memory.record_episode(
            EpisodicEntry(category="conversation", summary="anything")
        )
        calls_after_write = fake_port.call_count

        await vector_memory.search(
            MemoryQuery(
                query_text="anything",
                query_embedding=[0.1] * DIM,
                categories=[MemoryCategory.EPISODIC],
            )
        )

        assert fake_port.call_count == calls_after_write


class TestGracefulDegradation:
    """Embedding failures must degrade recall, never lose data."""

    async def test_write_succeeds_when_embedding_backend_fails(
        self,
        identity_store,
        episodic_store,
        semantic_store,
        relationship_store,
    ):
        from myharness.memory.manager import MemoryManager

        broken = BrokenEmbeddingPort()
        memory = MemoryManager(
            identity=identity_store,
            episodic=episodic_store,
            semantic=semantic_store,
            relationship=relationship_store,
            embedder=Embedder(port=broken, dimension=DIM),
        )

        entry_id = await memory.record_episode(
            EpisodicEntry(category="conversation", summary="Survives the outage")
        )

        assert entry_id, "a failed embedding must not abort the write"
        recent = await memory.get_recent_episodes(limit=10)
        assert any(e.summary == "Survives the outage" for e in recent)

    async def test_broken_backend_is_called_only_once(
        self,
        identity_store,
        episodic_store,
        semantic_store,
        relationship_store,
    ):
        """After the first failure the embedder must stop retrying.

        Otherwise every memory write pays a full network timeout during an
        outage, converting a degraded feature into a latency incident.
        """
        from myharness.memory.manager import MemoryManager

        broken = BrokenEmbeddingPort()
        memory = MemoryManager(
            identity=identity_store,
            episodic=episodic_store,
            semantic=semantic_store,
            relationship=relationship_store,
            embedder=Embedder(port=broken, dimension=DIM),
        )

        for i in range(5):
            await memory.record_episode(
                EpisodicEntry(category="conversation", summary=f"entry {i}")
            )

        assert broken.call_count == 1

    async def test_dimension_mismatch_is_rejected(
        self,
        identity_store,
        episodic_store,
        semantic_store,
        relationship_store,
    ):
        """A wrong-sized vector must be dropped, not handed to FAISS."""
        from myharness.memory.manager import MemoryManager

        memory = MemoryManager(
            identity=identity_store,
            episodic=episodic_store,
            semantic=semantic_store,
            relationship=relationship_store,
            # Port yields DIM-sized vectors; the embedder expects DIM * 2.
            embedder=Embedder(port=FakeEmbeddingPort(DIM), dimension=DIM * 2),
        )

        entry = EpisodicEntry(category="conversation", summary="mismatched dims")
        await memory.record_episode(entry)

        recent = await memory.get_recent_episodes(limit=10)
        stored = next(e for e in recent if e.summary == "mismatched dims")
        assert stored.embedding is None
        assert episodic_store._vector_idx.size == 0

    async def test_null_embedder_keeps_memory_functional(
        self, identity_store, episodic_store, semantic_store, relationship_store
    ):
        """With embeddings disabled, memory still records and recalls by text."""
        from myharness.memory.manager import MemoryManager

        memory = MemoryManager(
            identity=identity_store,
            episodic=episodic_store,
            semantic=semantic_store,
            relationship=relationship_store,
            embedder=NullEmbedder(dimension=DIM),
        )

        await memory.record_episode(
            EpisodicEntry(category="conversation", summary="text only recall")
        )

        recent = await memory.get_recent_episodes(limit=10)
        assert any(e.summary == "text only recall" for e in recent)
        assert episodic_store._vector_idx.size == 0


class TestEmbedderUnit:
    """Direct unit coverage of the Embedder's contract."""

    async def test_blank_text_is_not_embedded(self, fake_port):
        embedder = Embedder(port=fake_port, dimension=DIM)
        assert await embedder.embed_one("   ") is None
        assert fake_port.call_count == 0

    async def test_reset_clears_degraded_state(self):
        broken = BrokenEmbeddingPort()
        embedder = Embedder(port=broken, dimension=DIM)

        assert await embedder.embed_one("hello") is None
        assert embedder.enabled is False

        embedder.reset()
        assert embedder.enabled is True
        assert await embedder.embed_one("hello") is None
        assert broken.call_count == 2

    async def test_null_embedder_is_never_enabled(self):
        assert NullEmbedder(dimension=DIM).enabled is False
