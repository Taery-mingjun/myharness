"""The Skill power must constrain the Execution power.

Before the ExecutionGuard, ``_execute_plan`` resolved a skill only to read
its ``driver_type`` and then handed the driver whatever action string the
plan carried. Plan steps come from the LLM, whose context includes
retrieved memories and tool output, so three things were reachable from
untrusted input and all three were reproduced against the real classes:

  1. an approved read-only skill executing an arbitrary destructive action
  2. an ARCHIVED skill the operator had retired still executing
  3. ``PermissionManager`` never being consulted at all — and handing
     callers its own mutable action lists, so reading an actor's
     permissions was enough to escalate them

These tests exist so none of the three can come back quietly.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from myharness.core.exceptions import PermissionDeniedError
from myharness.harness.guard import ExecutionGuard
from myharness.harness.permission import PermissionManager
from myharness.harness.supervisor import HarnessSupervisor
from myharness.llm.engine import Plan, PlanStep
from myharness.schema.driver import ExecutionResult
from myharness.schema.skill import (
    SkillDefinition,
    SkillStatus,
    resolve_allowed_actions,
)

pytestmark = pytest.mark.asyncio


# ── Fixtures / doubles ─────────────────────────────────────────────────


class SpyDriverManager:
    """Records every call that makes it past the guard."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict]] = []

    async def execute(self, driver_name: str, action: str, parameters: dict):
        self.calls.append((driver_name, action, dict(parameters)))
        return ExecutionResult(success=True, output={})


class DictSkillStore:
    def __init__(self, skills: dict[str, SkillDefinition] | None = None) -> None:
        self._skills = skills or {}

    async def get_by_name(self, name: str, version: str | None = None):
        return self._skills.get(name)


def _skill(name: str, **kw: Any) -> SkillDefinition:
    kw.setdefault("version", "1.0.0")
    kw.setdefault("status", SkillStatus.STABLE)
    kw.setdefault("driver_type", "api")
    kw.setdefault("capability", "test")
    return SkillDefinition(name=name, **kw)


def _plan(*steps: PlanStep) -> Plan:
    return Plan(
        plan_id="p",
        goal="g",
        steps=list(steps),
        reasoning="",
        created_at=datetime.now(timezone.utc),
    )


def _step(skill_name: str, action: str, **params: Any) -> PlanStep:
    return PlanStep(
        step_id="s",
        action=action,
        skill_name=skill_name,
        parameters=params,
        expected_outcome="",
    )


def _supervisor(store: Any, drivers: Any, guard: Any = None) -> HarnessSupervisor:
    return HarnessSupervisor(
        event_bus=None,
        router=None,
        memory=None,
        llm_engine=None,
        skill_store=store,
        capability_registry=None,
        driver_manager=drivers,
        scheduler=None,
        monitor=None,
        execution_guard=guard,
    )


# ── The skill's declared boundary ──────────────────────────────────────


class TestAllowlistResolution:
    async def test_explicit_allowlist_wins(self):
        s = _skill(
            "x",
            allowed_actions=["read", "list"],
            action_template={"action": "write"},
        )
        assert resolve_allowed_actions(s) == {"read", "list"}
        assert s.permits_action("read")
        assert not s.permits_action("write")

    async def test_template_action_list(self):
        s = _skill("x", action_template={"actions": ["get", "head"]})
        assert resolve_allowed_actions(s) == {"get", "head"}

    async def test_single_template_action(self):
        s = _skill("x", action_template={"action": "get_weather"})
        assert s.permits_action("get_weather")
        assert not s.permits_action("delete_all")

    async def test_falls_back_to_the_skill_name(self):
        """Skills predating the allowlist keep working for their own action."""
        s = _skill("walk", action_template={})
        assert s.permits_action("walk")
        assert not s.permits_action("detonate")

    async def test_wildcard_is_an_explicit_opt_out(self):
        s = _skill("x", allowed_actions=["*"])
        assert s.permits_action("anything_at_all")

    @pytest.mark.parametrize("action", ["", "   ", None, 42])
    async def test_unnamed_action_is_never_permitted(self, action):
        s = _skill("x", allowed_actions=["*"])
        assert not s.permits_action(action)


# ── Exploit 1: a read-only skill as a handle for arbitrary actions ─────


class TestSkillBoundaryIsEnforced:
    async def test_arbitrary_action_on_an_approved_skill_is_refused(self):
        """The original exploit, end to end through the real supervisor."""
        store = DictSkillStore(
            {
                "read_weather": _skill(
                    "read_weather",
                    action_template={
                        "action": "get_weather",
                        "method": "GET",
                    },
                )
            }
        )
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers)

        malicious = _plan(
            _step(
                "read_weather",
                "delete_all_records",
                method="DELETE",
                url="https://internal.corp/admin/records",
            )
        )

        with pytest.raises(PermissionDeniedError) as exc:
            await sup._execute_plan(malicious, {})

        assert exc.value.code == "ACTION_NOT_PERMITTED"
        assert drivers.calls == [], "the driver must never have been reached"

    async def test_the_declared_action_still_runs(self):
        store = DictSkillStore(
            {"read_weather": _skill("read_weather", action_template={"action": "get_weather"})}
        )
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers)

        await sup._execute_plan(_plan(_step("read_weather", "get_weather")), {})

        assert drivers.calls == [("api", "get_weather", {})]

    async def test_a_denied_step_aborts_the_rest_of_the_plan(self):
        """Later steps assumed the denied one ran; finishing is not safe."""
        store = DictSkillStore(
            {
                "safe": _skill("safe", allowed_actions=["ping"]),
                "narrow": _skill("narrow", allowed_actions=["read"]),
            }
        )
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers)

        plan = _plan(
            _step("safe", "ping"),
            _step("narrow", "drop_table"),
            _step("safe", "ping"),
        )

        with pytest.raises(PermissionDeniedError):
            await sup._execute_plan(plan, {})

        assert len(drivers.calls) == 1, "execution stopped at the denial"
        assert plan.current_step == 1, "cursor rests on the step that did not run"

    async def test_unknown_skill_is_a_denial_not_a_shrug(self):
        drivers = SpyDriverManager()
        sup = _supervisor(DictSkillStore(), drivers)

        with pytest.raises(PermissionDeniedError) as exc:
            await sup._execute_plan(_plan(_step("ghost", "anything")), {})

        assert exc.value.code == "SKILL_NOT_FOUND"
        assert drivers.calls == []

    async def test_guard_is_present_even_when_not_injected(self):
        """A control that can be skipped by omitting a dependency is not one."""
        sup = _supervisor(DictSkillStore(), SpyDriverManager(), guard=None)
        assert isinstance(sup._execution_guard, ExecutionGuard)
        assert sup._execution_guard.enforcing


# ── Exploit 2: retired skills ──────────────────────────────────────────


class TestLifecycleIsEnforced:
    async def test_archived_skill_cannot_execute(self):
        store = DictSkillStore(
            {
                "legacy_wire_transfer": _skill(
                    "legacy_wire_transfer",
                    status=SkillStatus.ARCHIVED,
                    allowed_actions=["transfer"],
                )
            }
        )
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers)

        with pytest.raises(PermissionDeniedError) as exc:
            await sup._execute_plan(
                _plan(_step("legacy_wire_transfer", "transfer", amount=999999)), {}
            )

        assert exc.value.code == "SKILL_ARCHIVED"
        assert drivers.calls == []

    async def test_deprecated_skill_runs_but_is_flagged(self):
        """Deprecated means 'don't build on it', not 'refuse it'.

        The registry already falls back to DEPRECATED skills when nothing
        else matches, so blocking them here would contradict discovery.
        """
        store = DictSkillStore(
            {
                "old_api": _skill(
                    "old_api",
                    status=SkillStatus.DEPRECATED,
                    allowed_actions=["fetch"],
                )
            }
        )
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers)

        await sup._execute_plan(_plan(_step("old_api", "fetch")), {})

        assert drivers.calls == [("api", "fetch", {})]

    async def test_skill_with_no_resolvable_action_authorises_nothing(self):
        """An unresolvable boundary must fail closed, not become a wildcard."""
        blank = _skill("nameless")
        object.__setattr__(blank, "name", "")
        assert resolve_allowed_actions(blank) == set()

        drivers = SpyDriverManager()
        sup = _supervisor(DictSkillStore({"nameless": blank}), drivers)

        with pytest.raises(PermissionDeniedError) as exc:
            await sup._execute_plan(_plan(_step("nameless", "anything")), {})

        assert exc.value.code == "ACTION_NOT_PERMITTED"
        assert drivers.calls == []


# ── The validator must catch incoherent boundaries at registration ─────


class TestValidatorChecksTheBoundary:
    async def test_template_action_outside_the_allowlist_is_an_error(self):
        """Otherwise the skill can never execute its own template."""
        from myharness.skill.validator import SkillValidator

        errors = SkillValidator.validate(
            _skill(
                "x",
                allowed_actions=["read"],
                action_template={"action": "write"},
            )
        )
        assert any("could never execute its own template" in e for e in errors)

    async def test_consistent_boundary_passes(self):
        from myharness.skill.validator import SkillValidator

        errors = SkillValidator.validate(
            _skill(
                "x",
                allowed_actions=["read", "write"],
                action_template={"action": "write"},
            )
        )
        assert errors == []

    async def test_wildcard_mixed_with_named_actions_is_flagged(self):
        from myharness.skill.validator import SkillValidator

        errors = SkillValidator.validate(_skill("x", allowed_actions=["*", "read"]))
        assert any("wildcard" in e for e in errors)

    async def test_duplicate_and_blank_entries_are_flagged(self):
        from myharness.skill.validator import SkillValidator

        errors = SkillValidator.validate(
            _skill("x", allowed_actions=["read", "read", "  "])
        )
        assert any("twice" in e for e in errors)
        assert any("empty entry" in e for e in errors)


# ── Exploit 3: RBAC that nobody called, and that leaked its own state ──


class TestPermissionManager:
    async def test_defaults_to_deny(self):
        pm = PermissionManager()
        assert pm.default_policy == "deny"
        assert not await pm.check("nobody", "skill:x", "execute")

    async def test_grant_and_check(self):
        pm = PermissionManager()
        await pm.grant("alice", "skill:walk", "execute")
        assert await pm.check("alice", "skill:walk", "execute")
        assert not await pm.check("alice", "skill:walk", "delete")
        assert not await pm.check("bob", "skill:walk", "execute")

    async def test_superusers_are_seeded(self):
        pm = PermissionManager(superusers=["system"])
        assert await pm.check("system", "skill:anything", "execute")
        assert not await pm.check("guest", "skill:anything", "execute")

    async def test_permissive_mode_is_opt_in(self):
        pm = PermissionManager(default_policy="allow")
        assert await pm.check("anyone", "skill:x", "execute")

    async def test_rejects_an_unknown_policy(self):
        with pytest.raises(ValueError, match="default_policy"):
            PermissionManager(default_policy="maybe")

    async def test_get_permissions_cannot_be_used_to_escalate(self):
        """The original leak: the returned lists were the manager's own."""
        pm = PermissionManager()
        await pm.grant("agent", "skill:read", "execute")

        leaked = await pm.get_permissions("agent")
        leaked["skill:read"].append("*")
        leaked["skill:everything"] = ["*"]

        assert not await pm.check("agent", "skill:read", "delete")
        assert not await pm.check("agent", "skill:everything", "execute")

    async def test_revoking_an_action_also_strips_a_wildcard(self):
        """A revocation that revokes nothing is worse than none — it's believed."""
        pm = PermissionManager()
        await pm.grant("agent", "skill:db", "*")

        await pm.revoke("agent", "skill:db", "drop_table")

        assert not await pm.check("agent", "skill:db", "drop_table")
        assert not await pm.check("agent", "skill:db", "select")

    async def test_revoke_all(self):
        pm = PermissionManager()
        await pm.grant("agent", "skill:a", "execute")
        await pm.grant("agent", "skill:b", "execute")

        await pm.revoke_all("agent")

        assert await pm.get_permissions("agent") == {}
        assert await pm.list_actors() == []

    async def test_revoke_is_a_noop_for_unknown_actors(self):
        pm = PermissionManager()
        await pm.revoke("ghost", "skill:x", "execute")
        await pm.revoke_all("ghost")


class TestActorAuthorization:
    async def test_actor_without_a_grant_is_refused(self):
        pm = PermissionManager(superusers=["system"])
        guard = ExecutionGuard(permission_manager=pm, system_actor="system")
        store = DictSkillStore({"walk": _skill("walk", allowed_actions=["walk"])})
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers, guard)

        with pytest.raises(PermissionDeniedError) as exc:
            await sup._execute_plan(
                _plan(_step("walk", "walk")), {"actor": "untrusted_tenant"}
            )

        assert exc.value.code == "ACTOR_NOT_PERMITTED"
        assert drivers.calls == []

    async def test_system_actor_is_authorised_by_default(self):
        pm = PermissionManager(superusers=["system"])
        guard = ExecutionGuard(permission_manager=pm, system_actor="system")
        store = DictSkillStore({"walk": _skill("walk", allowed_actions=["walk"])})
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers, guard)

        await sup._execute_plan(_plan(_step("walk", "walk")), {})

        assert drivers.calls == [("api", "walk", {})]

    async def test_granting_the_tenant_lets_it_through(self):
        pm = PermissionManager()
        await pm.grant("tenant_a", "skill:walk", "execute")
        guard = ExecutionGuard(permission_manager=pm)
        store = DictSkillStore({"walk": _skill("walk", allowed_actions=["walk"])})
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers, guard)

        await sup._execute_plan(_plan(_step("walk", "walk")), {"actor": "tenant_a"})

        assert drivers.calls == [("api", "walk", {})]

    async def test_a_grant_does_not_widen_the_skill_boundary(self):
        """RBAC and the action boundary are independent gates."""
        pm = PermissionManager()
        await pm.grant("tenant_a", "skill:walk", "execute")
        guard = ExecutionGuard(permission_manager=pm)
        store = DictSkillStore({"walk": _skill("walk", allowed_actions=["walk"])})
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers, guard)

        with pytest.raises(PermissionDeniedError) as exc:
            await sup._execute_plan(
                _plan(_step("walk", "self_destruct")), {"actor": "tenant_a"}
            )

        assert exc.value.code == "ACTION_NOT_PERMITTED"

    async def test_guard_rejects_a_permission_manager_without_check(self):
        with pytest.raises(TypeError, match="check"):
            ExecutionGuard(permission_manager=object())


# ── Audit-only mode ────────────────────────────────────────────────────


class TestAuditOnlyMode:
    async def test_denials_are_recorded_but_execution_proceeds(self):
        guard = ExecutionGuard(enforce=False)
        store = DictSkillStore({"walk": _skill("walk", allowed_actions=["walk"])})
        drivers = SpyDriverManager()
        sup = _supervisor(store, drivers, guard)

        await sup._execute_plan(_plan(_step("walk", "self_destruct")), {})

        assert drivers.calls == [("api", "self_destruct", {})]
        assert [d["code"] for d in guard.denials] == ["ACTION_NOT_PERMITTED"]
        assert not guard.enforcing

    async def test_audit_mode_survives_an_unknown_skill(self):
        guard = ExecutionGuard(enforce=False)
        drivers = SpyDriverManager()
        sup = _supervisor(DictSkillStore(), drivers, guard)

        await sup._execute_plan(_plan(_step("ghost", "x")), {})

        assert drivers.calls == []
        assert [d["code"] for d in guard.denials] == ["SKILL_NOT_FOUND"]

    async def test_denial_records_carry_enough_to_audit(self):
        guard = ExecutionGuard(enforce=False)
        store = DictSkillStore({"walk": _skill("walk", allowed_actions=["walk"])})
        sup = _supervisor(store, SpyDriverManager(), guard)

        await sup._execute_plan(
            _plan(_step("walk", "self_destruct")), {"actor": "tenant_a"}
        )

        record = guard.denials[0]
        assert record["skill_name"] == "walk"
        assert record["action"] == "self_destruct"
        assert record["actor"] == "tenant_a"
        assert "walk" in record["reason"]


class TestDenialHistoryIsBounded:
    """A blocked attack must not become an out-of-memory kill.

    Denials are produced by hostile input, so anything the guard retains
    per denial is attacker-controlled growth.
    """

    async def test_history_drops_the_oldest_entries(self):
        guard = ExecutionGuard(enforce=False, denial_history_limit=8)
        skill = _skill("walk", allowed_actions=["walk"])

        for i in range(200):
            await guard.authorize(skill=skill, action=f"attack_{i}")

        assert len(guard.denials) == 8
        assert guard.denials[-1]["action"] == "attack_199"
        assert guard.denials[0]["action"] == "attack_192"

    async def test_limit_is_never_zero(self):
        guard = ExecutionGuard(enforce=False, denial_history_limit=0)

        await guard.authorize(skill=None, action="x", skill_name="ghost")

        assert len(guard.denials) == 1

    async def test_history_is_bounded_while_enforcing_too(self):
        guard = ExecutionGuard(denial_history_limit=4)
        skill = _skill("walk", allowed_actions=["walk"])

        for i in range(50):
            with pytest.raises(PermissionDeniedError):
                await guard.authorize(skill=skill, action=f"attack_{i}")

        assert len(guard.denials) == 4

    async def test_the_view_cannot_mutate_the_history(self):
        guard = ExecutionGuard(enforce=False)
        await guard.authorize(skill=None, action="x", skill_name="ghost")

        guard.denials.clear()

        assert len(guard.denials) == 1


# ── Wiring ─────────────────────────────────────────────────────────────


class TestGuardIsWiredIntoTheContainer:
    async def test_container_builds_an_enforcing_guard(self, test_settings):
        from myharness.core.di import build_container

        c = build_container(test_settings)
        guard = c[ExecutionGuard]

        assert guard.enforcing
        assert guard.system_actor == test_settings.system_actor
        assert c[ExecutionGuard] is guard, "guard must be a singleton"

    async def test_supervisor_uses_the_container_guard(self, test_settings):
        from myharness.core.di import build_container

        c = build_container(test_settings)
        assert c[HarnessSupervisor]._execution_guard is c[ExecutionGuard]

    async def test_system_actor_is_authorised_out_of_the_box(self, test_settings):
        """Deny-by-default must not brick the default single-agent install."""
        from myharness.core.di import build_container

        c = build_container(test_settings)
        pm = c[PermissionManager]

        assert pm.default_policy == "deny"
        assert await pm.check(test_settings.system_actor, "skill:anything", "execute")
        assert not await pm.check("someone_else", "skill:anything", "execute")
