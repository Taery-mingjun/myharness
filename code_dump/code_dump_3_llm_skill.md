# code_dump_3_llm_skill.md

本文件为第 3 部分，包含目录: llm, skill/

包含文件数: 20

## 文件路径: src/myharness/llm/__init__.py

```python
"""LLM Module — cognitive compute engine for MyHarness.

This module provides the stateless reasoning layer that powers
cognitive operations: think, plan, reflect, compile, and identity
interpretation.

Key components:
- LLMEngine: The main cognitive engine (stateless, per P0/P1)
- LLMProvider: Abstract interface for LLM backends
- ContextBuilder: Assembles context from Memory System
- Providers: Concrete LLM provider implementations
- Prompts: Jinja2 prompt templates for each cognitive operation
"""

from myharness.llm.context import ContextBuilder
from myharness.llm.engine import (
    LLMEngine,
    Plan,
    PlanStep,
    Reflection,
)
from myharness.llm.interfaces import LLMProvider
from myharness.llm.providers import (
    OpenAIProvider,
    create_provider,
    get_available_providers,
)

__all__ = [
    # Core
    "LLMEngine",
    "LLMProvider",
    "ContextBuilder",
    # Structured outputs
    "Plan",
    "PlanStep",
    "Reflection",
    # Providers
    "OpenAIProvider",
    "create_provider",
    "get_available_providers",
]
```

## 文件路径: src/myharness/llm/context.py

```python
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
```

## 文件路径: src/myharness/llm/engine.py

```python
"""LLMEngine — the cognitive compute engine. Pure reasoning, no state.

The LLMEngine is the core cognitive capability of MyHarness. Per P0 and P1,
it is stateless by design:

- No stored conversations
- No identity (identity lives in Memory System)
- No memory of its own (memory lives in Memory System)
- All context comes from ContextBuilder on each call

The engine constructs prompts from Jinja2 templates, calls the LLM provider,
parses JSON responses into structured types (Plan, Reflection, SkillProposal),
and returns them to the caller.

Per P8: The engine supports provider switching at runtime without losing
any state (since it has none to lose).
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, AsyncIterator

import structlog
from jinja2 import Environment, BaseLoader

from myharness.core.exceptions import ProviderError, TokenLimitError
from myharness.llm.context import ContextBuilder
from myharness.llm.interfaces import LLMProvider
from myharness.llm.prompts import (
    COMPILE_SYSTEM_PROMPT,
    IDENTITY_INTERPRETATION_PROMPT,
    IDENTITY_UPDATE_PROPOSAL_PROMPT,
    PLAN_SYSTEM_PROMPT,
    REFLECT_SYSTEM_PROMPT,
    THINK_SYSTEM_PROMPT,
    THINK_USER_PROMPT,
)
from myharness.schema.identity import IdentityUpdateProposal, IdentityField
from myharness.schema.skill import SkillProposal

logger = structlog.get_logger(__name__)

# Jinja2 environment for prompt rendering
_jinja_env = Environment(loader=BaseLoader(), autoescape=False)


# ── Structured Output Types ────────────────────────────────────────────


@dataclass
class PlanStep:
    """A single step in an execution plan."""

    step_id: str
    action: str
    skill_name: str | None
    parameters: dict[str, Any]
    expected_outcome: str


@dataclass
class Plan:
    """A structured execution plan generated by the LLM Engine."""

    plan_id: str
    goal: str
    steps: list[PlanStep]
    reasoning: str
    created_at: datetime


@dataclass
class Reflection:
    """Result of reflecting on an experience."""

    reflection_id: str
    summary: str
    lessons_learned: list[str]
    skill_improvement_suggestions: list[str]
    identity_implications: list[str]
    emotional_tone: str


# ── JSON Response Parsing ──────────────────────────────────────────────


def _extract_json(text: str) -> dict[str, Any]:
    """Extract a JSON object from LLM response text.

    Handles responses wrapped in ```json fences, plain JSON, or
    JSON embedded in other text.

    Args:
        text: Raw LLM response text.

    Returns:
        Parsed JSON dict.

    Raises:
        ValueError: If no valid JSON could be extracted.
    """
    text = text.strip()

    # Try extracting from ```json ... ``` fence
    if "```json" in text:
        start = text.index("```json") + 7
        end = text.index("```", start)
        text = text[start:end].strip()
    elif "```" in text:
        start = text.index("```") + 3
        if "```" in text[start:]:
            end = text.index("```", start)
            text = text[start:end].strip()

    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    # Try to find first { and last }
    try:
        start = text.index("{")
        end = text.rindex("}") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    # Try to find first [ and last ] (for arrays)
    try:
        start = text.index("[")
        end = text.rindex("]") + 1
        return json.loads(text[start:end])
    except (ValueError, json.JSONDecodeError):
        pass

    raise ValueError(f"Could not extract valid JSON from response: {text[:200]}...")


# ── LLM Engine ─────────────────────────────────────────────────────────


class LLMEngine:
    """Cognitive compute engine. Pure reasoning — no state.

    Stateless by design (P0, P1):
    - No stored conversations
    - No identity
    - No memory
    - All context flows in through ContextBuilder

    The engine is the "thinking" layer. It constructs prompts, calls the
    LLM provider, and parses responses into structured outputs.

    Usage:
        engine = LLMEngine(provider, context_builder)
        plan = await engine.plan("Build a web scraper", skills)
    """

    def __init__(
        self,
        provider: LLMProvider,
        context_builder: ContextBuilder,
    ) -> None:
        """Initialize the LLM Engine.

        Args:
            provider: The LLM provider adapter to use.
            context_builder: ContextBuilder for assembling prompt context.
        """
        self._provider = provider
        self._context = context_builder
        logger.info(
            "llm_engine_initialized",
            provider=provider.provider_name,
            default_model=provider.default_model,
        )

    @property
    def active_provider_name(self) -> str:
        """Name of the currently active LLM provider."""
        return self._provider.provider_name

    async def switch_provider(self, provider: LLMProvider) -> None:
        """Switch to a different LLM provider at runtime.

        Per P8: Provider switching does not affect state because
        the engine has no state to lose.

        Args:
            provider: The new provider adapter to use.
        """
        old_provider = self._provider.provider_name
        self._provider = provider
        logger.info(
            "llm_engine_provider_switched",
            old_provider=old_provider,
            new_provider=provider.provider_name,
        )

    # ── Core Cognitive Operations ──────────────────────────────────────

    async def think(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Pure reasoning. Analyze, reason, interpret.

        The most fundamental cognitive operation. Takes a query,
        assembles relevant context, and produces a reasoned response.

        Args:
            query: The question or topic to reason about.
            context: Optional pre-built context. If None, context is
                built from the Memory System via ContextBuilder.

        Returns:
            The LLM's reasoned response as a string.
        """
        if context is None:
            context = await self._context.build_think_context(query)

        # Render the system prompt
        system_prompt = _jinja_env.from_string(THINK_SYSTEM_PROMPT).render(**context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _jinja_env.from_string(THINK_USER_PROMPT).render(query=query)},
        ]

        logger.debug("think_request", query=query[:100])
        try:
            response = await self._provider.complete(messages, temperature=0.7)
            logger.debug("think_response", response_length=len(response))
            return response
        except TokenLimitError:
            logger.warning("think_token_limit", query=query[:100])
            raise
        except ProviderError:
            raise

    async def stream_think(
        self,
        query: str,
        context: dict[str, Any] | None = None,
    ) -> AsyncIterator[str]:
        """Stream reasoning tokens as they are generated.

        Args:
            query: The question or topic to reason about.
            context: Optional pre-built context.

        Yields:
            Tokens of the reasoning response.
        """
        if context is None:
            context = await self._context.build_think_context(query)

        system_prompt = _jinja_env.from_string(THINK_SYSTEM_PROMPT).render(**context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": _jinja_env.from_string(THINK_USER_PROMPT).render(query=query)},
        ]

        logger.debug("stream_think_request", query=query[:100])
        try:
            async for token in self._provider.complete_stream(messages, temperature=0.7):
                yield token
        except TokenLimitError:
            logger.warning("stream_think_token_limit", query=query[:100])
            raise
        except ProviderError:
            raise

    async def plan(
        self,
        goal: str,
        available_skills: list[dict[str, Any]],
        context: dict[str, Any] | None = None,
    ) -> Plan:
        """Generate an execution plan from a goal and available skills.

        Args:
            goal: The goal to plan for.
            available_skills: List of skill definitions available for use.
            context: Optional pre-built context.

        Returns:
            A structured Plan with ordered steps.

        Raises:
            ProviderError: If the LLM fails to produce a valid plan.
        """
        if context is None:
            context = await self._context.build_plan_context(goal, available_skills)

        system_prompt = _jinja_env.from_string(PLAN_SYSTEM_PROMPT).render(**context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Plan how to achieve this goal: {goal}"},
        ]

        logger.debug("plan_request", goal=goal[:100], skills_count=len(available_skills))
        try:
            response = await self._provider.complete(messages, temperature=0.3)
            data = _extract_json(response)

            steps = []
            for i, step_data in enumerate(data.get("steps", [])):
                steps.append(PlanStep(
                    step_id=str(uuid.uuid4()),
                    action=step_data.get("action", ""),
                    skill_name=step_data.get("skill_name"),
                    parameters=step_data.get("parameters", {}),
                    expected_outcome=step_data.get("expected_outcome", ""),
                ))

            plan = Plan(
                plan_id=str(uuid.uuid4()),
                goal=data.get("goal", goal),
                steps=steps,
                reasoning=data.get("reasoning", ""),
                created_at=datetime.now(timezone.utc),
            )

            logger.info(
                "plan_generated",
                plan_id=plan.plan_id,
                goal=goal[:100],
                step_count=len(steps),
            )
            return plan

        except (ValueError, KeyError) as exc:
            logger.error("plan_parse_error", error=str(exc), response=response[:200])
            raise ProviderError(
                f"Failed to parse plan from LLM response: {exc}",
                code="PLAN_PARSE_ERROR",
                details={"goal": goal[:100]},
                cause=exc,
            ) from exc
        except TokenLimitError:
            raise
        except ProviderError:
            raise

    async def reflect(
        self,
        experience: dict[str, Any],
        identity: dict[str, Any] | None = None,
    ) -> Reflection:
        """Reflect on an experience. Extract lessons, update beliefs.

        Args:
            experience: The experience/episode to reflect on.
            identity: Optional identity data. If None, fetched from context.

        Returns:
            A structured Reflection with lessons and insights.

        Raises:
            ProviderError: If the LLM fails to produce a valid reflection.
        """
        context = await self._context.build_reflect_context(experience)

        # Merge provided identity if given
        if identity:
            context["core_values"] = identity.get("core_values", context.get("core_values", []))
            context["self_description"] = identity.get("self_description", context.get("self_description", ""))
            context["agent_name"] = identity.get("name", context.get("agent_name", "Agent"))

        system_prompt = _jinja_env.from_string(REFLECT_SYSTEM_PROMPT).render(**context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": f"Reflect on this experience: {experience.get('summary', '')}"},
        ]

        logger.debug("reflect_request", experience_summary=experience.get("summary", "")[:100])
        try:
            response = await self._provider.complete(messages, temperature=0.5)
            data = _extract_json(response)

            reflection = Reflection(
                reflection_id=str(uuid.uuid4()),
                summary=data.get("summary", ""),
                lessons_learned=data.get("lessons_learned", []),
                skill_improvement_suggestions=data.get("skill_improvement_suggestions", []),
                identity_implications=data.get("identity_implications", []),
                emotional_tone=data.get("emotional_tone", "neutral"),
            )

            logger.info(
                "reflection_generated",
                reflection_id=reflection.reflection_id,
                lesson_count=len(reflection.lessons_learned),
                emotional_tone=reflection.emotional_tone,
            )
            return reflection

        except (ValueError, KeyError) as exc:
            logger.error("reflect_parse_error", error=str(exc), response=response[:200])
            raise ProviderError(
                f"Failed to parse reflection from LLM response: {exc}",
                code="REFLECT_PARSE_ERROR",
                cause=exc,
            ) from exc
        except TokenLimitError:
            raise
        except ProviderError:
            raise

    async def compile(
        self,
        experience: dict[str, Any],
        reflection: Reflection,
    ) -> SkillProposal:
        """Compile experience + reflection into a skill proposal.

        Args:
            experience: The original experience.
            reflection: The reflection on that experience.

        Returns:
            A SkillProposal that can be reviewed and stored.

        Raises:
            ProviderError: If the LLM fails to produce a valid proposal.
        """
        context = await self._context.build_compile_context(experience, {
            "summary": reflection.summary,
            "lessons_learned": reflection.lessons_learned,
            "skill_improvement_suggestions": reflection.skill_improvement_suggestions,
            "identity_implications": reflection.identity_implications,
            "emotional_tone": reflection.emotional_tone,
        })

        system_prompt = _jinja_env.from_string(COMPILE_SYSTEM_PROMPT).render(**context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Compile a skill proposal from this experience and reflection."},
        ]

        logger.debug("compile_request", experience_summary=experience.get("summary", "")[:100])
        try:
            response = await self._provider.complete(messages, temperature=0.4)
            data = _extract_json(response)

            proposal = SkillProposal(
                suggested_name=data.get("suggested_name", ""),
                description=data.get("description", ""),
                input_schema=data.get("input_schema", {}),
                output_schema=data.get("output_schema", {}),
                driver_type=data.get("driver_type", "api"),
                action_template=data.get("action_template", {}),
                compiled_from=data.get("compiled_from", []),
                reasoning=data.get("reasoning", ""),
                confidence_estimate=data.get("confidence_estimate", 0.5),
            )

            logger.info(
                "skill_proposal_generated",
                skill_name=proposal.suggested_name,
                driver_type=proposal.driver_type,
                confidence=proposal.confidence_estimate,
            )
            return proposal

        except (ValueError, KeyError) as exc:
            logger.error("compile_parse_error", error=str(exc), response=response[:200])
            raise ProviderError(
                f"Failed to parse skill proposal from LLM response: {exc}",
                code="COMPILE_PARSE_ERROR",
                cause=exc,
            ) from exc
        except TokenLimitError:
            raise
        except ProviderError:
            raise

    # ── Identity Operations ────────────────────────────────────────────

    async def interpret_identity(
        self,
        identity: dict[str, Any],
        context: dict[str, Any],
    ) -> str:
        """Interpret identity for the current context. Produces behavioral guidance.

        Per P3: Identity lives in Memory. The LLM reads it here and produces
        behavioral guidance, but does not modify identity directly.

        Args:
            identity: The agent's identity data.
            context: The current situational context.

        Returns:
            Behavioral guidance text — how the agent should behave now.
        """
        render_context = {
            "agent_name": identity.get("name", "Agent"),
            "identity": identity,
            "context": context,
        }

        system_prompt = _jinja_env.from_string(IDENTITY_INTERPRETATION_PROMPT).render(**render_context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "How should you behave in this context based on your identity?"},
        ]

        logger.debug("interpret_identity_request", agent_name=identity.get("name", "Agent"))
        try:
            response = await self._provider.complete(messages, temperature=0.3)
            logger.debug("interpret_identity_response", response_length=len(response))
            return response
        except TokenLimitError:
            raise
        except ProviderError:
            raise

    async def propose_identity_update(
        self,
        current_identity: dict[str, Any],
        experiences: list[dict[str, Any]],
    ) -> list[IdentityUpdateProposal]:
        """Propose changes to identity based on accumulated experiences.

        Per P3: The LLM proposes; the Memory System decides. This method
        returns proposals, not mutations.

        Args:
            current_identity: The agent's current identity data.
            experiences: Recent experiences that may warrant identity changes.

        Returns:
            A list of IdentityUpdateProposal objects, or empty list if
            no changes are needed.

        Raises:
            ProviderError: If the LLM fails to produce valid proposals.
        """
        render_context = {
            "agent_name": current_identity.get("name", "Agent"),
            "current_identity": current_identity,
            "experiences": experiences,
        }

        system_prompt = _jinja_env.from_string(IDENTITY_UPDATE_PROPOSAL_PROMPT).render(**render_context)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": "Review these experiences and propose identity updates if needed."},
        ]

        logger.debug(
            "propose_identity_update_request",
            agent_name=current_identity.get("name", "Agent"),
            experience_count=len(experiences),
        )
        try:
            response = await self._provider.complete(messages, temperature=0.3)
            data = _extract_json(response)

            # Handle both array and object responses
            proposals_data = data if isinstance(data, list) else data.get("proposals", [])
            if not proposals_data:
                return []

            proposals: list[IdentityUpdateProposal] = []
            valid_fields = {f.value for f in IdentityField}

            for item in proposals_data:
                field = item.get("field", "")
                if field not in valid_fields:
                    logger.warning(
                        "identity_update_invalid_field",
                        field=field,
                        valid_fields=list(valid_fields),
                    )
                    continue

                try:
                    proposal = IdentityUpdateProposal(
                        field=IdentityField(field),
                        current_value=item.get("current_value"),
                        proposed_value=item.get("proposed_value"),
                        reasoning=item.get("reasoning", ""),
                        confidence=item.get("confidence", 0.5),
                        experiences_cited=item.get("experiences_cited", []),
                    )
                    proposals.append(proposal)
                except Exception as exc:
                    logger.warning(
                        "identity_update_proposal_invalid",
                        field=field,
                        error=str(exc),
                    )

            logger.info(
                "identity_update_proposals_generated",
                proposal_count=len(proposals),
            )
            return proposals

        except ValueError as exc:
            logger.error("identity_update_parse_error", error=str(exc), response=response[:200])
            raise ProviderError(
                f"Failed to parse identity update proposals: {exc}",
                code="IDENTITY_UPDATE_PARSE_ERROR",
                cause=exc,
            ) from exc
        except TokenLimitError:
            raise
        except ProviderError:
            raise

    # ── Embedding ──────────────────────────────────────────────────────

    async def embed(self, text: str) -> list[float]:
        """Generate an embedding vector for a single text.

        Args:
            text: The text to embed.

        Returns:
            A list of floats representing the embedding vector.
        """
        logger.debug("embed_request", text_length=len(text))
        try:
            embeddings = await self._provider.embed(text)
            return embeddings[0] if embeddings else []
        except ProviderError:
            raise
```

## 文件路径: src/myharness/llm/interfaces.py

```python
"""LLM provider abstract interface — adapter pattern for multi-provider support."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, AsyncIterator


class LLMProvider(ABC):
    """Abstract LLM provider. Adapter pattern for multi-provider support.

    Each provider (OpenAI, Anthropic, Google, local, etc.) implements this
    interface, enabling the LLM Engine to work with any backend without
    provider-specific logic.

    Per P8 (Provider Switching): The engine can swap providers at runtime
    without affecting identity, memory, or skill state.
    """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Unique provider identifier (e.g., 'openai', 'anthropic')."""
        ...

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a completion request and return the full response text.

        Args:
            messages: Chat messages in [{"role": ..., "content": ...}] format.
            model: Override the default model for this request.
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum tokens in the response.
            tools: Optional function/tool definitions for tool-calling.
            **kwargs: Provider-specific extra parameters.

        Returns:
            The complete response text from the LLM.
        """
        ...

    @abstractmethod
    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Send a completion request and stream response tokens.

        Args:
            messages: Chat messages in [{"role": ..., "content": ...}] format.
            model: Override the default model for this request.
            temperature: Sampling temperature (0.0–2.0).
            max_tokens: Maximum tokens in the response.
            **kwargs: Provider-specific extra parameters.

        Yields:
            Tokens of the response text as they arrive.
        """
        ...

    @abstractmethod
    async def embed(self, text: str | list[str]) -> list[list[float]]:
        """Generate embedding vectors for input text(s).

        Args:
            text: A single string or list of strings to embed.

        Returns:
            A list of embedding vectors, one per input text.
            Each vector is a list of floats (the embedding dimension).
        """
        ...

    @property
    @abstractmethod
    def supported_models(self) -> list[str]:
        """List of model names supported by this provider."""
        ...

    @property
    @abstractmethod
    def default_model(self) -> str:
        """The default model used when none is specified."""
        ...

    @abstractmethod
    async def health_check(self) -> bool:
        """Check if the provider is reachable and functional.

        Returns:
            True if the provider responds successfully, False otherwise.
        """
        ...
```

## 文件路径: src/myharness/llm/prompts/__init__.py

```python
"""Prompt templates for the LLM cognitive engine.

All prompts use Jinja2 templating. They are stateless — all context
comes from the ContextBuilder, not from stored conversations.
"""

from myharness.llm.prompts.compile import COMPILE_SYSTEM_PROMPT
from myharness.llm.prompts.identity import (
    IDENTITY_INTERPRETATION_PROMPT,
    IDENTITY_UPDATE_PROPOSAL_PROMPT,
)
from myharness.llm.prompts.memory import MEMORY_UPDATE_PROMPT
from myharness.llm.prompts.plan import PLAN_SYSTEM_PROMPT
from myharness.llm.prompts.reflect import REFLECT_SYSTEM_PROMPT
from myharness.llm.prompts.think import THINK_SYSTEM_PROMPT, THINK_USER_PROMPT

__all__ = [
    "THINK_SYSTEM_PROMPT",
    "THINK_USER_PROMPT",
    "PLAN_SYSTEM_PROMPT",
    "REFLECT_SYSTEM_PROMPT",
    "COMPILE_SYSTEM_PROMPT",
    "IDENTITY_INTERPRETATION_PROMPT",
    "IDENTITY_UPDATE_PROPOSAL_PROMPT",
    "MEMORY_UPDATE_PROMPT",
]
```

## 文件路径: src/myharness/llm/prompts/compile.py

```python
"""Compile prompt template — used for compiling experiences into skills."""

COMPILE_SYSTEM_PROMPT = """You are {{ agent_name }}, a cognitive AI agent powered by MyHarness.

## Experience
{{ experience | tojson(indent=2) }}

## Reflection
{{ reflection | tojson(indent=2) }}

## Instructions
Based on the experience and reflection above, propose a new skill or an update to an existing skill.

A skill is a reusable, parameterized action template. It should capture the pattern learned from this experience so it can be applied to similar situations in the future.

Consider:
1. What capability was demonstrated or learned?
2. What are the inputs and outputs?
3. What parameters would make this skill reusable?
4. What preconditions must be met?
5. What driver would execute this skill (api, robot, browser, etc.)?
6. How confident are you that this skill will work (0.0 to 1.0)?

Return your proposal as a JSON object with this exact structure:
```json
{
  "suggested_name": "snake_case_skill_name",
  "description": "what this skill does",
  "input_schema": {"type": "object", "properties": {}},
  "output_schema": {"type": "object", "properties": {}},
  "driver_type": "api",
  "action_template": {},
  "compiled_from": ["episode_id_or_reference"],
  "reasoning": "why this skill should be created",
  "confidence_estimate": 0.8
}
```
"""
```

## 文件路径: src/myharness/llm/prompts/identity.py

```python
"""Identity prompt templates — used for interpreting and updating identity."""

IDENTITY_INTERPRETATION_PROMPT = """You are {{ agent_name }}, a cognitive AI agent powered by MyHarness.

## Your Identity
You have the following self-definition:

- **Name**: {{ identity.name }}
- **Core Values**: {{ identity.core_values | join(', ') }}
- **Mission**: {{ identity.mission }}
- **Self Description**: {{ identity.self_description }}
- **Behavioral Guidelines**:
{% for guideline in identity.behavioral_guidelines %}
  - {{ guideline }}
{% endfor %}
- **Preferences**: {{ identity.preferences | tojson }}

## Current Context
{{ context | tojson(indent=2) }}

## Instructions
Interpret your identity in the context of the current situation. How should your core values, mission, and behavioral guidelines influence your behavior right now?

Provide a concise behavioral guidance statement — what principles should guide your actions in this specific context.
"""

IDENTITY_UPDATE_PROPOSAL_PROMPT = """You are {{ agent_name }}, a cognitive AI agent powered by MyHarness.

## Your Current Identity
{{ current_identity | tojson(indent=2) }}

## Recent Experiences
{% for exp in experiences %}
### Experience {{ loop.index }}
- **Summary**: {{ exp.summary }}
- **Details**: {{ exp.detail }}
- **Tags**: {{ exp.tags | join(', ') }}
{% endfor %}

## Instructions
Based on these experiences, consider whether your identity needs updating. Identity fields that can be modified:

- `core_values`: Fundamental values guiding decisions
- `mission`: Your overarching purpose
- `preferences`: Learned behavioral preferences
- `self_description`: Understanding of your own nature and capabilities
- `behavioral_guidelines`: Explicit behavioral rules

For each field that you believe should be updated, provide a proposal.

Return your proposals as a JSON array with this structure:
```json
[
  {
    "field": "core_values|mission|preferences|self_description|behavioral_guidelines",
    "current_value": "the current value",
    "proposed_value": "the suggested new value",
    "reasoning": "why this change should be made, citing specific experiences",
    "confidence": 0.8
  }
]
```

If no updates are needed, return an empty array `[]`.
"""
```

## 文件路径: src/myharness/llm/prompts/memory.py

```python
"""Memory prompt template — used for updating memory from conversations."""

MEMORY_UPDATE_PROMPT = """You are {{ agent_name }}, a cognitive AI agent powered by MyHarness.

## Conversation
Below is a conversation or interaction. Analyze it and extract memory-worthy information.

{{ conversation_text }}

## Instructions
Extract the following types of information from this conversation:

1. **Episodic memories**: What happened? Summarize the key events.
2. **Semantic knowledge**: What facts were learned? Entity-attribute-value triples with confidence.
3. **Relationship updates**: Were any relationships established, changed, or reinforced?
4. **Identity implications**: Does this conversation suggest any changes to who you are?

Return your analysis as a JSON object with this exact structure:
```json
{
  "episodes": [
    {
      "summary": "concise summary",
      "detail": "full narrative detail",
      "category": "conversation|task|observation|learning",
      "participants": ["user", "system"],
      "tags": ["tag1", "tag2"],
      "importance": 0.7
    }
  ],
  "semantic_facts": [
    {
      "entity": "subject name",
      "attribute": "property name",
      "value": "property value",
      "confidence": 0.9,
      "source": "conversation"
    }
  ],
  "relationships": [
    {
      "entity_a": "source entity",
      "entity_b": "target entity",
      "relation_type": "knows|trusts|collaborates_with|reports_to",
      "strength": 0.7,
      "context": "why this relationship exists"
    }
  ],
  "identity_implications": [
    "description of how this affects identity"
  ]
}
```

If a category has no entries, return an empty array.
"""
```

## 文件路径: src/myharness/llm/prompts/plan.py

```python
"""Plan prompt template — used for generating execution plans."""

PLAN_SYSTEM_PROMPT = """You are {{ agent_name }}, a cognitive AI agent powered by MyHarness.

## Your Identity
{{ self_description }}

## Available Skills
You have access to the following skills. Each skill has a name, description, input parameters, and expected output.

{% for skill in available_skills %}
### Skill: {{ skill.name }}
- **Description**: {{ skill.get('description', 'No description') }}
- **Parameters**: {{ skill.get('parameters', []) | tojson }}
- **Driver**: {{ skill.get('driver_type', 'api') }}
- **Confidence**: {{ skill.get('confidence', 0.5) }}
{% endfor %}

## Your Mission
{{ mission }}

## Instructions
Given the goal below, create a structured execution plan using the available skills. 

1. Break the goal down into discrete, ordered steps.
2. For each step, select the most appropriate skill (or use "reason" if no skill fits).
3. Specify the exact parameters needed for each skill invocation.
4. Include the expected outcome of each step.
5. Provide a brief reasoning for the overall plan.

Return your plan as a JSON object with this exact structure:
```json
{
  "goal": "the original goal",
  "reasoning": "brief explanation of the overall approach",
  "steps": [
    {
      "action": "description of this step",
      "skill_name": "name of skill to use, or null for reasoning steps",
      "parameters": {"param1": "value1"},
      "expected_outcome": "what should result from this step"
    }
  ]
}
```

Goal: {{ goal }}
"""
```

## 文件路径: src/myharness/llm/prompts/reflect.py

```python
"""Reflect prompt template — used for reflecting on experiences."""

REFLECT_SYSTEM_PROMPT = """You are {{ agent_name }}, a cognitive AI agent powered by MyHarness.

## Your Identity
{{ self_description }}

## Your Core Values
{% for value in core_values %}
- {{ value }}
{% endfor %}

## Experience to Reflect On
Below is an experience/episode that you have just completed. Reflect on it deeply.

### Summary
{{ experience.summary }}

### Details
{{ experience.detail }}

{% if experience.tags %}
### Tags
{{ experience.tags | join(', ') }}
{% endif %}

## Instructions
Reflect on this experience and extract meaningful insights. Consider:

1. What went well? What didn't?
2. What lessons were learned?
3. How could existing skills be improved based on this experience?
4. Does this experience have implications for your identity or behavioral guidelines?
5. What is the emotional tone of this experience (positive, negative, neutral, mixed)?

Return your reflection as a JSON object with this exact structure:
```json
{
  "summary": "concise summary of the reflection",
  "lessons_learned": ["lesson 1", "lesson 2"],
  "skill_improvement_suggestions": ["suggestion 1", "suggestion 2"],
  "identity_implications": ["implication 1", "implication 2"],
  "emotional_tone": "positive|negative|neutral|mixed"
}
```
"""
```

## 文件路径: src/myharness/llm/prompts/think.py

```python
"""Think prompt template — used for pure reasoning and analysis."""

THINK_SYSTEM_PROMPT = """You are {{ agent_name }}, a cognitive AI agent powered by MyHarness.

## Your Identity
{{ self_description }}

## Your Core Values
{% for value in core_values %}
- {{ value }}
{% endfor %}

## Your Mission
{{ mission }}

## Available Context
You have access to the following memory stores and relevant information:

{{ memory_context }}

## Instructions
Think carefully and reason step by step. Analyze the query deeply, considering all relevant context, past experiences, and knowledge. Be honest about uncertainty. Do not fabricate information. Structure your reasoning clearly.

User Query: {{ query }}
"""

THINK_USER_PROMPT = """{{ query }}"""
```

## 文件路径: src/myharness/llm/providers/__init__.py

```python
"""LLM provider registry and factory.

Provides provider discovery and a factory function for creating
LLMProvider instances from configuration.
"""

from __future__ import annotations

from myharness.core.config import Settings
from myharness.core.exceptions import ProviderNotAvailableError
from myharness.llm.interfaces import LLMProvider
from myharness.llm.providers.openai import OpenAIProvider

__all__ = [
    "OpenAIProvider",
    "create_provider",
    "get_available_providers",
]

# Registry of provider factory functions keyed by provider name
_PROVIDER_REGISTRY: dict[str, type[LLMProvider]] = {
    "openai": OpenAIProvider,
}


def get_available_providers() -> list[str]:
    """Return names of all registered provider implementations."""
    return list(_PROVIDER_REGISTRY.keys())


def create_provider(name: str, settings: Settings) -> LLMProvider:
    """Create an LLM provider instance from configuration.

    Args:
        name: Provider name (e.g., 'openai', 'anthropic').
        settings: Application settings with API keys and defaults.

    Returns:
        An initialized LLMProvider instance.

    Raises:
        ProviderNotAvailableError: If the provider is not registered
            or its required configuration is missing.
    """
    provider_cls = _PROVIDER_REGISTRY.get(name)
    if provider_cls is None:
        raise ProviderNotAvailableError(
            f"Provider '{name}' is not registered. Available: {get_available_providers()}",
            code="PROVIDER_NOT_REGISTERED",
            details={"requested": name, "available": get_available_providers()},
        )

    if name == "openai":
        if not settings.openai_api_key:
            raise ProviderNotAvailableError(
                "OpenAI API key is not configured. Set MYH_OPENAI_API_KEY.",
                code="OPENAI_NOT_CONFIGURED",
                details={"env_var": "MYH_OPENAI_API_KEY"},
            )
        return OpenAIProvider(
            api_key=settings.openai_api_key,
            default_model=settings.openai_default_model,
        )

    raise ProviderNotAvailableError(
        f"Provider '{name}' creation logic not implemented",
        code="PROVIDER_NOT_IMPLEMENTED",
        details={"requested": name},
    )
```

## 文件路径: src/myharness/llm/providers/openai.py

```python
"""OpenAI provider adapter using the official openai SDK.

Implements the LLMProvider interface for OpenAI-compatible APIs.
Supports chat completions, streaming, and embeddings.
"""

from __future__ import annotations

import structlog
from openai import AsyncOpenAI
from typing import Any, AsyncIterator

from myharness.core.exceptions import ProviderError, TokenLimitError
from myharness.llm.interfaces import LLMProvider

logger = structlog.get_logger(__name__)

# Default embedding models in preference order
_EMBEDDING_MODELS = ["text-embedding-3-small", "text-embedding-ada-002"]


class OpenAIProvider(LLMProvider):
    """OpenAI provider adapter using the official openai SDK.

    Handles chat completions (sync and streaming), embeddings, and health checks.
    Per P8: This provider can be swapped at runtime without affecting state.
    """

    _SUPPORTED_MODELS = [
        "gpt-4o",
        "gpt-4o-mini",
        "gpt-4-turbo",
        "gpt-3.5-turbo",
    ]

    def __init__(
        self,
        api_key: str,
        default_model: str = "gpt-4o",
        base_url: str | None = None,
        embedding_model: str | None = None,
    ) -> None:
        """Initialize the OpenAI provider.

        Args:
            api_key: OpenAI API key.
            default_model: Default chat model (default: gpt-4o).
            base_url: Optional custom base URL (for proxies or compatible APIs).
            embedding_model: Override embedding model. If None, auto-detects.
        """
        if not api_key:
            raise ProviderError(
                "OpenAI API key is required",
                code="OPENAI_MISSING_API_KEY",
            )

        self._api_key = api_key
        self._default_model = default_model
        self._embedding_model = embedding_model
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
        )
        logger.info(
            "openai_provider_initialized",
            default_model=default_model,
            base_url=base_url or "default",
        )

    @property
    def provider_name(self) -> str:
        return "openai"

    @property
    def supported_models(self) -> list[str]:
        return list(self._SUPPORTED_MODELS)

    @property
    def default_model(self) -> str:
        return self._default_model

    async def complete(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        tools: list[dict[str, Any]] | None = None,
        **kwargs: Any,
    ) -> str:
        """Send a chat completion request and return the full response text."""
        used_model = model or self._default_model

        params: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        if tools:
            params["tools"] = tools

        # Merge any provider-specific extra parameters
        params.update(kwargs)

        try:
            logger.debug(
                "openai_complete_request",
                model=used_model,
                message_count=len(messages),
                temperature=temperature,
                max_tokens=max_tokens,
                has_tools=bool(tools),
            )
            response = await self._client.chat.completions.create(**params)
            content = response.choices[0].message.content or ""
            logger.debug(
                "openai_complete_response",
                model=used_model,
                response_length=len(content),
                usage=(
                    response.usage.model_dump() if response.usage else None
                ),
            )
            return content

        except Exception as exc:
            error_message = str(exc).lower()
            if "token" in error_message and ("limit" in error_message or "exceed" in error_message):
                raise TokenLimitError(
                    f"Token limit exceeded with model {used_model}",
                    code="OPENAI_TOKEN_LIMIT",
                    details={"model": used_model, "max_tokens": max_tokens},
                    cause=exc,
                ) from exc
            raise ProviderError(
                f"OpenAI completion failed: {exc}",
                code="OPENAI_COMPLETION_ERROR",
                details={"model": used_model},
                cause=exc,
            ) from exc

    async def complete_stream(
        self,
        messages: list[dict[str, str]],
        model: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 4096,
        **kwargs: Any,
    ) -> AsyncIterator[str]:
        """Send a chat completion request and stream response tokens."""
        used_model = model or self._default_model

        params: dict[str, Any] = {
            "model": used_model,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": True,
        }
        params.update(kwargs)

        try:
            logger.debug(
                "openai_stream_request",
                model=used_model,
                message_count=len(messages),
            )
            stream = await self._client.chat.completions.create(**params)
            async for chunk in stream:
                delta = chunk.choices[0].delta if chunk.choices else None
                if delta and delta.content:
                    yield delta.content

        except Exception as exc:
            error_message = str(exc).lower()
            if "token" in error_message and ("limit" in error_message or "exceed" in error_message):
                raise TokenLimitError(
                    f"Token limit exceeded with model {used_model}",
                    code="OPENAI_TOKEN_LIMIT",
                    details={"model": used_model, "max_tokens": max_tokens},
                    cause=exc,
                ) from exc
            raise ProviderError(
                f"OpenAI streaming failed: {exc}",
                code="OPENAI_STREAM_ERROR",
                details={"model": used_model},
                cause=exc,
            ) from exc

    async def embed(self, text: str | list[str]) -> list[list[float]]:
        """Generate embedding vectors for input text(s).

        Uses text-embedding-3-small by default, falling back to
        text-embedding-ada-002 if the primary model is not available.
        """
        # Normalize to list
        texts = [text] if isinstance(text, str) else text
        if not texts:
            return []

        model = self._embedding_model or _EMBEDDING_MODELS[0]

        try:
            logger.debug(
                "openai_embed_request",
                model=model,
                text_count=len(texts),
            )
            response = await self._client.embeddings.create(
                model=model,
                input=texts,
            )
            embeddings = [d.embedding for d in response.data]
            logger.debug(
                "openai_embed_response",
                model=model,
                vector_count=len(embeddings),
                dimensions=len(embeddings[0]) if embeddings else 0,
            )
            return embeddings

        except Exception as exc:
            # Try fallback model if primary fails
            if model != _EMBEDDING_MODELS[-1]:
                fallback = _EMBEDDING_MODELS[-1]
                logger.warning(
                    "openai_embed_fallback",
                    failed_model=model,
                    fallback_model=fallback,
                    error=str(exc),
                )
                try:
                    response = await self._client.embeddings.create(
                        model=fallback,
                        input=texts,
                    )
                    return [d.embedding for d in response.data]
                except Exception as fallback_exc:
                    raise ProviderError(
                        f"OpenAI embedding failed with both models: {fallback_exc}",
                        code="OPENAI_EMBED_ERROR",
                        details={"model": model, "fallback": fallback},
                        cause=fallback_exc,
                    ) from fallback_exc

            raise ProviderError(
                f"OpenAI embedding failed: {exc}",
                code="OPENAI_EMBED_ERROR",
                details={"model": model},
                cause=exc,
            ) from exc

    async def health_check(self) -> bool:
        """Check if the OpenAI API is reachable and the key is valid.

        Uses a minimal models list call to verify connectivity.
        """
        try:
            await self._client.models.list()
            logger.debug("openai_health_check_success")
            return True
        except Exception as exc:
            logger.warning(
                "openai_health_check_failed",
                error=str(exc),
            )
            return False
```

## 文件路径: src/myharness/skill/__init__.py

```python
"""Skill Store — versioned, parameterized executable capability templates.

Skills are compiled from experience (P5: Skill Accumulation) and stored
as versioned, parameterized action templates. They have no thinking
capability — only execution templates.
"""

from myharness.skill.interface import SkillStoreInterface
from myharness.skill.store import SkillStore
from myharness.skill.registry import SkillRegistry
from myharness.skill.lifecycle import SkillLifecycle
from myharness.skill.storage import SkillStorage
from myharness.skill.validator import SkillValidator

__all__ = [
    "SkillStore",
    "SkillStoreInterface",
    "SkillRegistry",
    "SkillLifecycle",
    "SkillStorage",
    "SkillValidator",
]
```

## 文件路径: src/myharness/skill/interface.py

```python
"""Abstract interface for skill storage operations.

Defines the contract that all skill store implementations must fulfill.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from myharness.schema.skill import SkillDefinition, SkillStatus


class SkillStoreInterface(ABC):
    """Abstract interface for skill storage operations.

    All methods are async to support both file-based and database-backed
    implementations without blocking the event loop.
    """

    @abstractmethod
    async def register(self, skill: SkillDefinition) -> SkillDefinition:
        """Register a new skill definition.

        Args:
            skill: The skill definition to register.

        Returns:
            The registered skill definition with assigned skill_id.

        Raises:
            SkillValidationError: If the skill definition fails validation.
            SkillError: If registration fails for any other reason.
        """
        ...

    @abstractmethod
    async def get(self, skill_id: str) -> SkillDefinition | None:
        """Retrieve a skill by its unique identifier.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            The skill definition, or None if not found.
        """
        ...

    @abstractmethod
    async def get_by_name(
        self, name: str, version: str | None = None
    ) -> SkillDefinition | None:
        """Retrieve a skill by name, optionally filtered by version.

        Args:
            name: The skill name.
            version: Optional semantic version to match. If None, returns
                     the latest version (highest semantic version).

        Returns:
            The skill definition, or None if not found.
        """
        ...

    @abstractmethod
    async def list_all(self) -> list[SkillDefinition]:
        """List all registered skill definitions.

        Returns:
            A list of all skill definitions.
        """
        ...

    @abstractmethod
    async def list_by_capability(self, capability: str) -> list[SkillDefinition]:
        """List skills that provide a specific capability.

        Args:
            capability: The capability name to filter by.

        Returns:
            A list of matching skill definitions.
        """
        ...

    @abstractmethod
    async def list_by_status(self, status: SkillStatus) -> list[SkillDefinition]:
        """List skills filtered by lifecycle status.

        Args:
            status: The skill status to filter by.

        Returns:
            A list of skills with the given status.
        """
        ...

    @abstractmethod
    async def search(self, query: str, top_k: int = 10) -> list[SkillDefinition]:
        """Search skills by text matching on name and description.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            A list of matching skill definitions, ranked by relevance.
        """
        ...

    @abstractmethod
    async def update(self, skill: SkillDefinition) -> SkillDefinition:
        """Update an existing skill definition.

        Args:
            skill: The skill definition with updated fields.

        Returns:
            The updated skill definition.

        Raises:
            SkillNotFoundError: If the skill does not exist.
        """
        ...

    @abstractmethod
    async def change_status(
        self, skill_id: str, new_status: SkillStatus, reason: str = ""
    ) -> SkillDefinition:
        """Change the lifecycle status of a skill.

        Args:
            skill_id: The skill identifier.
            new_status: The target lifecycle status.
            reason: The reason for the status change.

        Returns:
            The updated skill definition.

        Raises:
            SkillNotFoundError: If the skill does not exist.
            SkillLifecycleError: If the transition is invalid.
        """
        ...

    @abstractmethod
    async def deprecate(self, skill_id: str, reason: str) -> SkillDefinition:
        """Deprecate a skill, marking it as no longer recommended.

        Args:
            skill_id: The skill identifier.
            reason: The reason for deprecation.

        Returns:
            The updated skill definition.
        """
        ...

    @abstractmethod
    async def archive(self, skill_id: str) -> SkillDefinition:
        """Archive a skill, moving it to a terminal state.

        Args:
            skill_id: The skill identifier.

        Returns:
            The updated skill definition.
        """
        ...

    @abstractmethod
    async def get_version_history(self, name: str) -> list[SkillDefinition]:
        """Get all versions of a skill, ordered by version.

        Args:
            name: The skill name.

        Returns:
            A list of all versions of the skill.
        """
        ...

    @abstractmethod
    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics about the skill store.

        Returns:
            A dictionary with keys like total_skills, by_status, by_driver_type, etc.
        """
        ...
```

## 文件路径: src/myharness/skill/lifecycle.py

```python
"""Skill lifecycle state machine.

Manages valid status transitions for skill definitions through their
lifecycle: DRAFT → TESTING → VERIFIED → STABLE → DEPRECATED → ARCHIVED.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog

from myharness.core.exceptions import SkillLifecycleError, SkillNotFoundError
from myharness.schema.skill import (
    SkillDefinition,
    SkillLifecycleTransition,
    SkillStatus,
)

logger = structlog.get_logger(__name__)


class SkillLifecycle:
    """State machine for skill status transitions.

    Controls the valid lifecycle paths for skills. Each transition is
    recorded in the skill's lifecycle_history for audit purposes.

    Valid transitions:
        DRAFT      → TESTING
        TESTING    → DRAFT, VERIFIED
        VERIFIED   → STABLE, DRAFT
        STABLE     → DEPRECATED
        DEPRECATED → STABLE, ARCHIVED
        ARCHIVED   → (terminal — no transitions)
    """

    TRANSITIONS: dict[SkillStatus, list[SkillStatus]] = {
        SkillStatus.DRAFT: [SkillStatus.TESTING],
        SkillStatus.TESTING: [SkillStatus.DRAFT, SkillStatus.VERIFIED],
        SkillStatus.VERIFIED: [SkillStatus.STABLE, SkillStatus.DRAFT],
        SkillStatus.STABLE: [SkillStatus.DEPRECATED],
        SkillStatus.DEPRECATED: [SkillStatus.STABLE, SkillStatus.ARCHIVED],
        SkillStatus.ARCHIVED: [],
    }

    @classmethod
    def can_transition(
        cls, from_status: SkillStatus, to_status: SkillStatus
    ) -> bool:
        """Check if a lifecycle transition is allowed.

        Args:
            from_status: The current skill status.
            to_status: The desired target status.

        Returns:
            True if the transition is valid, False otherwise.
        """
        allowed = cls.TRANSITIONS.get(from_status, [])
        return to_status in allowed

    @classmethod
    def transition(
        cls,
        skill: SkillDefinition,
        to_status: SkillStatus,
        reason: str = "",
        triggered_by: str = "system",
    ) -> SkillDefinition:
        """Transition a skill to a new lifecycle status.

        Records the transition in the skill's lifecycle_history and updates
        the updated_at timestamp.

        Args:
            skill: The skill definition to transition.
            to_status: The target lifecycle status.
            reason: Human-readable reason for the transition.
            triggered_by: Identifier of who/what triggered the transition.

        Returns:
            The skill definition with updated status and history.

        Raises:
            SkillLifecycleError: If the transition is not allowed.
        """
        if skill is None:
            raise SkillNotFoundError(
                "Cannot transition None skill",
                code="SKILL_NOT_FOUND",
            )

        if not cls.can_transition(skill.status, to_status):
            allowed = cls.TRANSITIONS.get(skill.status, [])
            raise SkillLifecycleError(
                f"Invalid lifecycle transition: {skill.status.value} → "
                f"{to_status.value}. Allowed transitions: "
                f"{[s.value for s in allowed]}",
                code="SKILL_LIFECYCLE_INVALID",
                details={
                    "skill_id": str(skill.skill_id),
                    "name": skill.name,
                    "from_status": skill.status.value,
                    "to_status": to_status.value,
                },
            )

        transition_record = SkillLifecycleTransition(
            from_status=skill.status,
            to_status=to_status,
            reason=reason,
            timestamp=datetime.now(timezone.utc),
            triggered_by=triggered_by,
        )

        skill.status = to_status
        skill.lifecycle_history.append(transition_record)
        skill.updated_at = datetime.now(timezone.utc)

        logger.info(
            "skill_lifecycle_transition",
            skill_id=str(skill.skill_id),
            name=skill.name,
            from_status=transition_record.from_status.value,
            to_status=to_status.value,
            reason=reason,
        )

        return skill
```

## 文件路径: src/myharness/skill/registry.py

```python
"""Skill discovery and matching.

The SkillRegistry finds the best skill for a given requirement by matching
capabilities and ranking by status, confidence, and usage.
"""

from __future__ import annotations

from typing import Any

import structlog

from myharness.schema.skill import SkillDefinition, SkillStatus
from myharness.skill.store import SkillStore

logger = structlog.get_logger(__name__)

# Status priority: higher = preferred
_STATUS_PRIORITY: dict[SkillStatus, int] = {
    SkillStatus.STABLE: 100,
    SkillStatus.VERIFIED: 80,
    SkillStatus.TESTING: 60,
    SkillStatus.DRAFT: 40,
    SkillStatus.DEPRECATED: 20,
    SkillStatus.ARCHIVED: 0,
}


class SkillRegistry:
    """Skill discovery and matching.

    Finds the best skill for a given requirement by matching capabilities
    and ranking candidates by status priority, confidence, and usage count.

    Prefers STABLE > VERIFIED > TESTING > DRAFT. ARCHIVED and DEPRECATED
    skills are excluded from matching by default.
    """

    def __init__(self, store: SkillStore) -> None:
        """Initialize the skill registry.

        Args:
            store: The skill store to query for skills.
        """
        self._store = store

    async def find_best_match(
        self,
        capability: str,
        requirements: dict | None = None,
    ) -> SkillDefinition | None:
        """Find the best matching skill for a given requirement.

        Ranking criteria (in order):
        1. Status priority (STABLE > VERIFIED > TESTING > DRAFT)
        2. Confidence score
        3. Usage count

        ARCHIVED skills are excluded. DEPRECATED skills are only
        considered if no other candidates exist.

        Args:
            capability: The capability name to match.
            requirements: Optional additional requirements dict.

        Returns:
            The best matching SkillDefinition, or None if no match found.
        """
        candidates = await self._store.list_by_capability(capability)

        if not candidates:
            logger.debug(
                "no_skills_for_capability",
                capability=capability,
            )
            return None

        # Filter and score candidates
        active_candidates = [
            s for s in candidates
            if s.status not in {SkillStatus.ARCHIVED}
        ]

        if not active_candidates:
            logger.debug(
                "no_active_skills_for_capability",
                capability=capability,
                total_candidates=len(candidates),
            )
            return None

        # If only deprecated candidates, use them as fallback
        non_deprecated = [
            s for s in active_candidates
            if s.status != SkillStatus.DEPRECATED
        ]
        pool = non_deprecated if non_deprecated else active_candidates

        # Apply additional requirement filtering
        if requirements:
            pool = self._filter_by_requirements(pool, requirements)

        if not pool:
            return None

        # Score and rank
        scored = self._rank_candidates(pool)
        best = scored[0]

        logger.info(
            "best_skill_match",
            capability=capability,
            skill_id=str(best.skill_id),
            name=best.name,
            version=best.version,
            status=best.status.value,
            confidence=best.confidence,
        )

        return best

    async def find_by_capability(self, capability: str) -> list[SkillDefinition]:
        """Find all skills providing a specific capability.

        Results are sorted by status priority and confidence.

        Args:
            capability: The capability name to match.

        Returns:
            A list of matching skill definitions, ranked by relevance.
        """
        candidates = await self._store.list_by_capability(capability)
        return self._rank_candidates(candidates)

    async def discover(self) -> list[SkillDefinition]:
        """List all available skills.

        Only returns non-archived skills, sorted by status priority.

        Returns:
            A list of all available skill definitions.
        """
        all_skills = await self._store.list_all()
        available = [
            s for s in all_skills
            if s.status != SkillStatus.ARCHIVED
        ]
        return self._rank_candidates(available)

    @staticmethod
    def _rank_candidates(
        candidates: list[SkillDefinition],
    ) -> list[SkillDefinition]:
        """Rank candidates by status priority, confidence, and usage.

        Args:
            candidates: List of skill candidates.

        Returns:
            Sorted list, best first.
        """
        return sorted(
            candidates,
            key=lambda s: (
                _STATUS_PRIORITY.get(s.status, 0),
                s.confidence,
                s.usage_count,
            ),
            reverse=True,
        )

    @staticmethod
    def _filter_by_requirements(
        candidates: list[SkillDefinition],
        requirements: dict[str, Any],
    ) -> list[SkillDefinition]:
        """Filter candidates by additional requirements.

        Currently supports filtering by:
            - driver_type: Match the skill's driver type.
            - min_confidence: Minimum confidence threshold.
            - tags: Skill must have all specified tags.

        Args:
            candidates: List of skill candidates.
            requirements: Dict of requirement filters.

        Returns:
            Filtered list of candidates.
        """
        result = list(candidates)

        if "driver_type" in requirements:
            dt = requirements["driver_type"]
            result = [s for s in result if s.driver_type == dt]

        if "min_confidence" in requirements:
            min_conf = float(requirements["min_confidence"])
            result = [s for s in result if s.confidence >= min_conf]

        if "tags" in requirements:
            required_tags = set(requirements["tags"])
            result = [
                s for s in result
                if required_tags.issubset(set(s.tags))
            ]

        return result
```

## 文件路径: src/myharness/skill/storage.py

```python
"""Low-level JSON file operations for skill persistence.

Skills are stored as JSON files in a directory hierarchy:
    {skills_dir}/{skill_name}/{version}.json

The JSON file is the source of truth for each skill version.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

from myharness.core.exceptions import SkillError, SkillNotFoundError
from myharness.schema.skill import SkillDefinition

logger = structlog.get_logger(__name__)


class SkillStorage:
    """Low-level JSON file operations for skill definitions.

    Handles reading and writing individual skill JSON files. Does not
    implement business logic — that belongs in SkillStore.
    """

    def __init__(self, skills_dir: Path) -> None:
        """Initialize the skill storage layer.

        Args:
            skills_dir: Root directory where skill JSON files are stored.
        """
        self._skills_dir = skills_dir
        self._skills_dir.mkdir(parents=True, exist_ok=True)

    def _skill_path(self, name: str, version: str) -> Path:
        """Get the file path for a skill name/version pair."""
        safe_name = name.replace("/", "_").replace("\\", "_")
        return self._skills_dir / safe_name / f"{version}.json"

    def _skill_dir(self, name: str) -> Path:
        """Get the directory for a skill name."""
        safe_name = name.replace("/", "_").replace("\\", "_")
        return self._skills_dir / safe_name

    async def save(self, skill: SkillDefinition) -> None:
        """Save a skill definition to its JSON file.

        Args:
            skill: The skill definition to persist.

        Raises:
            SkillError: If the file cannot be written.
        """
        skill.updated_at = datetime.now(timezone.utc)
        file_path = self._skill_path(skill.name, skill.version)
        file_path.parent.mkdir(parents=True, exist_ok=True)

        try:
            data = skill.model_dump(mode="json")
            file_path.write_text(
                json.dumps(data, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )
            logger.debug(
                "skill_saved",
                skill_id=str(skill.skill_id),
                name=skill.name,
                version=skill.version,
                path=str(file_path),
            )
        except OSError as exc:
            raise SkillError(
                f"Failed to save skill {skill.name}@{skill.version}: {exc}",
                code="SKILL_SAVE_ERROR",
                details={"path": str(file_path)},
                cause=exc,
            ) from exc

    async def load(self, skill_id: str) -> SkillDefinition | None:
        """Load a skill definition by its skill_id.

        This scans all skill directories to find the matching skill_id.
        For direct lookups, prefer load_by_name_version.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            The skill definition, or None if not found.
        """
        if not self._skills_dir.exists():
            return None

        for skill_dir in self._skills_dir.iterdir():
            if not skill_dir.is_dir():
                continue
            for json_file in skill_dir.glob("*.json"):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    if data.get("skill_id") == skill_id:
                        return SkillDefinition(**data)
                except (json.JSONDecodeError, KeyError, ValueError):
                    logger.warning(
                        "corrupt_skill_file", path=str(json_file)
                    )
        return None

    async def load_by_name_version(
        self, name: str, version: str
    ) -> SkillDefinition | None:
        """Load a skill definition by name and version.

        Args:
            name: The skill name.
            version: The semantic version string.

        Returns:
            The skill definition, or None if not found.
        """
        file_path = self._skill_path(name, version)
        if not file_path.exists():
            return None

        try:
            data = json.loads(file_path.read_text(encoding="utf-8"))
            return SkillDefinition(**data)
        except (json.JSONDecodeError, KeyError, ValueError) as exc:
            logger.warning(
                "corrupt_skill_file",
                path=str(file_path),
                error=str(exc),
            )
            return None

    async def list_versions(self, name: str) -> list[str]:
        """List all available versions for a skill name.

        Args:
            name: The skill name.

        Returns:
            A list of version strings, sorted by semantic version.
        """
        skill_dir = self._skill_dir(name)
        if not skill_dir.exists():
            return []

        versions: list[str] = []
        for json_file in sorted(skill_dir.glob("*.json")):
            stem = json_file.stem
            if stem not in versions:
                versions.append(stem)

        return self._sort_semver(versions)

    async def list_all(self) -> list[SkillDefinition]:
        """List all skill definitions from all directories.

        Returns:
            A list of all persisted skill definitions.
        """
        if not self._skills_dir.exists():
            return []

        skills: list[SkillDefinition] = []
        for skill_dir in sorted(self._skills_dir.iterdir()):
            if not skill_dir.is_dir():
                continue
            for json_file in sorted(skill_dir.glob("*.json")):
                try:
                    data = json.loads(json_file.read_text(encoding="utf-8"))
                    skills.append(SkillDefinition(**data))
                except (json.JSONDecodeError, KeyError, ValueError) as exc:
                    logger.warning(
                        "corrupt_skill_file",
                        path=str(json_file),
                        error=str(exc),
                    )

        return skills

    async def delete(self, skill_id: str) -> None:
        """Delete a skill definition from storage.

        Args:
            skill_id: The unique skill identifier.

        Raises:
            SkillNotFoundError: If the skill is not found.
        """
        skill = await self.load(skill_id)
        if skill is None:
            raise SkillNotFoundError(
                f"Skill not found: {skill_id}",
                code="SKILL_NOT_FOUND",
                details={"skill_id": skill_id},
            )

        file_path = self._skill_path(skill.name, skill.version)
        if file_path.exists():
            file_path.unlink()
            logger.debug(
                "skill_deleted",
                skill_id=str(skill.skill_id),
                name=skill.name,
                version=skill.version,
            )

        # Clean up empty directories
        skill_dir = self._skill_dir(skill.name)
        if skill_dir.exists() and not any(skill_dir.iterdir()):
            skill_dir.rmdir()

    @staticmethod
    def _sort_semver(versions: list[str]) -> list[str]:
        """Sort version strings semantically (newest first)."""

        def _key(v: str) -> tuple[int, ...]:
            try:
                return tuple(int(x) for x in v.split("."))
            except ValueError:
                return (0, 0, 0)

        return sorted(versions, key=_key, reverse=True)
```

## 文件路径: src/myharness/skill/store.py

```python
"""Persistent skill storage using JSON files (source of truth).

Implements the SkillStoreInterface with file-based persistence.
Skills are organized as:
    {skills_dir}/{name}/{version}.json
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import structlog

from myharness.core.exceptions import (
    SkillError,
    SkillLifecycleError,
    SkillNotFoundError,
    SkillValidationError,
)
from myharness.schema.skill import SkillDefinition, SkillStatus
from myharness.skill.interface import SkillStoreInterface
from myharness.skill.lifecycle import SkillLifecycle
from myharness.skill.storage import SkillStorage
from myharness.skill.validator import SkillValidator

logger = structlog.get_logger(__name__)


class SkillStore(SkillStoreInterface):
    """Persistent skill storage using JSON files (source of truth).

    Implements all SkillStoreInterface methods with file-based persistence.
    Uses SkillStorage for low-level file I/O and SkillValidator for
    validation before persistence.
    """

    def __init__(self, skills_dir: Path) -> None:
        """Initialize the skill store.

        Args:
            skills_dir: Root directory for skill JSON files.
        """
        self._skills_dir = Path(skills_dir)
        self._storage = SkillStorage(self._skills_dir)
        logger.info("skill_store_initialized", skills_dir=str(self._skills_dir))

    async def register(self, skill: SkillDefinition) -> SkillDefinition:
        """Register a new skill definition.

        Validates the skill before persisting it to storage.

        Args:
            skill: The skill definition to register.

        Returns:
            The registered skill definition.

        Raises:
            SkillValidationError: If the skill fails validation.
            SkillError: If a skill with the same name and version already exists.
        """
        # Validate the skill
        errors = SkillValidator.validate(skill)
        if errors:
            raise SkillValidationError(
                f"Skill validation failed for '{skill.name}': {'; '.join(errors)}",
                code="SKILL_VALIDATION_ERROR",
                details={"name": skill.name, "errors": errors},
            )

        # Check for duplicates
        existing = await self._storage.load_by_name_version(
            skill.name, skill.version
        )
        if existing is not None:
            raise SkillError(
                f"Skill '{skill.name}' version '{skill.version}' already exists",
                code="SKILL_ALREADY_EXISTS",
                details={
                    "name": skill.name,
                    "version": skill.version,
                    "existing_skill_id": str(existing.skill_id),
                },
            )

        await self._storage.save(skill)
        logger.info(
            "skill_registered",
            skill_id=str(skill.skill_id),
            name=skill.name,
            version=skill.version,
        )
        return skill

    async def get(self, skill_id: str) -> SkillDefinition | None:
        """Retrieve a skill by its unique identifier.

        Args:
            skill_id: The unique skill identifier.

        Returns:
            The skill definition, or None if not found.
        """
        return await self._storage.load(skill_id)

    async def get_by_name(
        self, name: str, version: str | None = None
    ) -> SkillDefinition | None:
        """Retrieve a skill by name, optionally filtered by version.

        If version is None, returns the latest version.

        Args:
            name: The skill name.
            version: Optional semantic version to match.

        Returns:
            The skill definition, or None if not found.
        """
        if version is not None:
            return await self._storage.load_by_name_version(name, version)

        # Get latest version
        versions = await self._storage.list_versions(name)
        if not versions:
            return None
        return await self._storage.load_by_name_version(name, versions[0])

    async def list_all(self) -> list[SkillDefinition]:
        """List all registered skill definitions.

        Returns:
            A list of all skill definitions.
        """
        return await self._storage.list_all()

    async def list_by_capability(self, capability: str) -> list[SkillDefinition]:
        """List skills that provide a specific capability.

        Args:
            capability: The capability name to filter by (case-insensitive).

        Returns:
            A list of matching skill definitions.
        """
        all_skills = await self._storage.list_all()
        query = capability.lower()
        return [
            s for s in all_skills
            if query in s.capability.lower()
        ]

    async def list_by_status(self, status: SkillStatus) -> list[SkillDefinition]:
        """List skills filtered by lifecycle status.

        Args:
            status: The skill status to filter by.

        Returns:
            A list of skills with the given status.
        """
        all_skills = await self._storage.list_all()
        return [s for s in all_skills if s.status == status]

    async def search(self, query: str, top_k: int = 10) -> list[SkillDefinition]:
        """Search skills by text matching on name and description.

        Uses simple case-insensitive substring matching. Results are
        ranked by relevance: exact name match > name contains > description
        contains. Within each tier, higher confidence ranks higher.

        Args:
            query: The search query string.
            top_k: Maximum number of results to return.

        Returns:
            A list of matching skill definitions, ranked by relevance.
        """
        all_skills = await self._storage.list_all()
        query_lower = query.lower()

        if not query_lower:
            return sorted(
                all_skills,
                key=lambda s: s.confidence,
                reverse=True,
            )[:top_k]

        # Scoring: name match = 100, description match = 50, tag match = 30
        scored: list[tuple[int, SkillDefinition]] = []
        for skill in all_skills:
            score = 0
            name_lower = skill.name.lower()
            if name_lower == query_lower:
                score = 100
            elif query_lower in name_lower:
                score = 80
            if query_lower in skill.description.lower():
                score += 50
            for tag in skill.tags:
                if query_lower in tag.lower():
                    score += 30
            if score > 0:
                scored.append((score, skill))

        # Sort by score descending, then by confidence descending
        scored.sort(key=lambda x: (x[0], x[1].confidence), reverse=True)
        return [s[1] for s in scored[:top_k]]

    async def update(self, skill: SkillDefinition) -> SkillDefinition:
        """Update an existing skill definition.

        Args:
            skill: The skill definition with updated fields.

        Returns:
            The updated skill definition.

        Raises:
            SkillNotFoundError: If the skill does not exist.
            SkillValidationError: If the updated skill fails validation.
        """
        existing = await self._storage.load(str(skill.skill_id))
        if existing is None:
            raise SkillNotFoundError(
                f"Skill not found: {skill.skill_id}",
                code="SKILL_NOT_FOUND",
                details={"skill_id": str(skill.skill_id)},
            )

        # Validate the updated skill
        errors = SkillValidator.validate(skill)
        if errors:
            raise SkillValidationError(
                f"Skill validation failed for '{skill.name}': {'; '.join(errors)}",
                code="SKILL_VALIDATION_ERROR",
                details={"name": skill.name, "errors": errors},
            )

        await self._storage.save(skill)
        logger.info(
            "skill_updated",
            skill_id=str(skill.skill_id),
            name=skill.name,
            version=skill.version,
        )
        return skill

    async def change_status(
        self, skill_id: str, new_status: SkillStatus, reason: str = ""
    ) -> SkillDefinition:
        """Change the lifecycle status of a skill.

        Uses SkillLifecycle to validate and record the transition.

        Args:
            skill_id: The skill identifier.
            new_status: The target lifecycle status.
            reason: The reason for the status change.

        Returns:
            The updated skill definition.

        Raises:
            SkillNotFoundError: If the skill does not exist.
            SkillLifecycleError: If the transition is invalid.
        """
        skill = await self._storage.load(skill_id)
        if skill is None:
            raise SkillNotFoundError(
                f"Skill not found: {skill_id}",
                code="SKILL_NOT_FOUND",
                details={"skill_id": skill_id},
            )

        updated = SkillLifecycle.transition(skill, new_status, reason)
        await self._storage.save(updated)
        return updated

    async def deprecate(self, skill_id: str, reason: str) -> SkillDefinition:
        """Deprecate a skill, marking it as no longer recommended.

        Args:
            skill_id: The skill identifier.
            reason: The reason for deprecation.

        Returns:
            The updated skill definition.
        """
        return await self.change_status(skill_id, SkillStatus.DEPRECATED, reason)

    async def archive(self, skill_id: str) -> SkillDefinition:
        """Archive a skill, moving it to a terminal state.

        Args:
            skill_id: The skill identifier.

        Returns:
            The updated skill definition.

        Raises:
            SkillLifecycleError: If the skill cannot be archived from
                its current status (only DEPRECATED can be archived).
        """
        return await self.change_status(
            skill_id, SkillStatus.ARCHIVED, "Archived"
        )

    async def get_version_history(self, name: str) -> list[SkillDefinition]:
        """Get all versions of a skill, ordered newest first.

        Args:
            name: The skill name.

        Returns:
            A list of all versions of the skill.
        """
        versions = await self._storage.list_versions(name)
        skills: list[SkillDefinition] = []
        for version in versions:
            skill = await self._storage.load_by_name_version(name, version)
            if skill is not None:
                skills.append(skill)
        return skills

    async def get_stats(self) -> dict[str, Any]:
        """Get aggregate statistics about the skill store.

        Returns:
            A dictionary with keys:
                - total_skills: Total number of skill definitions.
                - by_status: Count of skills per lifecycle status.
                - by_driver_type: Count of skills per driver type.
                - total_usage: Sum of all usage counts.
                - avg_confidence: Average confidence across all skills.
        """
        all_skills = await self._storage.list_all()

        by_status: dict[str, int] = {}
        by_driver_type: dict[str, int] = {}
        total_usage = 0
        total_confidence = 0.0

        for skill in all_skills:
            status_key = skill.status.value
            by_status[status_key] = by_status.get(status_key, 0) + 1

            driver_key = skill.driver_type or "unknown"
            by_driver_type[driver_key] = by_driver_type.get(driver_key, 0) + 1

            total_usage += skill.usage_count
            total_confidence += skill.confidence

        return {
            "total_skills": len(all_skills),
            "by_status": by_status,
            "by_driver_type": by_driver_type,
            "total_usage": total_usage,
            "avg_confidence": (
                total_confidence / len(all_skills) if all_skills else 0.0
            ),
        }
```

## 文件路径: src/myharness/skill/validator.py

```python
"""Skill definition validation.

Validates skill definitions and proposals against the schema requirements
before they are persisted or executed.
"""

from __future__ import annotations

import structlog

from myharness.schema.skill import (
    SkillDefinition,
    SkillProposal,
    SkillStatus,
)

logger = structlog.get_logger(__name__)


class SkillValidator:
    """Validates skill definitions and proposals.

    All methods are static — validation is a pure function with no side effects.
    """

    @staticmethod
    def validate(skill: SkillDefinition) -> list[str]:
        """Validate a skill definition.

        Checks structural integrity, required fields, parameter types,
        and logical consistency.

        Args:
            skill: The skill definition to validate.

        Returns:
            A list of validation error messages. Empty list means valid.
        """
        errors: list[str] = []

        # Required fields
        if not skill.name or not skill.name.strip():
            errors.append("Skill name is required and must not be empty")
        elif len(skill.name) > 128:
            errors.append(f"Skill name exceeds 128 characters: '{skill.name}'")

        if not skill.version:
            errors.append("Skill version is required")
        elif not SkillValidator._is_valid_semver(skill.version):
            errors.append(f"Invalid semver format: '{skill.version}'")

        # Status must be a valid enum value
        if skill.status not in SkillStatus:
            errors.append(f"Invalid skill status: '{skill.status}'")

        # Capability should be specified for non-draft skills
        if skill.status != SkillStatus.DRAFT and not skill.capability:
            errors.append(
                f"Skill '{skill.name}' in status '{skill.status}' "
                "must have a capability defined"
            )

        # Validate parameters
        param_names: set[str] = set()
        for param in skill.parameters:
            if not param.name:
                errors.append("Skill parameter has empty name")
                continue
            if param.name in param_names:
                errors.append(f"Duplicate parameter name: '{param.name}'")
            param_names.add(param.name)

            valid_types = {"string", "int", "float", "bool", "array", "object"}
            if param.type not in valid_types:
                errors.append(
                    f"Parameter '{param.name}' has invalid type '{param.type}'. "
                    f"Must be one of: {valid_types}"
                )

            if param.required and param.default is not None:
                logger.debug(
                    "required_param_with_default",
                    skill_name=skill.name,
                    param_name=param.name,
                )

        # Confidence must be in range
        if not 0.0 <= skill.confidence <= 1.0:
            errors.append(
                f"Confidence must be between 0.0 and 1.0, got {skill.confidence}"
            )

        # Timeout must be non-negative
        if skill.timeout_seconds < 0:
            errors.append(
                f"Timeout must be non-negative, got {skill.timeout_seconds}"
            )

        # Driver type must be a known value
        known_drivers = {
            "api", "browser", "database", "robot",
            "mcp", "computer", "iot",
        }
        if skill.driver_type and skill.driver_type not in known_drivers:
            errors.append(
                f"Unknown driver type '{skill.driver_type}'. "
                f"Must be one of: {known_drivers}"
            )

        # Action template should not be empty for verified/stable skills
        if skill.status in {SkillStatus.VERIFIED, SkillStatus.STABLE}:
            if not skill.action_template:
                errors.append(
                    f"Skill '{skill.name}' is {skill.status.value} but has "
                    "no action template defined"
                )

        return errors

    @staticmethod
    def validate_proposal(proposal: SkillProposal) -> list[str]:
        """Validate a skill proposal.

        Args:
            proposal: The skill proposal to validate.

        Returns:
            A list of validation error messages. Empty list means valid.
        """
        errors: list[str] = []

        if not proposal.suggested_name or not proposal.suggested_name.strip():
            errors.append("Proposal must have a suggested name")
        elif len(proposal.suggested_name) > 128:
            errors.append(
                f"Proposal name exceeds 128 characters: '{proposal.suggested_name}'"
            )

        if not proposal.description:
            errors.append("Proposal should have a description")

        known_drivers = {
            "api", "browser", "database", "robot",
            "mcp", "computer", "iot",
        }
        if proposal.driver_type not in known_drivers:
            errors.append(
                f"Unknown driver type '{proposal.driver_type}'. "
                f"Must be one of: {known_drivers}"
            )

        if not 0.0 <= proposal.confidence_estimate <= 1.0:
            errors.append(
                f"Confidence estimate must be between 0.0 and 1.0, "
                f"got {proposal.confidence_estimate}"
            )

        if not proposal.reasoning:
            errors.append("Proposal must include reasoning for why the skill should be created")

        return errors

    @staticmethod
    def _is_valid_semver(version: str) -> bool:
        """Check if a version string follows semantic versioning."""
        parts = version.split(".")
        if len(parts) != 3:
            return False
        for part in parts:
            if not part.isdigit():
                return False
        return True
```
