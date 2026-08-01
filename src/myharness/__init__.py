"""MyHarness — Cognitive Operating System for AI Agents.

A production-grade implementation of the four-power separation architecture:
  - LLM Engine: Pure cognitive computation (no state)
  - Memory System: Persistent identity, episodic, semantic, and relationship memory
  - Skill Store: Versioned, parameterized executable capability templates
  - Execution Layer: Unified driver protocol for hardware/platform abstraction

Key Principles:
  P0. LLM is the Cognitive Runtime, not the Identity Container
  P1. Single Cognitive Engine
  P2. Separation of Concerns (Compute / Memory / Skill / Execution)
  P3. Identity Externalization
  P4. Event-Driven Architecture
  P5. Skill Accumulation
  P6. Minimal Runtime Computation
  P7. Protocol over Implementation
  P8. Replaceable Compute
  P9. Source / Derived Data Separation
"""

__version__ = "0.1.0"
__author__ = "Taerymingjun"
