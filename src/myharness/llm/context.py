"""ContextBuilder — assembles context from Memory System for LLM consumption.

The ContextBuilder is the bridge between the Memory System (source of truth)
and the LLM Engine (stateless reasoning). It queries memory stores to
build structured context dictionaries for each cognitive operation.

Per P0: The LLM is stateless. All context is externalized into the Memory
System and assembled here per-request.
"""

from __future__ import annotations

from typing import Any, TYPE_CHECKING

import structlog

from myharness.schema.memory import (
    MemoryCategory,
    MemoryQuery,
    EpisodicEntry,
    SemanticEntry,
    RelationshipEntry,
)

if TYPE_CHECKING:
    from myharness.memory.system import MemorySystem

logger = structlog.get_logger(__name__)


class ContextBuilder:
    """Assembles context from Memory System for LLM consumption.

    Reads from the Memory System's four stores (identity, episodic,
    semantic, relationship) and formats them into structured dicts
    suitable for Jinja2 prompt templates.

    The ContextBuilder is stateless — it has no stored conversations,
    no identity, no memory of its own. It is purely a query interface.
    """

    def __init__(self, memory: "MemorySystem") -> None:
        """Initialize with a reference to the Memory System.

        Args:
            memory: The MemorySystem instance to query for context.
        """
        self._memory = memory
        logger.info("context_builder_initialized")

    async def build_think_context(self, query: str) -> dict[str, Any]:
        """Build full context for the think() cognitive operation.

        Assembles identity, relevant memories, and semantic knowledge
        relevant to the query.

        Args:
            query: The user's query or the cognitive question being analyzed.

        Returns:
            A dict with identity data, memory context string, and the query.
        """
        identity_context = await self.get_identity_context()
        memory_context = await self.get_memory_context(query)

        return {
            "agent_name": identity_context.get("name", "Agent"),
            "self_description": identity_context.get("self_description", ""),
            "core_values": identity_context.get("core_values", []),
            "mission": identity_context.get("mission", ""),
            "memory_context": memory_context,
            "query": query,
        }

    async def build_plan_context(
        self,
        goal: str,
        available_skills: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Build context for the plan() cognitive operation.

        Assembles identity context and formats available skills for
        planning.

        Args:
            goal: The goal to plan for.
            available_skills: List of skill definitions available for planning.

        Returns:
            A dict with identity data, available skills, and the goal.
        """
        identity_context = await self.get_identity_context()

        return {
            "agent_name": identity_context.get("name", "Agent"),
            "self_description": identity_context.get("self_description", ""),
            "mission": identity_context.get("mission", ""),
            "available_skills": available_skills,
            "goal": goal,
        }

    async def build_reflect_context(
        self,
        experience: dict[str, Any],
    ) -> dict[str, Any]:
        """Build context for the reflect() cognitive operation.

        Assembles identity context alongside the experience to be reflected on.

        Args:
            experience: The experience/episode to reflect on (as a dict).

        Returns:
            A dict with identity data and the experience.
        """
        identity_context = await self.get_identity_context()

        return {
            "agent_name": identity_context.get("name", "Agent"),
            "self_description": identity_context.get("self_description", ""),
            "core_values": identity_context.get("core_values", []),
            "experience": experience,
        }

    async def build_compile_context(
        self,
        experience: dict[str, Any],
        reflection: dict[str, Any],
    ) -> dict[str, Any]:
        """Build context for the compile() cognitive operation.

        Assembles identity context alongside the experience and its
        reflection for skill compilation.

        Args:
            experience: The original experience (as a dict).
            reflection: The reflection result (as a dict).

        Returns:
            A dict with identity data, experience, and reflection.
        """
        identity_context = await self.get_identity_context()

        return {
            "agent_name": identity_context.get("name", "Agent"),
            "experience": experience,
            "reflection": reflection,
        }

    async def get_identity_context(self) -> dict[str, Any]:
        """Get the agent's identity as context for LLM interpretation.

        Reads the current identity from the Memory System and returns
        it as a structured dict.

        Returns:
            Identity context dict with name, core_values, mission,
            self_description, behavioral_guidelines, and preferences.
        """
        try:
            identity = await self._memory.get_identity()
            if identity is None:
                logger.warning("no_identity_found_returning_defaults")
                return {
                    "name": "Agent",
                    "core_values": [],
                    "mission": "",
                    "self_description": "A cognitive AI agent",
                    "behavioral_guidelines": [],
                    "preferences": {},
                }

            return {
                "name": identity.name,
                "core_values": identity.core_values,
                "mission": identity.mission,
                "self_description": identity.self_description,
                "behavioral_guidelines": identity.behavioral_guidelines,
                "preferences": identity.preferences,
            }
        except Exception as exc:
            logger.error("failed_to_get_identity", error=str(exc))
            return {
                "name": "Agent",
                "core_values": [],
                "mission": "",
                "self_description": "A cognitive AI agent",
                "behavioral_guidelines": [],
                "preferences": {},
            }

    async def get_memory_context(
        self,
        query: str,
        top_k: int = 10,
    ) -> str:
        """Get relevant memory entries as formatted text.

        Searches across all memory stores (episodic, semantic, relationship)
        and formats results as human-readable text for inclusion in prompts.

        Args:
            query: The query to search memories against.
            top_k: Maximum number of results per store.

        Returns:
            Formatted string of relevant memories.
        """
        if not query.strip():
            return "No relevant memories available."

        sections: list[str] = []

        try:
            # Search episodic memory
            episodic_results = await self._memory.search(
                MemoryQuery(
                    query_text=query,
                    categories=[MemoryCategory.EPISODIC],
                    top_k=top_k,
                )
            )
            if episodic_results and episodic_results.results:
                lines = ["### Past Experiences"]
                for i, result in enumerate(episodic_results.results, 1):
                    lines.append(f"{i}. {result.content}")
                    if result.score:
                        lines.append(f"   (relevance: {result.score:.2f})")
                sections.append("\n".join(lines))

            # Search semantic memory
            semantic_results = await self._memory.search(
                MemoryQuery(
                    query_text=query,
                    categories=[MemoryCategory.SEMANTIC],
                    top_k=top_k,
                )
            )
            if semantic_results and semantic_results.results:
                lines = ["### Known Facts"]
                for i, result in enumerate(semantic_results.results, 1):
                    lines.append(f"{i}. {result.content}")
                sections.append("\n".join(lines))

            # Search relationship memory
            relationship_results = await self._memory.search(
                MemoryQuery(
                    query_text=query,
                    categories=[MemoryCategory.RELATIONSHIP],
                    top_k=top_k,
                )
            )
            if relationship_results and relationship_results.results:
                lines = ["### Known Relationships"]
                for i, result in enumerate(relationship_results.results, 1):
                    lines.append(f"{i}. {result.content}")
                sections.append("\n".join(lines))

        except Exception as exc:
            logger.error("memory_search_failed", error=str(exc))
            return f"Memory search encountered an error: {exc}"

        if not sections:
            return "No relevant memories found for this query."

        return "\n\n".join(sections)
