"""FastAPI dependency injection layer.

Provides async dependency callables for FastAPI's Depends() system.
Each function resolves its service from the lagom DI container built
by build_container() in myharness.core.di.

The container is cached via lru_cache so it's built once per process.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TYPE_CHECKING

from myharness.core.config import get_settings

if TYPE_CHECKING:
    from lagom import Container
    from myharness.bus.dispatcher import EventBus
    from myharness.harness.supervisor import HarnessSupervisor
    from myharness.llm.engine import LLMEngine
    from myharness.memory.interface import MemorySystem
    from myharness.skill.store import SkillStore


@lru_cache(maxsize=1)
def get_container() -> "Container":
    """Build and cache the DI container.

    The container is built once per process and cached. This ensures
    all FastAPI dependency resolutions share the same service instances
    (singleton scope).

    Returns:
        The configured lagom Container instance.
    """
    settings = get_settings()
    # Defer import to avoid circular dependency at module level
    from myharness.core.di import build_container

    return build_container(settings)


async def get_supervisor() -> "HarnessSupervisor":
    """Resolve the HarnessSupervisor from the DI container.

    The supervisor is the central orchestrator. All cognitive operations
    flow through it.

    Returns:
        The singleton HarnessSupervisor instance.
    """
    container = get_container()
    from myharness.harness.supervisor import HarnessSupervisor

    return container.resolve(HarnessSupervisor)


async def get_memory() -> "MemorySystem":
    """Resolve the MemorySystem from the DI container.

    Returns:
        The singleton MemorySystem (MemoryManager) instance.
    """
    container = get_container()
    from myharness.memory.interface import MemorySystem

    return container.resolve(MemorySystem)


async def get_llm_engine() -> "LLMEngine":
    """Resolve the LLMEngine from the DI container.

    Returns:
        The singleton LLMEngine instance.
    """
    container = get_container()
    from myharness.llm.engine import LLMEngine

    return container.resolve(LLMEngine)


async def get_skill_store() -> "SkillStore":
    """Resolve the SkillStore from the DI container.

    Returns:
        The singleton SkillStore instance.
    """
    container = get_container()
    from myharness.skill.store import SkillStore

    return container.resolve(SkillStore)


async def get_event_bus() -> "EventBus":
    """Resolve the EventBus from the DI container.

    Returns:
        The singleton EventBus instance.
    """
    container = get_container()
    from myharness.bus.dispatcher import EventBus

    return container.resolve(EventBus)
