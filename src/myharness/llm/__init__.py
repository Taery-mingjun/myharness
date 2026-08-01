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
