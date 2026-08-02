"""Runtime layer tests — the cognitive event loop, state, and wiring.

This whole package used to sit at 0% coverage while being architecturally
load-bearing (P4: one event loop, no mode switching). What was hiding in
there:

  * ``EventLoop.step()`` called ``event_bus.get_event()``, a method the
    EventBus never had. Every iteration bailed out instantly, so the loop
    spun at ~97% of a CPU core and processed zero events, silently.
  * ``EventLoop.step()`` did ``await event_bus.queue_size()`` on what is a
    plain ``int`` property — ``TypeError``, swallowed by a blanket except.
  * ``HarnessSupervisor.run_cognitive_loop()`` was a second, divergent copy
    of the same broken loop with no yield point at all. Calling it starved
    the entire asyncio event loop; the process had to be SIGKILLed.
  * Queued events reached ``publish()`` directly, bypassing the Router, so
    routing rules were decorative.

The tests below pin every one of those down.
"""

from __future__ import annotations

import asyncio
import time

import pytest

from myharness.bus.dispatcher import EventBus
from myharness.bus.router import RouteRule, Router
from myharness.core.exceptions import EventBusError
from myharness.runtime.loop import EventLoop
from myharness.runtime.state import RuntimeState
from myharness.schema.event import BaseEvent, EventType, UserMessageEvent

pytestmark = pytest.mark.asyncio


def _cpu_time() -> float:
    # time.process_time(): cross-platform CPU time (user + system), replaces
    # the Unix-only resource.getrusage() used previously.
    return time.process_time()


def _msg(i: int = 0) -> UserMessageEvent:
    return UserMessageEvent(source="test", payload={"content": f"msg-{i}"})


@pytest.fixture
def state() -> RuntimeState:
    return RuntimeState()


@pytest.fixture
def loop(event_bus, router, state) -> EventLoop:
    return EventLoop(event_bus, router, state, poll_timeout=0.02)


# ── Collaborator contract: fail loud, never degrade silently ───────────


class TestContractValidation:
    async def test_rejects_bus_without_get_event(self, router, state):
        class BusWithoutGetEvent:
            async def publish(self, event):
                return []

        with pytest.raises(TypeError, match="get_event"):
            EventLoop(BusWithoutGetEvent(), router, state)

    async def test_rejects_router_without_route(self, event_bus, state):
        class RouterWithoutRoute:
            pass

        with pytest.raises(TypeError, match="route"):
            EventLoop(event_bus, RouterWithoutRoute(), state)

    async def test_rejects_synchronous_get_event(self, router, state):
        class SyncBus:
            def get_event(self, timeout=0.1):
                return None

            async def publish(self, event):
                return []

        with pytest.raises(TypeError, match="must be async"):
            EventLoop(SyncBus(), router, state)

    async def test_rejects_none_collaborators(self, event_bus, router, state):
        with pytest.raises(TypeError, match="event_bus"):
            EventLoop(None, router, state)
        with pytest.raises(TypeError, match="router"):
            EventLoop(event_bus, None, state)

    async def test_rejects_zero_poll_timeout(self, event_bus, router, state):
        # A zero timeout turns get_event into a non-blocking poll, which is
        # exactly how the original loop burned a core.
        with pytest.raises(ValueError, match="poll_timeout"):
            EventLoop(event_bus, router, state, poll_timeout=0)

    async def test_bus_rejects_zero_timeout_get_event(self, event_bus):
        with pytest.raises(ValueError, match="busy-spin"):
            await event_bus.get_event(timeout=0)


# ── Events actually get processed ──────────────────────────────────────


class TestEventProcessing:
    async def test_processes_every_enqueued_event(self, event_bus, loop):
        for i in range(5):
            await event_bus.enqueue(_msg(i))

        await loop.start()
        try:
            await _wait_until(lambda: loop.event_count == 5, timeout=3.0)
        finally:
            await loop.stop()

        assert loop.event_count == 5
        assert event_bus.queue_size == 0

    async def test_step_works_without_start(self, event_bus, loop):
        """Manual stepping must not require the background loop.

        The old implementation early-returned unless start() had been
        called, so the documented "manual stepping for debugging" was
        impossible without also racing the auto loop.
        """
        await event_bus.enqueue(_msg())

        assert await loop.step() is True
        assert loop.event_count == 1

    async def test_step_returns_false_when_idle(self, loop):
        assert await loop.step() is False
        assert loop.event_count == 0

    async def test_routes_through_router_when_rule_matches(
        self, event_bus, router, loop
    ):
        router.add_rule(
            RouteRule(
                rule_id="cognitive",
                event_types=[EventType.USER_MESSAGE],
                target="llm.engine.think",
            )
        )
        seen: list[BaseEvent] = []

        async def handler(event):
            seen.append(event)

        event_bus.subscribe(EventType.USER_MESSAGE, handler)
        await event_bus.enqueue(_msg())

        assert await loop.step() is True
        assert len(seen) == 1
        # Router enriches metadata; proves we went through routing, not raw publish.
        assert seen[0].metadata.get("routed_by") == "cognitive"
        assert seen[0].metadata.get("target") == "llm.engine.think"

    async def test_unrouted_events_still_reach_subscribers(
        self, event_bus, loop
    ):
        """Routing rules are an overlay, not a gate.

        With no rules registered, Router.route() matches nothing. If the
        loop treated that as "done", every queued event would be silently
        black-holed the moment the cognitive loop was switched on.
        """
        seen: list[BaseEvent] = []

        async def handler(event):
            seen.append(event)

        event_bus.subscribe(EventType.USER_MESSAGE, handler)
        await event_bus.enqueue(_msg())

        assert await loop.step() is True
        assert len(seen) == 1
        assert "routed_by" not in seen[0].metadata

    async def test_preserves_fifo_order(self, event_bus, loop):
        seen: list[int] = []

        async def handler(event):
            seen.append(int(event.payload.content.split("-")[1]))

        event_bus.subscribe(EventType.USER_MESSAGE, handler)
        for i in range(8):
            await event_bus.enqueue(_msg(i))

        for _ in range(8):
            await loop.step()

        assert seen == list(range(8))


# ── Resource-behaviour regressions ─────────────────────────────────────


class TestNoBusySpin:
    async def test_idle_loop_does_not_burn_cpu(self, loop):
        """Regression: the idle loop used to consume ~97% of a core."""
        await loop.start()
        try:
            cpu_before = _cpu_time()
            await asyncio.sleep(0.5)
            cpu_used = _cpu_time() - cpu_before
        finally:
            await loop.stop()

        assert cpu_used < 0.10, (
            f"idle loop burned {cpu_used:.2f}s CPU in 0.5s wall "
            "— the poll timeout is not throttling it"
        )

    async def test_running_loop_does_not_starve_other_tasks(self, loop):
        """Regression: the old supervisor loop never yielded at all.

        A plain ``asyncio.sleep`` in a sibling task never resumed, and even
        ``asyncio.wait_for`` could not fire — the process needed SIGKILL.
        """
        await loop.start()
        try:
            started = time.monotonic()
            await asyncio.wait_for(asyncio.sleep(0.2), timeout=3.0)
            elapsed = time.monotonic() - started
        finally:
            await loop.stop()

        assert elapsed < 1.0, f"sibling task was starved for {elapsed:.2f}s"

    async def test_failing_bus_does_not_spin(self, router, state):
        """A bus that raises on every fetch must back off, not hot-loop."""
        calls = 0

        class BrokenBus:
            async def get_event(self, timeout=0.1):
                nonlocal calls
                calls += 1
                raise RuntimeError("bus is down")

            async def publish(self, event):
                return []

        broken = EventLoop(BrokenBus(), router, state, poll_timeout=0.05)
        await broken.start()
        try:
            await asyncio.sleep(0.3)
        finally:
            await broken.stop()

        # With a 0.05s backoff, ~6 attempts in 0.3s. Anything in the
        # thousands means it is spinning.
        assert calls < 50, f"failing bus polled {calls} times in 0.3s"
        assert broken.error_count == calls


# ── One poisoned event must not kill the loop ──────────────────────────


class TestErrorContainment:
    async def test_survives_handler_exception_and_keeps_going(
        self, event_bus, state
    ):
        boom_count = 0

        class ExplodingRouter:
            async def route(self, event):
                nonlocal boom_count
                if event.payload.content == "msg-0":
                    boom_count += 1
                    raise RuntimeError("handler exploded")
                return ["ok"]

        loop = EventLoop(event_bus, ExplodingRouter(), state, poll_timeout=0.02)

        await event_bus.enqueue(_msg(0))  # explodes
        await event_bus.enqueue(_msg(1))  # must still be processed

        assert await loop.step() is False  # first event failed
        assert await loop.step() is True  # loop survived

        assert boom_count == 1
        assert loop.error_count == 1
        assert loop.event_count == 1

    async def test_errors_surface_in_state(self, event_bus, state):
        class ExplodingRouter:
            async def route(self, event):
                raise RuntimeError("nope")

        loop = EventLoop(event_bus, ExplodingRouter(), state, poll_timeout=0.02)
        await event_bus.enqueue(_msg())
        await loop.step()

        assert state.error_count == 1
        assert state.metrics["total_errors"] == 1


# ── Exactly one queue consumer ─────────────────────────────────────────


class TestSingleQueueConsumer:
    async def test_loop_and_bus_processor_cannot_both_drain(
        self, event_bus, loop
    ):
        """Two consumers would each steal ~half the events, invisibly."""
        event_bus.start_queue_processor()
        try:
            with pytest.raises(EventBusError, match="already has a consumer"):
                await loop.start()
        finally:
            await event_bus.stop()

    async def test_stopping_loop_releases_the_queue(self, event_bus, loop):
        await loop.start()
        assert event_bus.queue_consumer == "runtime.event_loop"
        await loop.stop()
        assert event_bus.queue_consumer is None

        # The bus processor can now claim it without conflict.
        event_bus.start_queue_processor()
        await event_bus.stop()

    async def test_restart_is_idempotent(self, event_bus, loop):
        await loop.start()
        await loop.start()  # must not raise a consumer conflict
        await loop.stop()
        await loop.stop()  # must be safe twice
        assert event_bus.queue_consumer is None


# ── Observable runtime state ───────────────────────────────────────────


class TestRuntimeStateTracking:
    async def test_state_reflects_lifecycle_and_counters(
        self, event_bus, loop, state
    ):
        assert state.is_running is False

        await loop.start()
        try:
            assert state.is_running is True
            for i in range(3):
                await event_bus.enqueue(_msg(i))
            await _wait_until(lambda: loop.event_count == 3, timeout=3.0)
        finally:
            await loop.stop()

        assert state.is_running is False
        assert state.metrics["total_events"] == 3
        assert state.pending_events == 0
        assert state.uptime_seconds > 0
        assert state.metrics["events_per_second"] > 0

    async def test_state_validates_on_assignment(self, state):
        """Bounds must hold for mutations, not just construction."""
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            state.pending_events = -1
        with pytest.raises(ValidationError):
            state.cognitive_load = 1.5


# ── Supervisor delegates to the single loop ────────────────────────────


class TestSupervisorIntegration:
    def _supervisor(self, bus, cognitive_loop):
        from myharness.harness.monitor import RuntimeMonitor
        from myharness.harness.supervisor import HarnessSupervisor

        return HarnessSupervisor(
            event_bus=bus,
            router=Router(bus),
            memory=None,
            llm_engine=None,
            skill_store=None,
            capability_registry=None,
            driver_manager=None,
            scheduler=None,
            monitor=RuntimeMonitor(),
            cognitive_loop=cognitive_loop,
        )

    async def test_run_cognitive_loop_without_loop_fails_loudly(
        self, event_bus
    ):
        sup = self._supervisor(event_bus, cognitive_loop=None)
        with pytest.raises(RuntimeError, match="no cognitive loop"):
            await sup.run_cognitive_loop()

    async def test_boot_starts_loop_and_leaves_bus_processor_dormant(
        self, event_bus, loop
    ):
        sup = self._supervisor(event_bus, cognitive_loop=loop)
        await sup.boot()
        try:
            assert loop.is_running is True
            # The loop owns the queue — not the bus's raw-publish processor.
            assert event_bus.queue_consumer == "runtime.event_loop"
        finally:
            await sup.shutdown()

        assert loop.is_running is False
        assert event_bus.queue_consumer is None

    async def test_events_flow_end_to_end_through_booted_supervisor(
        self, event_bus, loop
    ):
        seen: list[BaseEvent] = []

        async def handler(event):
            seen.append(event)

        event_bus.subscribe(EventType.USER_MESSAGE, handler)
        sup = self._supervisor(event_bus, cognitive_loop=loop)

        await sup.boot()
        try:
            await event_bus.enqueue(_msg())
            await _wait_until(lambda: len(seen) == 1, timeout=3.0)
        finally:
            await sup.shutdown()

        assert len(seen) == 1


# ── DI wiring: the runtime layer is no longer orphaned ─────────────────


class TestRuntimeDIWiring:
    async def test_runtime_components_are_registered_singletons(
        self, test_settings
    ):
        from myharness.core.di import build_container
        from myharness.runtime.interrupt import InterruptHandler

        container = build_container(test_settings)
        for cls in (RuntimeState, InterruptHandler, EventLoop):
            assert container.resolve(cls) is container.resolve(cls), (
                f"{cls.__name__} is rebuilt on every resolution"
            )

    async def test_supervisor_shares_the_container_loop_and_bus(
        self, test_settings
    ):
        from myharness.core.di import build_container
        from myharness.harness.supervisor import HarnessSupervisor

        container = build_container(test_settings)
        loop = container.resolve(EventLoop)
        sup = container.resolve(HarnessSupervisor)

        assert sup._cognitive_loop is loop
        assert loop._event_bus is container.resolve(EventBus)
        assert loop._state is container.resolve(RuntimeState)

        memory = container.resolve(HarnessSupervisor)._memory
        if hasattr(memory, "close"):
            await memory.close()


async def _wait_until(predicate, timeout: float = 2.0, interval: float = 0.01):
    """Poll ``predicate`` until true or the timeout elapses."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(interval)
    return predicate()
