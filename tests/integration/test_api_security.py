"""API security and state-sharing regression tests.

Two production defects motivate this file:

1. **The API was effectively unauthenticated.** ``verify_api_key`` existed and
   was correct, but it was attached to only a handful of write endpoints via
   per-endpoint ``Depends``. Every read endpoint and the entire cognitive
   router — the most sensitive surface in the system — answered anonymous
   requests with 200. Auth is now bound at ``include_router`` level, and these
   tests assert that every non-public route rejects anonymous callers.

2. **Every request got a private memory system.** The DI container rebuilt its
   object graph on each resolution, so writes from one request were invisible
   to the next. ``test_memory_persists_across_requests`` locks that down.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.asyncio

API_KEY = "integration-test-key"

#: Every route that must require authentication, as (method, path).
PROTECTED_ROUTES = [
    ("GET", "/api/v1/memory/stats"),
    ("GET", "/api/v1/memory/identity"),
    ("GET", "/api/v1/memory/episodes/recent"),
    ("POST", "/api/v1/memory/search"),
    ("POST", "/api/v1/memory/rebuild"),
    ("GET", "/api/v1/skill/"),
    ("GET", "/api/v1/skill/stats/overview"),
    ("GET", "/api/v1/driver/"),
    ("GET", "/api/v1/driver/capabilities"),
    ("GET", "/api/v1/harness/status"),
    ("GET", "/api/v1/harness/health"),
    ("GET", "/api/v1/cognitive/status"),
    ("POST", "/api/v1/cognitive/message"),
]

#: Routes intentionally reachable without credentials.
PUBLIC_ROUTES = [
    ("GET", "/health"),
    ("GET", "/health/ready"),
]


def _call(client, method: str, path: str, **kwargs):
    return client.request(method, path, **kwargs)


class TestAuthentication:
    @pytest.mark.parametrize(
        ("method", "path"), PROTECTED_ROUTES, ids=lambda v: str(v)
    )
    async def test_anonymous_request_is_rejected(self, api_client, method, path):
        response = _call(api_client, method, path, json={})
        assert response.status_code == 401, (
            f"{method} {path} served an anonymous caller with "
            f"{response.status_code} — this endpoint is publicly exposed"
        )

    @pytest.mark.parametrize(
        ("method", "path"), PROTECTED_ROUTES, ids=lambda v: str(v)
    )
    async def test_wrong_key_is_rejected(self, api_client, method, path):
        response = _call(
            api_client, method, path, json={}, headers={"X-API-Key": "wrong-key"}
        )
        assert response.status_code == 401

    @pytest.mark.parametrize(("method", "path"), PUBLIC_ROUTES, ids=lambda v: str(v))
    async def test_public_routes_stay_public(self, api_client, method, path):
        """Health probes must work without credentials for orchestrators."""
        response = _call(api_client, method, path)
        assert response.status_code == 200

    async def test_valid_key_is_accepted(self, api_client):
        response = api_client.get(
            "/api/v1/memory/stats", headers={"X-API-Key": API_KEY}
        )
        assert response.status_code == 200
        assert "episodic" in response.json()

    async def test_empty_key_header_is_rejected(self, api_client):
        """An empty header must not be treated as 'no auth required'."""
        response = api_client.get("/api/v1/memory/stats", headers={"X-API-Key": ""})
        assert response.status_code == 401

    async def test_rejection_includes_www_authenticate(self, api_client):
        response = api_client.get("/api/v1/memory/stats")
        assert "WWW-Authenticate" in response.headers

    async def test_error_body_does_not_leak_the_key(self, api_client):
        response = api_client.get(
            "/api/v1/memory/stats", headers={"X-API-Key": "wrong-key"}
        )
        assert API_KEY not in response.text


class TestFailClosedWithoutKey:
    """With no MYH_API_KEY configured the API must refuse, not open up."""

    @pytest.fixture
    def unconfigured_client(self, tmp_path, monkeypatch):
        monkeypatch.setenv("MYH_DATA_DIR", str(tmp_path))
        monkeypatch.delenv("MYH_API_KEY", raising=False)
        monkeypatch.setenv("MYH_API_KEY", "")
        monkeypatch.setenv("MYH_OPENAI_API_KEY", "sk-test-not-used")
        monkeypatch.setenv("MYH_EMBEDDING_PROVIDER", "none")
        monkeypatch.setenv("MYH_LOG_LEVEL", "ERROR")

        from myharness.api.dependencies import get_container
        from myharness.core.config import get_settings

        get_settings.cache_clear()
        get_container.cache_clear()

        from myharness.api.app import create_app

        with TestClient(create_app()) as client:
            yield client

        get_settings.cache_clear()
        get_container.cache_clear()

    async def test_missing_server_key_denies_access(self, unconfigured_client):
        """A forgotten MYH_API_KEY must lock the door, not remove it."""
        response = unconfigured_client.get("/api/v1/memory/stats")
        assert response.status_code in (401, 503)

    async def test_health_still_works_without_a_key(self, unconfigured_client):
        assert unconfigured_client.get("/health").status_code == 200


class TestCrossRequestState:
    """Requests must share one memory system, not one per request."""

    async def test_memory_persists_across_requests(self, api_client):
        auth = {"X-API-Key": API_KEY}

        before = api_client.get("/api/v1/memory/stats", headers=auth).json()
        assert before["episodic"]["total_entries"] == 0

        # The LLM call fails (dummy key) but the episode is still recorded,
        # which is precisely what we need to observe here.
        api_client.post(
            "/api/v1/cognitive/message",
            headers=auth,
            json={"message": "remember the alamo"},
        )

        after = api_client.get("/api/v1/memory/stats", headers=auth).json()
        assert after["episodic"]["total_entries"] > 0, (
            "an episode written during one request was invisible to the next — "
            "each request is getting its own MemoryManager"
        )

    async def test_recent_episodes_endpoint_serializes(self, api_client):
        """Regression: the response model claimed `count` was a list → 500."""
        response = api_client.get(
            "/api/v1/memory/episodes/recent?limit=5", headers={"X-API-Key": API_KEY}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert isinstance(body["episodes"], list)
        assert isinstance(body["count"], int)


class TestHealthProbesReflectRealState:
    """Health probes are unauthenticated and drive traffic routing.

    They used to return a hardcoded 200 ("in MVP, this is always true after
    startup"). After ``POST /harness/shutdown`` the supervisor was stopped
    and every memory backend was closed, yet both probes still answered
    200 — so a load balancer kept sending traffic to a dead instance.
    """

    async def test_probes_are_green_on_a_serving_instance(self, api_client):
        for path in ("/health", "/health/ready"):
            response = api_client.get(path)
            assert response.status_code == 200, f"{path} -> {response.text}"
            assert response.json()["service"] == "myharness"

    async def test_probes_fail_after_shutdown(self, api_client):
        from myharness.api.dependencies import get_container
        from myharness.harness.supervisor import HarnessSupervisor

        supervisor = get_container().resolve(HarnessSupervisor)
        await supervisor.shutdown()

        liveness = api_client.get("/health")
        assert liveness.status_code == 503, (
            "a shut-down instance still reported itself alive — an "
            "orchestrator would keep it in the pool"
        )
        assert liveness.json()["status"] == "unhealthy"

        readiness = api_client.get("/health/ready")
        assert readiness.status_code == 503
        assert readiness.json()["status"] == "not_ready"

    async def test_readiness_fails_when_memory_is_closed(self, api_client):
        """Readiness must track capability, not just a boolean flag."""
        from myharness.api.dependencies import get_container
        from myharness.memory.interface import MemorySystem

        memory = get_container().resolve(MemorySystem)
        assert memory.is_closed is False
        await memory.close()
        assert memory.is_closed is True

        response = api_client.get("/health/ready")
        assert response.status_code == 503
        assert "Memory subsystem is closed" in response.json()["detail"]

        # Liveness stays green: the process itself is still viable.
        assert api_client.get("/health").status_code == 200


class TestLivenessSurvivesMisconfiguration:
    """A liveness probe must not fail for reasons a restart cannot fix.

    Found by smoke-testing a real server with no LLM key set. In the API's
    lazy mode, resolving the supervisor builds the entire DI graph, so
    constructing the LLM engine raised ProviderNotAvailableError straight
    out of ``/health``. Kubernetes reads that as "wedged process", kills
    the pod, and restarts it — forever, because no restart supplies a
    missing API key. Readiness is where that condition belongs.
    """

    @staticmethod
    def _break_supervisor(monkeypatch):
        from myharness.api.routers import health
        from myharness.core.exceptions import ProviderNotAvailableError

        async def boom():
            raise ProviderNotAvailableError(
                "OpenAI API key is not configured.",
                code="OPENAI_NOT_CONFIGURED",
            )

        monkeypatch.setattr(health, "get_supervisor", boom)

    async def test_liveness_stays_green_when_the_graph_cannot_be_built(
        self, api_client, monkeypatch
    ):
        self._break_supervisor(monkeypatch)

        response = api_client.get("/health")

        assert response.status_code == 200, (
            "a misconfigured instance was reported dead — the orchestrator "
            "would restart-loop it without ever fixing the configuration"
        )
        body = response.json()
        assert body["status"] == "healthy"
        assert "not constructible" in body["detail"]

    async def test_readiness_drains_the_instance_instead(
        self, api_client, monkeypatch
    ):
        self._break_supervisor(monkeypatch)

        response = api_client.get("/health/ready")

        assert response.status_code == 503
        assert response.json()["status"] == "not_ready"
        assert "OPENAI_NOT_CONFIGURED" in response.json()["detail"]

    async def test_probes_never_return_500(self, api_client, monkeypatch):
        """A probe that 500s tells the orchestrator nothing useful."""
        from myharness.api.routers import health

        async def boom():
            raise RuntimeError("something entirely unexpected")

        monkeypatch.setattr(health, "get_supervisor", boom)

        assert api_client.get("/health").status_code == 200
        assert api_client.get("/health/ready").status_code == 503
