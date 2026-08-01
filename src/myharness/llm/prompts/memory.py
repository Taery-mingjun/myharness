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
