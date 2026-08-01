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
