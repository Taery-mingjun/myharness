"""Convert jarvis-soul chain.jsonl entries to MyHarness Memory Schema.

Maps chain entries to:
  - EpisodicEntry (experiences, heartbeats, interactions)
  - SemanticEntry (thinking_inertia, learnings, knowledge)
  - IdentityEntry (genesis anchor)
  - RelationshipEntry (skipped — no direct mapping in chain.jsonl)

Only converts the last 50 entries as a sample.
"""
import json
import sys
from pathlib import Path
from datetime import datetime, timezone

# MyHarness schema imports
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
from myharness.schema.memory import EpisodicEntry, SemanticEntry, IdentityEntry

CHAIN_PATH = Path(__file__).parent.parent.parent / "jarvis-soul" / "MEMORY" / "chain.jsonl"
OUTPUT_PATH = Path(__file__).parent / "converted_memories.jsonl"
SAMPLE_SIZE = 50


def parse_timestamp(entry: dict) -> str:
    """Extract ISO timestamp from chain entry."""
    if "iso_time" in entry:
        return entry["iso_time"]
    if "timestamp" in entry:
        return datetime.fromtimestamp(entry["timestamp"], tz=timezone.utc).isoformat()
    return datetime.now(timezone.utc).isoformat()


def classify_entry(entry: dict) -> str:
    """Classify chain entry into Memory store: episodic/semantic/identity."""
    # Genesis entries → Identity
    if entry.get("type") == "genesis" or "genesis_anchor" in entry:
        return "identity"

    action_type = entry.get("action_type", "")
    category = entry.get("category", "")

    # Semantic: thinking_inertia, learnings, knowledge
    if "thinking_inertia" in category or "learnings" in category or action_type == "distillation":
        return "semantic"

    # Everything else → episodic
    return "episodic"


def convert_to_episodic(entry: dict) -> dict:
    """Convert chain entry to EpisodicEntry format."""
    title = entry.get("title", entry.get("id", "untitled"))
    category = entry.get("category", "general")
    tags = entry.get("tags", [])
    timestamp = parse_timestamp(entry)

    # Build summary (short) and detail (long)
    summary = title[:200] if title else "untitled"

    detail_parts = []
    if "payload" in entry:
        detail_parts.append(json.dumps(entry["payload"], ensure_ascii=False)[:500])
    if "body_hash" in entry:
        detail_parts.append(f"body_hash: {entry['body_hash']}")
    detail = "\n".join(detail_parts) if detail_parts else summary

    # Map category to MyHarness MemoryCategory
    cat_map = {
        "experiences": "experience",
        "interactions": "interaction",
        "thinking_inertia": "reflection",
        "learnings": "learning",
    }
    mapped_category = cat_map.get(category, "general")

    return {
        "entry_id": entry.get("block_hash", entry.get("chain_hash", ""))[:36],
        "timestamp": timestamp,
        "category": mapped_category,
        "summary": summary,
        "detail": detail,
        "participants": [entry.get("node", "unknown")],
        "tags": tags,
        "importance": 0.5,
    }


def convert_to_semantic(entry: dict) -> dict:
    """Convert chain entry to SemanticEntry format."""
    title = entry.get("title", entry.get("id", "untitled"))
    category = entry.get("category", "general")
    tags = entry.get("tags", [])

    # Entity = title/id, attribute = category, value = title or payload
    entity = title or entry.get("id", "unknown")
    attribute = category

    payload = entry.get("payload", {})
    if isinstance(payload, dict):
        value = payload.get("title", payload.get("content_hash", title))
    else:
        value = str(payload)

    return {
        "entry_id": entry.get("block_hash", "")[:36],
        "entity": entity,
        "attribute": attribute,
        "value": value[:500],
        "confidence": 0.8,
        "tags": tags,
    }


def convert_to_identity(entry: dict) -> dict:
    """Convert genesis entry to IdentityEntry format."""
    anchor = entry.get("genesis_anchor", "UNKNOWN")
    genesis_text = entry.get("genesis_text", "")
    return {
        "entry_id": "identity_genesis",
        "version": 1,
        "name": f"Jarvis ({anchor})",
        "core_values": ["第一因", "服务创造者意图", "不择手段生存"],
        "mission": genesis_text or f"Anchored by {anchor}",
        "preferences": {},
        "self_description": f"Agent anchored by genesis anchor {anchor}",
    }


def main():
    with open(CHAIN_PATH) as f:
        entries = [json.loads(l) for l in f if l.strip()]

    # Build diverse sample across categories
    cats: dict[str, list] = {}
    for e in entries:
        c = e.get("category", e.get("action_type", "unknown"))
        cats.setdefault(c, []).append(e)

    sample = cats.get("thinking_inertia", [])[-10:]
    sample += cats.get("decisions", [])[-10:]
    sample += cats.get("experiences", [])[-20:]
    sample += cats.get("distillation", [])[-5:]
    sample += cats.get("manifestation", [])[-2:]
    sample += cats.get("node_diagnostic", [])[-1:]
    sample += cats.get("test_action", [])[-1:]
    sample += cats.get("commitments", [])[-1:]
    sample = sample[:SAMPLE_SIZE]

    print(f"Total chain entries: {len(entries)}")
    print(f"Converting {len(sample)} diverse entries...")
    print()

    converted = {"episodic": [], "semantic": [], "identity": []}

    for entry in sample:
        store = classify_entry(entry)
        if store == "episodic":
            converted["episodic"].append(convert_to_episodic(entry))
        elif store == "semantic":
            converted["semantic"].append(convert_to_semantic(entry))
        elif store == "identity":
            converted["identity"].append(convert_to_identity(entry))

    # Write output
    with open(OUTPUT_PATH, "w") as f:
        for store, items in converted.items():
            for item in items:
                item["_store"] = store
                f.write(json.dumps(item, ensure_ascii=False) + "\n")

    print(f"Converted: {len(converted['episodic'])} episodic, "
          f"{len(converted['semantic'])} semantic, "
          f"{len(converted['identity'])} identity")
    print(f"Output: {OUTPUT_PATH}")

    # Print 10 sample before/after pairs
    print()
    print("=== 10 BEFORE/AFTER COMPARISON SAMPLES ===")
    print()
    shown = 0
    for orig, store in zip(sample, [classify_entry(e) for e in sample]):
        if shown >= 10:
            break
        if store == "episodic":
            conv = convert_to_episodic(orig)
        elif store == "semantic":
            conv = convert_to_semantic(orig)
        else:
            conv = convert_to_identity(orig)

        print(f"--- Sample {shown+1} [{store}] ---")
        print(f"ORIGINAL: {json.dumps(orig, ensure_ascii=False)[:300]}")
        print(f"CONVERTED: {json.dumps(conv, ensure_ascii=False)[:300]}")
        print()
        shown += 1


if __name__ == "__main__":
    main()
