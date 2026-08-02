"""Dependency Injection container — wires all MyHarness components together.

The DI container builds the complete object graph, respecting the strict
module dependency order required by the four-power-separation architecture.

Wiring order (bottom-up):
1. Configuration — Settings (no dependencies)
2. Storage — SourceOfTruth, DerivedStorage, VectorIndex, TextIndex
3. Memory Stores — IdentityStore, EpisodicStore, SemanticStore, RelationshipStore
4. Memory Manager — depends on all stores
5. LLM Provider — depends on config
6. Context Builder — depends on memory
7. LLM Engine — depends on provider + context builder
8. Skill Store — depends on storage
9. Event Bus — no dependencies
10. Router — depends on bus
11. Drivers — depends on config
12. Capability Registry — no dependencies
13. Scheduler, Monitor — no dependencies
14. Harness Supervisor — depends on everything
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from lagom import Container
    from myharness.core.config import Settings

logger = structlog.get_logger(__name__)


def _build_embedder(settings: "Settings"):
    """Construct the Embedder used by the Memory System.

    Per P8, the embedding backend is selected independently of the cognitive
    backend (``settings.embedding_provider`` vs ``default_llm_provider``),
    because Anthropic and DeepSeek expose no embeddings API — pairing Claude
    for reasoning with OpenAI for embeddings is a normal configuration.

    A missing or misconfigured embedding provider must NOT abort startup: the
    agent stays fully functional on full-text memory search. It degrades a
    capability instead of refusing to boot.
    """
    from myharness.memory.embedder import Embedder, NullEmbedder

    provider_name = getattr(settings, "embedding_provider", None) or (
        settings.default_llm_provider
    )

    if provider_name.lower() in {"none", "off", "disabled"}:
        logger.info("embeddings_disabled_text_only_memory")
        return NullEmbedder(dimension=settings.embedding_dimension)

    try:
        from myharness.llm.providers import create_provider

        port = create_provider(
            provider_name,
            settings,
            embedding_model=getattr(settings, "embedding_model", None),
        )
    except Exception as exc:
        logger.warning(
            "embedding_provider_unavailable_using_text_only_memory",
            provider=provider_name,
            error=str(exc),
        )
        return NullEmbedder(dimension=settings.embedding_dimension)

    logger.info(
        "embedder_configured",
        provider=provider_name,
        dimension=settings.embedding_dimension,
    )
    return Embedder(port=port, dimension=settings.embedding_dimension)


def build_container(settings: "Settings") -> "Container":
    """Build the complete dependency injection container.

    Every service is registered with an explicit ``lagom.Singleton`` wrapper.
    This is NOT lagom's default: a bare ``container[X] = lambda c: X(...)``
    definition re-runs the factory on *every* resolution. For MyHarness that
    is catastrophic rather than merely wasteful — nearly every component is
    stateful, so per-resolution construction would give each caller its own
    FAISS index, its own SQLite connections and its own EventBus, silently
    discarding all in-memory state and leaking a connection per request.

    The wiring is done in strict dependency order. Services that depend
    on other services are registered after their dependencies.

    Args:
        settings: Application settings loaded from environment/.env.

    Returns:
        A fully configured lagom Container ready for resolution.
    """
    from lagom import Container, Singleton

    container = Container()

    # ── Level 0: Settings ──────────────────────────────────────────────
    from myharness.core.config import Settings as SettingsCls

    container[SettingsCls] = settings

    # ── Level 1: Storage (no dependencies) ─────────────────────────────
    from myharness.memory.storage.source import SourceOfTruth
    from myharness.memory.storage.derived import DerivedStorage
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.indexing.text import TextIndex

    container[SourceOfTruth] = Singleton(lambda c: SourceOfTruth(settings.memory_source_dir))
    container[DerivedStorage] = Singleton(lambda c: DerivedStorage(
        settings.memory_derived_dir / "metadata.db"
    ))
    container[VectorIndex] = Singleton(lambda c: VectorIndex(
        dimension=settings.embedding_dimension,
        index_path=settings.memory_index_dir / "vectors.faiss",
    ))
    container[TextIndex] = Singleton(lambda c: TextIndex(
        settings.memory_derived_dir / "fts.db"
    ))

    # ── Level 2: Memory Stores (depend on storage) ─────────────────────
    from myharness.memory.stores.identity import IdentityStore
    from myharness.memory.stores.episodic import EpisodicStore
    from myharness.memory.stores.semantic import SemanticStore
    from myharness.memory.stores.relationship import RelationshipStore

    container[IdentityStore] = Singleton(lambda c: IdentityStore(c[SourceOfTruth]))
    container[EpisodicStore] = Singleton(lambda c: EpisodicStore(
        c[SourceOfTruth], c[DerivedStorage], c[VectorIndex], c[TextIndex]
    ))
    container[SemanticStore] = Singleton(lambda c: SemanticStore(
        c[SourceOfTruth], c[VectorIndex], c[TextIndex]
    ))
    container[RelationshipStore] = Singleton(lambda c: RelationshipStore(c[SourceOfTruth]))

    # ── Level 3: Embedder (bridges Memory to compute via a narrow port) ─
    from myharness.memory.embedder import Embedder

    container[Embedder] = Singleton(lambda c: _build_embedder(settings))

    # ── Level 3b: Memory Manager (depends on all stores + embedder) ────
    from myharness.memory.manager import MemoryManager
    from myharness.memory.interface import MemorySystem

    container[MemoryManager] = Singleton(lambda c: MemoryManager(
        identity=c[IdentityStore],
        episodic=c[EpisodicStore],
        semantic=c[SemanticStore],
        relationship=c[RelationshipStore],
        embedder=c[Embedder],
    ))
    # Register MemoryManager under the MemorySystem interface for polymorphic resolution
    container[MemorySystem] = Singleton(lambda c: c[MemoryManager])

    # ── Level 4: LLM Provider (depends on config) ─────────────────────
    from myharness.llm.providers import create_provider
    from myharness.llm.interfaces import LLMProvider

    container[LLMProvider] = Singleton(lambda c: create_provider(
        settings.default_llm_provider, settings
    ))

    # ── Level 5: Context Builder (depends on memory) ──────────────────
    from myharness.llm.context import ContextBuilder

    container[ContextBuilder] = Singleton(lambda c: ContextBuilder(c[MemorySystem]))

    # ── Level 6: LLM Engine (depends on provider + context builder) ───
    from myharness.llm.engine import LLMEngine

    container[LLMEngine] = Singleton(lambda c: LLMEngine(
        provider=c[LLMProvider], context_builder=c[ContextBuilder]
    ))

    # ── Level 7: Skill Store & Registry (depend on storage) ───────────
    from myharness.skill.store import SkillStore
    from myharness.skill.registry import SkillRegistry

    container[SkillStore] = Singleton(lambda c: SkillStore(settings.skills_dir))
    container[SkillRegistry] = Singleton(lambda c: SkillRegistry(c[SkillStore]))

    # ── Level 8: Event Bus & Router (no dependencies) ─────────────────
    from myharness.bus.dispatcher import EventBus
    from myharness.bus.router import Router

    container[EventBus] = EventBus()
    container[Router] = Singleton(lambda c: Router(c[EventBus]))

    # ── Level 9: Driver Manager (no dependencies) ─────────────────────
    from myharness.driver.protocol import DriverManager

    container[DriverManager] = DriverManager()

    # ── Level 10: Harness Components (no dependencies) ────────────────
    from myharness.harness.registry import CapabilityRegistry
    from myharness.harness.scheduler import ResourceScheduler
    from myharness.harness.monitor import RuntimeMonitor

    container[CapabilityRegistry] = Singleton(lambda c: CapabilityRegistry())
    container[ResourceScheduler] = Singleton(lambda c: ResourceScheduler())
    container[RuntimeMonitor] = RuntimeMonitor()

    # ── Level 11: Runtime Layer (event loop, state, interrupts) ───────
    from myharness.runtime.interrupt import InterruptHandler
    from myharness.runtime.loop import EventLoop
    from myharness.runtime.state import RuntimeState

    container[RuntimeState] = Singleton(lambda c: RuntimeState())
    container[InterruptHandler] = Singleton(lambda c: InterruptHandler(
        llm_engine=c[LLMEngine],
        skill_registry=c[SkillRegistry],
    ))
    container[EventLoop] = Singleton(lambda c: EventLoop(
        event_bus=c[EventBus],
        router=c[Router],
        state=c[RuntimeState],
        interrupt_handler=c[InterruptHandler],
    ))

    # ── Level 12: Harness Supervisor (depends on everything) ──────────
    from myharness.harness.supervisor import HarnessSupervisor

    container[HarnessSupervisor] = Singleton(lambda c: HarnessSupervisor(
        event_bus=c[EventBus],
        router=c[Router],
        memory=c[MemorySystem],
        llm_engine=c[LLMEngine],
        skill_store=c[SkillStore],
        capability_registry=c[CapabilityRegistry],
        driver_manager=c[DriverManager],
        scheduler=c[ResourceScheduler],
        monitor=c[RuntimeMonitor],
        cognitive_loop=c[EventLoop],
    ))

    logger.info(
        "di_container_built",
        provider=settings.default_llm_provider,
        embedding_dimension=settings.embedding_dimension,
    )

    return container
