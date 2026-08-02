"""FAISS-based vector similarity search index.

Stores embeddings for episodic and semantic memory entries.
Fully rebuildable from SourceOfTruth — per P9, this is derived data.
"""

from __future__ import annotations

import pickle
from pathlib import Path
from typing import TYPE_CHECKING, Any

import numpy as np

from myharness.core.config import get_settings
from myharness.core.logging import get_logger
from myharness.memory.indexing.base import BaseIndexer

if TYPE_CHECKING:
    from myharness.memory.storage.source import SourceOfTruth

logger = get_logger(__name__)


class VectorIndex(BaseIndexer):
    """FAISS-based vector index for semantic similarity search.

    Uses IndexFlatL2 (L2 distance) by default. Configurable to use
    IndexIVFFlat for larger datasets.

    The index stores (entry_id, metadata) mappings alongside FAISS vectors.
    The index file (.faiss) and metadata file (.meta) are saved together.
    """

    def __init__(
        self,
        dimension: int | None = None,
        index_path: Path | None = None,
    ) -> None:
        settings = get_settings()
        self._dimension = dimension or settings.embedding_dimension
        self._index_path = index_path or (
            settings.memory_index_dir / "vector.faiss"
        )
        self._meta_path = self._index_path.with_suffix(".meta")

        self._index = self._create_index()
        self._id_map: dict[int, str] = {}  # FAISS internal ID → entry_id
        self._metadata: dict[str, dict[str, Any]] = {}  # entry_id → metadata
        self._next_id = 0

    def _create_index(self):
        """Create a FAISS index. Uses FlatL2 for reliability."""
        try:
            import faiss
            return faiss.IndexFlatL2(self._dimension)
        except ImportError:
            raise ImportError(
                "faiss-cpu is required for VectorIndex. Install with: pip install faiss-cpu"
            )

    # ── Core Operations ─────────────────────────────────────────────────

    async def add(
        self, entry_id: str, embedding: np.ndarray, metadata: dict[str, Any] | None = None
    ) -> None:
        """Add an embedding to the index.

        Args:
            entry_id: The memory entry's unique ID.
            embedding: NumPy array of shape (dimension,) or (1, dimension).
            metadata: Optional metadata to store alongside.
        """
        if embedding.ndim == 1:
            embedding = embedding.reshape(1, -1)

        if embedding.shape[1] != self._dimension:
            raise ValueError(
                f"Embedding dimension {embedding.shape[1]} != index dimension {self._dimension}"
            )

        embedding = embedding.astype(np.float32)
        self._index.add(embedding)
        internal_id = self._next_id
        self._id_map[internal_id] = entry_id
        self._metadata[entry_id] = metadata or {}
        self._next_id += 1

    async def search(
        self, query_embedding: np.ndarray, k: int = 10
    ) -> list[tuple[str, float, dict[str, Any]]]:
        """Search for the k nearest neighbors.

        Args:
            query_embedding: NumPy array of shape (dimension,).
            k: Number of results to return.

        Returns:
            List of (entry_id, distance, metadata) tuples sorted by distance.
        """
        if self._index.ntotal == 0:
            return []

        if query_embedding.ndim == 1:
            query_embedding = query_embedding.reshape(1, -1)

        query_embedding = query_embedding.astype(np.float32)
        k = min(k, self._index.ntotal)

        distances, indices = self._index.search(query_embedding, k)

        results: list[tuple[str, float, dict[str, Any]]] = []
        for dist, idx in zip(distances[0], indices[0]):
            if idx == -1:
                continue
            entry_id = self._id_map.get(int(idx))
            if entry_id is None:
                continue
            # Convert L2 distance to similarity score [0,1]
            score = 1.0 / (1.0 + float(dist))
            meta = self._metadata.get(entry_id, {})
            results.append((entry_id, score, meta))

        return results

    async def delete(self, entry_id: str) -> None:
        """Remove an entry from the index.

        Note: FAISS IndexFlatL2 does not support deletion natively.
        We mark it as deleted in metadata; a full rebuild clears it.
        """
        if entry_id in self._metadata:
            self._metadata.pop(entry_id, None)
            logger.debug("VectorIndex: marked entry for deletion", entry_id=entry_id)

    async def clear(self) -> None:
        """Remove all entries from the index."""
        self._index = self._create_index()
        self._id_map.clear()
        self._metadata.clear()
        self._next_id = 0
        logger.info("VectorIndex: cleared")

    # ── Persistence ─────────────────────────────────────────────────────

    async def save(self) -> None:
        """Save the FAISS index and metadata to disk."""
        import faiss

        self._index_path.parent.mkdir(parents=True, exist_ok=True)

        # Save FAISS index
        faiss.write_index(self._index, str(self._index_path))

        # Save metadata
        meta_data = {
            "id_map": self._id_map,
            "metadata": self._metadata,
            "next_id": self._next_id,
            "dimension": self._dimension,
        }
        with open(self._meta_path, "wb") as f:
            pickle.dump(meta_data, f)

        logger.info(
            "VectorIndex: saved",
            path=str(self._index_path),
            entries=self._index.ntotal,
        )

    async def load(self) -> bool:
        """Load the FAISS index and metadata from disk.

        Returns:
            True if loaded successfully, False if files don't exist.
        """
        import faiss

        if not self._index_path.exists() or not self._meta_path.exists():
            return False

        try:
            self._index = faiss.read_index(str(self._index_path))
            with open(self._meta_path, "rb") as f:
                meta_data = pickle.load(f)
            self._id_map = meta_data["id_map"]
            self._metadata = meta_data["metadata"]
            self._next_id = meta_data["next_id"]
            logger.info(
                "VectorIndex: loaded",
                path=str(self._index_path),
                entries=self._index.ntotal,
            )
            return True
        except Exception as exc:
            logger.error("VectorIndex: load failed", error=str(exc))
            self._index = self._create_index()
            return False

    # ── Rebuild ─────────────────────────────────────────────────────────

    async def rebuild_from_source(self, source: SourceOfTruth) -> int:
        """Rebuild the vector index from SourceOfTruth data.

        Reads all episodic and semantic entries that have embeddings
        from the canonical JSONL files.

        Args:
            source: The SourceOfTruth instance.

        Returns:
            Number of entries indexed.
        """
        await self.clear()
        count = 0

        # Index episodic entries with embeddings
        async for entry in source.iterate_all("episodic"):
            embedding_data = entry.get("embedding")
            if embedding_data and isinstance(embedding_data, list) and len(embedding_data) > 0:
                emb = np.array(embedding_data, dtype=np.float32)
                await self.add(
                    entry.get("entry_id", ""),
                    emb,
                    {
                        "store": "episodic",
                        "summary": entry.get("summary", ""),
                        "category": entry.get("category", ""),
                        "importance": entry.get("importance", 0.5),
                    },
                )
                count += 1

        # Index semantic entries with embeddings
        async for entry in source.iterate_all("semantic"):
            embedding_data = entry.get("embedding")
            if embedding_data and isinstance(embedding_data, list) and len(embedding_data) > 0:
                emb = np.array(embedding_data, dtype=np.float32)
                await self.add(
                    entry.get("entry_id", ""),
                    emb,
                    {
                        "store": "semantic",
                        "entity": entry.get("entity", ""),
                        "attribute": entry.get("attribute", ""),
                        "confidence": entry.get("confidence", 1.0),
                    },
                )
                count += 1

        logger.info("VectorIndex: rebuilt from source", entries=count)
        return count

    # ── Properties ──────────────────────────────────────────────────────

    @property
    def size(self) -> int:
        """Number of entries in the index."""
        return self._index.ntotal

    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        return self._dimension
