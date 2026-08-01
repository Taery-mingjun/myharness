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
