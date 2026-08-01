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


def build_container(settings: "Settings") -> "Container":
    """Build the complete dependency injection container.

    All services are registered as singletons (lagom default). The
    container can be used to resolve any service by its type.

    The wiring is done in strict dependency order. Services that depend
    on other services are registered after their dependencies.

    Args:
        settings: Application settings loaded from environment/.env.

    Returns:
        A fully configured lagom Container ready for resolution.
    """
    from lagom import Container

    container = Container()

    # ── Level 0: Settings ──────────────────────────────────────────────
    from myharness.core.config import Settings as SettingsCls

    container[SettingsCls] = settings

    # ── Level 1: Storage (no dependencies) ─────────────────────────────
    from myharness.memory.storage.source import SourceOfTruth
    from myharness.memory.storage.derived import DerivedStorage
    from myharness.memory.indexing.vector import VectorIndex
    from myharness.memory.indexing.text import TextIndex

    container[SourceOfTruth] = lambda c: SourceOfTruth(settings.memory_source_dir)
    container[DerivedStorage] = lambda c: DerivedStorage(
        settings.memory_derived_dir / "metadata.db"
    )
    container[VectorIndex] = lambda c: VectorIndex(
        dimension=settings.embedding_dimension,
        index_path=settings.memory_index_dir / "vectors.faiss",
    )
    container[TextIndex] = lambda c: TextIndex(
        settings.memory_derived_dir / "fts.db"
    )

    # ── Level 2: Memory Stores (depend on storage) ─────────────────────
    from myharness.memory.stores.identity import IdentityStore
    from myharness.memory.stores.episodic import EpisodicStore
    from myharness.memory.stores.semantic import SemanticStore
    from myharness.memory.stores.relationship import RelationshipStore

    container[IdentityStore] = lambda c: IdentityStore(c[SourceOfTruth])
    container[EpisodicStore] = lambda c: EpisodicStore(
        c[SourceOfTruth], c[DerivedStorage], c[VectorIndex], c[TextIndex]
    )
    container[SemanticStore] = lambda c: SemanticStore(
        c[SourceOfTruth], c[VectorIndex], c[TextIndex]
    )
    container[RelationshipStore] = lambda c: RelationshipStore(c[SourceOfTruth])

    # ── Level 3: Memory Manager (depends on all stores) ────────────────
    from myharness.memory.manager import MemoryManager
    from myharness.memory.interface import MemorySystem

    container[MemoryManager] = lambda c: MemoryManager(
        identity=c[IdentityStore],
        episodic=c[EpisodicStore],
        semantic=c[SemanticStore],
        relationship=c[RelationshipStore],
    )
    # Register MemoryManager under the MemorySystem interface for polymorphic resolution
    container[MemorySystem] = lambda c: c[MemoryManager]

    # ── Level 4: LLM Provider (depends on config) ─────────────────────
    from myharness.llm.providers import create_provider
    from myharness.llm.interfaces import LLMProvider

    container[LLMProvider] = lambda c: create_provider(
        settings.default_llm_provider, settings
    )

    # ── Level 5: Context Builder (depends on memory) ──────────────────
    from myharness.llm.context import ContextBuilder

    container[ContextBuilder] = lambda c: ContextBuilder(c[MemorySystem])

    # ── Level 6: LLM Engine (depends on provider + context builder) ───
    from myharness.llm.engine import LLMEngine

    container[LLMEngine] = lambda c: LLMEngine(
        provider=c[LLMProvider], context_builder=c[ContextBuilder]
    )

    # ── Level 7: Skill Store & Registry (depend on storage) ───────────
    from myharness.skill.store import SkillStore
    from myharness.skill.registry import SkillRegistry

    container[SkillStore] = lambda c: SkillStore(settings.skills_dir)
    container[SkillRegistry] = lambda c: SkillRegistry(c[SkillStore])

    # ── Level 8: Event Bus & Router (no dependencies) ─────────────────
    from myharness.bus.dispatcher import EventBus
    from myharness.bus.router import Router

    container[EventBus] = EventBus()
    container[Router] = lambda c: Router(c[EventBus])

    # ── Level 9: Driver Manager (no dependencies) ─────────────────────
    from myharness.driver.protocol import DriverManager

    container[DriverManager] = DriverManager()

    # ── Level 10: Harness Components (no dependencies) ────────────────
    from myharness.harness.registry import CapabilityRegistry
    from myharness.harness.scheduler import ResourceScheduler
    from myharness.harness.monitor import RuntimeMonitor

    container[CapabilityRegistry] = lambda c: CapabilityRegistry()
    container[ResourceScheduler] = lambda c: ResourceScheduler()
    container[RuntimeMonitor] = RuntimeMonitor()

    # ── Level 11: Harness Supervisor (depends on everything) ──────────
    from myharness.harness.supervisor import HarnessSupervisor

    container[HarnessSupervisor] = lambda c: HarnessSupervisor(
        event_bus=c[EventBus],
        router=c[Router],
        memory=c[MemorySystem],
        llm_engine=c[LLMEngine],
        skill_store=c[SkillStore],
        capability_registry=c[CapabilityRegistry],
        driver_manager=c[DriverManager],
        scheduler=c[ResourceScheduler],
        monitor=c[RuntimeMonitor],
    )

    logger.info(
        "di_container_built",
        provider=settings.default_llm_provider,
        embedding_dimension=settings.embedding_dimension,
    )

    return container
