"""Deep coverage for skill store / registry / validator (P1-D).

Targets the branches missed by the original suite: validation edge
cases, duplicate/not-found paths, status transitions, search ranking,
registry requirement filtering, and stats.
"""

from __future__ import annotations

import pytest

from myharness.core.exceptions import (
    SkillError,
    SkillLifecycleError,
    SkillNotFoundError,
    SkillValidationError,
)
from myharness.schema.skill import (
    SkillDefinition,
    SkillParameter,
    SkillProposal,
    SkillStatus,
)
from myharness.skill.lifecycle import SkillLifecycle
from myharness.skill.registry import SkillRegistry
from myharness.skill.validator import SkillValidator


def _skill(**overrides) -> SkillDefinition:
    base = dict(
        name="walk",
        version="1.0.0",
        description="Walk forward",
        capability="mobility.walk",
        driver_type="robot",
        action_template={"action": "walk"},
        status=SkillStatus.DRAFT,
    )
    base.update(overrides)
    return SkillDefinition(**base)


# ── Validator: definition edge cases ───────────────────────────────────


class TestValidatorDefinition:
    def test_name_too_long(self):
        errors = SkillValidator.validate(_skill(name="n" * 129))
        assert any("exceeds 128" in e for e in errors)

    def test_missing_version(self):
        errors = SkillValidator.validate(_skill(version=""))
        assert any("version is required" in e for e in errors)

    def test_invalid_semver(self):
        errors = SkillValidator.validate(_skill(version="1.0"))
        assert any("semver" in e.lower() for e in errors)

    def test_invalid_status_bypassing_pydantic(self):
        raw = SkillDefinition.model_construct(name="x", version="1.0.0", status="bogus")
        errors = SkillValidator.validate(raw)
        assert any("status" in e for e in errors)

    def test_non_draft_requires_capability(self):
        errors = SkillValidator.validate(
            _skill(status=SkillStatus.STABLE, capability="")
        )
        assert any("capability" in e for e in errors)

    def test_parameter_validation(self):
        empty_name = SkillParameter.model_construct(name="", type="string")
        errors = SkillValidator.validate(
            _skill(
                parameters=[
                    empty_name,
                    SkillParameter(name="dup", type="int"),
                    SkillParameter(name="dup", type="float"),
                    SkillParameter(name="bad", type="datetime"),
                ]
            )
        )
        assert any("empty name" in e for e in errors)
        assert any("Duplicate parameter" in e for e in errors)
        assert any("invalid type" in e for e in errors)

    def test_unknown_driver_type(self):
        errors = SkillValidator.validate(_skill(driver_type="quantum"))
        assert any("Unknown driver type" in e for e in errors)

    def test_verified_requires_action_template(self):
        errors = SkillValidator.validate(
            _skill(status=SkillStatus.VERIFIED, action_template={})
        )
        assert any("action template" in e for e in errors)

    def test_confidence_out_of_range_bypassing_pydantic(self):
        raw = SkillDefinition.model_construct(
            name="x", version="1.0.0", confidence=1.5
        )
        errors = SkillValidator.validate(raw)
        assert any("Confidence" in e for e in errors)

    def test_negative_timeout_bypassing_pydantic(self):
        raw = SkillDefinition.model_construct(
            name="x", version="1.0.0", timeout_seconds=-1
        )
        errors = SkillValidator.validate(raw)
        assert any("Timeout" in e for e in errors)


# ── Validator: action boundary (protocol 14.3) ─────────────────────────


class TestActionBoundary:
    def test_empty_allowed_actions_entry(self):
        errors = SkillValidator.validate(_skill(allowed_actions=["walk", ""]))
        assert any("empty entry" in e for e in errors)

    def test_duplicate_allowed_actions(self):
        errors = SkillValidator.validate(_skill(allowed_actions=["walk", "walk"]))
        assert any("twice" in e for e in errors)

    def test_wildcard_mixed_with_named_actions(self):
        errors = SkillValidator.validate(_skill(allowed_actions=["*", "walk"]))
        assert any("wildcard" in e for e in errors)

    def test_template_action_outside_allowlist(self):
        errors = SkillValidator.validate(
            _skill(allowed_actions=["run"], action_template={"action": "walk"})
        )
        assert any("could never execute" in e for e in errors)

    def test_template_action_inside_allowlist_ok(self):
        errors = SkillValidator.validate(
            _skill(allowed_actions=["walk"], action_template={"action": "walk"})
        )
        assert errors == []


# ── Validator: proposals (Learning output) ─────────────────────────────


class TestValidatorProposal:
    def test_valid_proposal(self):
        errors = SkillValidator.validate_proposal(
            SkillProposal(
                suggested_name="walk",
                description="Walk forward",
                reasoning="Observed successful walking 5 times",
            )
        )
        assert errors == []

    def test_missing_name(self):
        raw = SkillProposal.model_construct(suggested_name="", reasoning="r")
        errors = SkillValidator.validate_proposal(raw)
        assert any("suggested name" in e for e in errors)

    def test_name_too_long(self):
        errors = SkillValidator.validate_proposal(
            SkillProposal(suggested_name="n" * 129, reasoning="r")
        )
        assert any("128" in e for e in errors)

    def test_missing_description(self):
        errors = SkillValidator.validate_proposal(
            SkillProposal(suggested_name="walk", reasoning="r")
        )
        assert any("description" in e.lower() for e in errors)

    def test_unknown_driver_type(self):
        errors = SkillValidator.validate_proposal(
            SkillProposal(suggested_name="walk", driver_type="quantum", reasoning="r")
        )
        assert any("Unknown driver type" in e for e in errors)

    def test_confidence_out_of_range(self):
        raw = SkillProposal.model_construct(
            suggested_name="walk", confidence_estimate=2.0, reasoning="r"
        )
        errors = SkillValidator.validate_proposal(raw)
        assert any("Confidence" in e for e in errors)

    def test_missing_reasoning(self):
        errors = SkillValidator.validate_proposal(
            SkillProposal(suggested_name="walk", description="d")
        )
        assert any("reasoning" in e.lower() for e in errors)

    def test_semver_helper(self):
        assert SkillValidator._is_valid_semver("1.2.3")
        assert not SkillValidator._is_valid_semver("1.2")
        assert not SkillValidator._is_valid_semver("a.b.c")


# ── Store: error paths & queries ───────────────────────────────────────


class TestStoreErrors:
    async def test_register_duplicate_version(self, skill_store):
        await skill_store.register(_skill())
        with pytest.raises(SkillError, match="already exists"):
            await skill_store.register(_skill())

    async def test_register_invalid_skill(self, skill_store):
        with pytest.raises(SkillValidationError, match="validation failed"):
            await skill_store.register(_skill(driver_type="quantum"))

    async def test_update_missing_skill(self, skill_store):
        with pytest.raises(SkillNotFoundError):
            await skill_store.update(_skill(name="ghost"))

    async def test_change_status_missing_skill(self, skill_store):
        with pytest.raises(SkillNotFoundError):
            await skill_store.change_status("missing-id", SkillStatus.DEPRECATED)

    async def test_deprecate_then_archive(self, skill_store):
        skill = await skill_store.register(_skill())
        await skill_store.change_status(skill.skill_id, SkillStatus.TESTING)
        await skill_store.change_status(skill.skill_id, SkillStatus.VERIFIED)
        await skill_store.change_status(skill.skill_id, SkillStatus.STABLE)
        deprecated = await skill_store.deprecate(skill.skill_id, "obsolete")
        assert deprecated.status == SkillStatus.DEPRECATED
        archived = await skill_store.archive(skill.skill_id)
        assert archived.status == SkillStatus.ARCHIVED

    async def test_archive_from_draft_rejected(self, skill_store):
        # DRAFT can be archived per schema transitions, but SkillLifecycle
        # (the service-level authority) requires the STABLE → DEPRECATED
        # chain; DRAFT → ARCHIVED is not a service-level transition.
        skill = await skill_store.register(_skill())
        with pytest.raises(SkillLifecycleError):
            await skill_store.archive(skill.skill_id)

    async def test_lifecycle_rejects_archive_directly(self):
        skill = _skill()
        with pytest.raises(SkillLifecycleError):
            SkillLifecycle.transition(skill, SkillStatus.ARCHIVED)

    async def test_update_existing_skill(self, skill_store):
        skill = await skill_store.register(_skill())
        skill.description = "Updated description"
        updated = await skill_store.update(skill)
        assert updated.description == "Updated description"
        fetched = await skill_store.get(str(skill.skill_id))
        assert fetched.description == "Updated description"


class TestStoreQueries:
    async def test_get_by_name_with_version(self, skill_store):
        await skill_store.register(_skill(version="1.0.0"))
        await skill_store.register(_skill(version="2.0.0"))
        v2 = await skill_store.get_by_name("walk", version="2.0.0")
        assert v2.version == "2.0.0"
        latest = await skill_store.get_by_name("walk")
        assert latest.version == "2.0.0"

    async def test_get_by_name_missing(self, skill_store):
        assert await skill_store.get_by_name("nope") is None

    async def test_list_by_capability_case_insensitive(self, skill_store):
        await skill_store.register(_skill(capability="Mobility.Walk"))
        results = await skill_store.list_by_capability("mobility.walk")
        assert len(results) == 1

    async def test_list_by_status(self, skill_store):
        await skill_store.register(_skill(status=SkillStatus.DRAFT))
        await skill_store.register(
            _skill(name="run", status=SkillStatus.STABLE, capability="mobility.run")
        )
        stable = await skill_store.list_by_status(SkillStatus.STABLE)
        assert [s.name for s in stable] == ["run"]

    async def test_search_empty_query_ranks_by_confidence(self, skill_store):
        await skill_store.register(_skill(name="low", confidence=0.3))
        await skill_store.register(_skill(name="high", confidence=0.9))
        results = await skill_store.search("")
        assert [s.name for s in results] == ["high", "low"]

    async def test_search_ranked_tiers(self, skill_store):
        await skill_store.register(_skill(name="walk", tags=[]))
        await skill_store.register(
            _skill(name="speedwalk", capability="mobility.speed", tags=["walk"])
        )
        results = await skill_store.search("walk")
        # speedwalk: name-contains (80) + tag (30) = 110 > exact name (100)
        assert [s.name for s in results] == ["speedwalk", "walk"]

    async def test_search_top_k(self, skill_store):
        for i in range(5):
            await skill_store.register(
                _skill(name=f"skill{i}", confidence=0.5 + i * 0.1)
            )
        results = await skill_store.search("skill", top_k=2)
        assert len(results) == 2

    async def test_version_history(self, skill_store):
        await skill_store.register(_skill(version="1.0.0"))
        await skill_store.register(_skill(version="1.1.0"))
        history = await skill_store.get_version_history("walk")
        versions = sorted(s.version for s in history)
        assert versions == ["1.0.0", "1.1.0"]

    async def test_stats(self, skill_store):
        await skill_store.register(_skill(status=SkillStatus.DRAFT))
        await skill_store.register(
            _skill(
                name="run",
                status=SkillStatus.STABLE,
                capability="mobility.run",
                confidence=1.0,
            )
        )
        stats = await skill_store.get_stats()
        assert stats["total_skills"] == 2
        assert stats["by_status"]["draft"] == 1
        assert stats["by_status"]["stable"] == 1
        assert stats["by_driver_type"]["robot"] == 2
        assert stats["total_usage"] == 0
        assert stats["avg_confidence"] == pytest.approx(0.75)

    async def test_stats_empty_store(self, skill_store):
        stats = await skill_store.get_stats()
        assert stats["total_skills"] == 0
        assert stats["avg_confidence"] == 0.0


# ── Registry: matching semantics (P6) ──────────────────────────────────


async def _register_verified(skill_store, **overrides) -> SkillDefinition:
    skill = await skill_store.register(_skill(**overrides))
    await skill_store.change_status(skill.skill_id, SkillStatus.TESTING)
    return await skill_store.change_status(skill.skill_id, SkillStatus.VERIFIED)


class TestRegistryMatching:
    async def test_requirements_filter_driver_type(self, skill_store):
        await _register_verified(skill_store, driver_type="robot")
        registry = SkillRegistry(skill_store)
        match = await registry.find_best_match(
            "mobility.walk", requirements={"driver_type": "api"}
        )
        assert match is None

    async def test_requirements_min_confidence(self, skill_store):
        await _register_verified(skill_store, confidence=0.4)
        registry = SkillRegistry(skill_store)
        match = await registry.find_best_match(
            "mobility.walk", requirements={"min_confidence": 0.8}
        )
        assert match is None

    async def test_requirements_tags(self, skill_store):
        await _register_verified(skill_store, tags=["indoors"])
        registry = SkillRegistry(skill_store)
        match = await registry.find_best_match(
            "mobility.walk", requirements={"tags": ["indoors", "safe"]}
        )
        assert match is None

    async def test_deprecated_fallback(self, skill_store):
        skill = await skill_store.register(_skill())
        await skill_store.change_status(skill.skill_id, SkillStatus.TESTING)
        await skill_store.change_status(skill.skill_id, SkillStatus.VERIFIED)
        await skill_store.change_status(skill.skill_id, SkillStatus.STABLE)
        await skill_store.change_status(skill.skill_id, SkillStatus.DEPRECATED)
        registry = SkillRegistry(skill_store)
        match = await registry.find_best_match("mobility.walk")
        assert match is not None
        assert match.status == SkillStatus.DEPRECATED

    async def test_all_archived_returns_none(self, skill_store):
        skill = await skill_store.register(_skill())
        await skill_store.change_status(skill.skill_id, SkillStatus.TESTING)
        await skill_store.change_status(skill.skill_id, SkillStatus.VERIFIED)
        await skill_store.change_status(skill.skill_id, SkillStatus.STABLE)
        await skill_store.change_status(skill.skill_id, SkillStatus.DEPRECATED)
        await skill_store.change_status(skill.skill_id, SkillStatus.ARCHIVED)
        registry = SkillRegistry(skill_store)
        assert await registry.find_best_match("mobility.walk") is None

    async def test_find_by_capability_ranks(self, skill_store):
        await skill_store.register(_skill(name="low", confidence=0.2))
        await skill_store.register(_skill(name="high", confidence=0.9))
        registry = SkillRegistry(skill_store)
        results = await registry.find_by_capability("mobility.walk")
        assert [s.name for s in results] == ["high", "low"]

    async def test_discover_excludes_archived(self, skill_store):
        await skill_store.register(_skill(name="keep"))
        await skill_store.register(
            _skill(name="gone", capability="mobility.gone")
        )
        # archive 'gone' through the full chain
        gone = await skill_store.get_by_name("gone")
        for target in (
            SkillStatus.TESTING,
            SkillStatus.VERIFIED,
            SkillStatus.STABLE,
            SkillStatus.DEPRECATED,
            SkillStatus.ARCHIVED,
        ):
            await skill_store.change_status(gone.skill_id, target)
        registry = SkillRegistry(skill_store)
        names = {s.name for s in await registry.discover()}
        assert "keep" in names
        assert "gone" not in names


# ── Schema-level action allowlist (security-critical, protocol 14.3) ──


class TestActionAllowlist:
    def test_permit_action_explicit_allowlist(self):
        skill = _skill(allowed_actions=["walk", "run"])
        assert skill.permits_action("walk")
        assert not skill.permits_action("jump")

    def test_wildcard_grants_all(self):
        skill = _skill(allowed_actions=["*"])
        assert skill.permits_action("anything")

    def test_template_actions_fallback(self):
        skill = _skill(allowed_actions=[], action_template={"actions": ["a", "b"]})
        assert skill.permits_action("a")
        assert not skill.permits_action("c")

    def test_single_template_action_fallback(self):
        skill = _skill(allowed_actions=[], action_template={"action": "walk"})
        assert skill.permits_action("walk")
        assert not skill.permits_action("run")

    def test_skill_name_fallback(self):
        # No allowlist and no template: the skill name itself is the default
        # allowlist entry (conservative default keeps old skills working).
        skill = _skill(name="walk", allowed_actions=[])
        assert skill.permits_action("walk")
        assert not skill.permits_action("grab")

    def test_empty_action_never_permitted(self):
        skill = _skill(allowed_actions=["*"])
        assert not skill.permits_action("")
        assert not skill.permits_action("   ")

    def test_duck_typed_skill_evaluated(self):
        # The guard evaluates duck-typed skills without silently waving
        # them through (resolve_allowed_actions accepts any shape).
        class DuckSkill:
            name = "quack"
            allowed_actions = []

        assert duck_action_is_permitted(DuckSkill(), "quack")
        assert not duck_action_is_permitted(DuckSkill(), "bite")


def duck_action_is_permitted(skill, action: str) -> bool:
    from myharness.schema.skill import action_is_permitted

    return action_is_permitted(skill, action)
