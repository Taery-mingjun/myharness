#!/usr/bin/env python3
"""Sandbox benchmark runner — executes the 5 fixed benchmark tasks.

This script runs inside the sandbox container. It:
1. Loads benchmark definitions from /benchmark/ (read-only mount)
2. For cognitive tasks (T1, T2, T5): calls the LLM engine directly
3. For API tasks (T3, T4): calls the FastAPI test client
4. Writes results to /sandbox/results/

This script does NOT modify any skill, does NOT merge results, and
does NOT make any outbound calls except to the configured LLM provider.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

BENCHMARK_DIR = Path(os.environ.get("BENCHMARK_DIR", "/benchmark"))
RESULTS_DIR = Path(os.environ.get("RESULTS_DIR", "/sandbox/results"))


async def run_cognitive_task(task: dict) -> dict:
    """Run a cognitive message task using LLMEngine directly."""
    message = task["input"]["message"]
    timeout = task.get("timeout_seconds", 30)

    try:
        from myharness.llm.context import ContextBuilder
        from myharness.llm.engine import LLMEngine
        from myharness.llm.providers import create_provider
        from myharness.core.config import get_settings

        settings = get_settings()
        provider = create_provider(name=settings.default_llm_provider, settings=settings)
        engine = LLMEngine(provider=provider, context_builder=None)

        # Bypass ContextBuilder (no memory in sandbox) — pass context directly
        result = await asyncio.wait_for(
            engine.think(query=message, context={"query": message, "identity": {}, "memories": []}),
            timeout=timeout,
        )
        return {
            "task_id": task["task_id"],
            "status": "pass" if result and len(result.strip()) > 0 else "fail",
            "response": result[:500],
            "duration_ms": 0,
            "error": None,
        }
    except Exception as e:
        return {
            "task_id": task["task_id"],
            "status": "fail",
            "response": "",
            "duration_ms": 0,
            "error": f"{type(e).__name__}: {e}",
        }


async def run_api_task(task: dict) -> dict:
    """Run an API endpoint task using TestClient."""
    endpoint = task["input"].get("endpoint", "")
    timeout = task.get("timeout_seconds", 10)

    try:
        from starlette.testclient import TestClient
        from myharness.api.app import create_app

        app = create_app(auto_boot=False)
        client = TestClient(app)

        method, path = endpoint.split(" ", 1)
        start = time.monotonic()
        response = client.get(path, headers={"X-API-Key": os.environ.get("MYH_API_KEY", "sandbox")})
        duration_ms = (time.monotonic() - start) * 1000

        data = response.json()
        expected_fields = task["expected"].get("response_contains", [])

        all_present = all(f in str(data) for f in expected_fields)
        status = "pass" if all_present else "fail"

        return {
            "task_id": task["task_id"],
            "status": status,
            "response": json.dumps(data)[:500],
            "duration_ms": round(duration_ms, 2),
            "error": None,
        }
    except Exception as e:
        return {
            "task_id": task["task_id"],
            "status": "fail",
            "response": "",
            "duration_ms": 0,
            "error": f"{type(e).__name__}: {e}",
        }


async def main():
    """Run all benchmarks and write results."""
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)

    # Override context builder for sandbox (no memory dependency)
    # We monkey-patch ContextBuilder to return empty context
    from myharness.llm.context import ContextBuilder

    original_init = ContextBuilder.__init__

    def sandbox_init(self, memory=None):
        self._memory = memory

    async def sandbox_build_think(self, query):
        return {"query": query, "identity_context": {}, "memory_context": "", "agent_name": "SandboxAgent", "self_description": "A sandbox test agent", "mission": "Run benchmarks", "core_values": [], "behavioral_guidelines": []}

    async def sandbox_build_plan(self, goal, skills):
        return {"goal": goal, "available_skills": skills or [], "agent_name": "SandboxAgent", "self_description": "", "mission": ""}

    async def sandbox_build_reflect(self, experience):
        return {"experience": experience, "identity_context": {}, "core_values": [], "self_description": ""}

    ContextBuilder.__init__ = sandbox_init
    ContextBuilder.build_think_context = sandbox_build_think
    ContextBuilder.build_plan_context = sandbox_build_plan
    ContextBuilder.build_reflect_context = sandbox_build_reflect

    results = []
    total_pass = 0
    total_fail = 0

    for task_file in sorted(BENCHMARK_DIR.glob("*.json")):
        with open(task_file) as f:
            task = json.load(f)

        print(f"[{task['task_id']}] Running: {task['name']}...", flush=True)

        endpoint = task["input"].get("endpoint", "")
        if endpoint:
            result = await run_api_task(task)
        else:
            result = await run_cognitive_task(task)

        results.append(result)
        if result["status"] == "pass":
            total_pass += 1
            print(f"  -> PASS", flush=True)
        else:
            total_fail += 1
            print(f"  -> FAIL: {result.get('error', 'criteria not met')}", flush=True)

    # Write results
    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "total": len(results),
        "passed": total_pass,
        "failed": total_fail,
        "score": f"{total_pass}/{len(results)}",
        "results": results,
    }

    results_file = RESULTS_DIR / f"benchmark_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}.json"
    with open(results_file, "w") as f:
        json.dump(report, f, indent=2)

    print(f"\n=== Benchmark Results ===", flush=True)
    print(f"Total: {report['total']}", flush=True)
    print(f"Passed: {report['passed']}", flush=True)
    print(f"Failed: {report['failed']}", flush=True)
    print(f"Score: {report['score']}", flush=True)
    print(f"Results file: {results_file}", flush=True)

    # Exit code: 0 if all passed, 1 if any failed
    sys.exit(0 if total_fail == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
