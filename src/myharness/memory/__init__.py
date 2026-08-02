"""Memory System — the agent's persistent identity and experience store.

Per P3 (Identity Externalization) and P9 (Source/Derived Data Separation):
- SourceOfTruth: append-only JSON/JSONL — canonical, immutable, human-readable
- DerivedStorage: SQLite metadata — fast query, fully rebuildable
- VectorIndex (FAISS) and TextIndex (FTS5): search indexes — fully rebuildable
"""

from myharness.memory.indexing.text import TextIndex
from myharness.memory.indexing.vector import VectorIndex
from myharness.memory.interface import MemorySystem
from myharness.memory.manager import MemoryManager
from myharness.memory.serializer import MemorySerializer
from myharness.memory.storage.derived import DerivedStorage
from myharness.memory.storage.source import SourceOfTruth
from myharness.memory.stores.episodic import EpisodicStore
from myharness.memory.stores.identity import IdentityStore
from myharness.memory.stores.relationship import RelationshipStore
from myharness.memory.stores.semantic import SemanticStore

__all__ = [
    "MemorySystem",
    "MemoryManager",
    "MemorySerializer",
    "SourceOfTruth",
    "DerivedStorage",
    "VectorIndex",
    "TextIndex",
    "IdentityStore",
    "EpisodicStore",
    "SemanticStore",
    "RelationshipStore",
]
