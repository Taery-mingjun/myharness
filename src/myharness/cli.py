"""Command-line interface for MyHarness.

Provides entry points for running the API server and demonstrations:

    myharness serve   — Start the FastAPI server
    myharness demo    — Run an offline cognitive pipeline demo
    myharness version — Print version information
"""

from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

__version__ = "0.1.0"


def _cmd_serve(args: argparse.Namespace) -> int:
    """Start the FastAPI server via uvicorn."""
    import uvicorn

    from myharness.api.app import create_app

    app = create_app()
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_level="info" if args.debug else "warning",
        reload=args.debug,
    )
    return 0


async def _run_demo() -> None:
    """Run an offline cognitive pipeline demo using a FakeProvider."""
    from myharness.core.config import Settings
    from myharness.core.di import build_container
    from myharness.harness.supervisor import HarnessSupervisor
    from myharness.llm.context import ContextBuilder
    from myharness.llm.engine import LLMEngine
    from myharness.llm.interfaces import LLMProvider
    from myharness.memory.embedder import Embedder
    from myharness.memory.interface import MemorySystem

    class DemoProvider(LLMProvider):
        @property
        def provider_name(self) -> str:
            return "demo"

        async def complete(self, messages, model=None, temperature=0.7,
                           max_tokens=4096, tools=None, **kwargs) -> str:
            sys_ = messages[0]["content"] if messages else ""
            user_ = messages[-1]["content"] if messages else ""
            if "plan" in sys_.lower():
                return '{"goal": "respond", "steps": [], "reasoning": "demo: no action"}'
            if "reflect" in sys_.lower():
                return '{"summary": "demo reflection", "lessons_learned": [], "skill_improvement_suggestions": [], "identity_implications": [], "emotional_tone": "neutral"}'
            return f"[demo-think] Acknowledged: {user_[:60]}"

        async def complete_stream(self, messages, model=None, temperature=0.7,
                                  max_tokens=4096, **kwargs):
            yield "ok"

        async def embed(self, text):
            """Deterministic bag-of-words vectors — no model, no network.

            Random vectors would make recall meaningless; hashing tokens keeps
            similar texts genuinely close so the demo's vector search behaves
            like the real thing.
            """
            texts = [text] if isinstance(text, str) else list(text)
            vectors = []
            for item in texts:
                vec = [0.0] * 64
                for token in item.lower().split():
                    vec[hash(token) % 64] += 1.0
                vectors.append(vec)
            return vectors

        @property
        def supported_models(self) -> list[str]:
            return ["demo-1"]

        @property
        def default_model(self) -> str:
            return "demo-1"

        async def health_check(self) -> bool:
            return True

    demo_provider = DemoProvider()

    # The demo must run with zero credentials and zero network access, so it
    # cannot reuse ambient settings: building the container would resolve the
    # real LLMProvider (and fail on a missing API key) before we ever get to
    # swap in DemoProvider. Data lands in a temp dir so repeated runs stay
    # reproducible and never pollute the operator's real memory store.
    with tempfile.TemporaryDirectory(prefix="myharness-demo-") as tmp:
        settings = Settings(
            data_dir=Path(tmp),
            openai_api_key="demo-offline",
            default_llm_provider="openai",
            embedding_provider="none",  # vector memory off: no network
            embedding_dimension=64,
            log_level="ERROR",
        )

        # Route BOTH cognition and embeddings through the offline provider so
        # the demo exercises the real vector path instead of skipping it.
        # The override must be applied BEFORE resolving MemorySystem: lagom
        # caches singletons and MemoryManager captures its embedder at
        # construction time.
        container = build_container(settings).clone()
        container[Embedder] = Embedder(port=demo_provider, dimension=64)

        memory = container.resolve(MemorySystem)
        supervisor = container.resolve(HarnessSupervisor)
        supervisor._llm_engine = LLMEngine(demo_provider, ContextBuilder(memory))

        await supervisor.boot()
        try:
            print("=" * 60)
            print(" MyHarness Cognitive Pipeline Demo (offline)")
            print("=" * 60)
            messages = [
                "Hello, who are you?",
                "Remember that I prefer concise answers.",
                "What did we discuss earlier?",
            ]
            for msg in messages:
                print(f"\n[user]  {msg}")
                resp = await supervisor.handle_user_message(msg, user_id="demo")
                print(f"[agent] {resp}")

            recent = await memory.get_recent_episodes(limit=10)
            stats = await memory.get_stats()
            vectors = stats.get("indexes", {}).get("vector_count", 0)
            print("\n" + "-" * 60)
            print(f"Episodes recorded : {len(recent)}")
            print(f"Vectors indexed   : {vectors}")
            print("-" * 60)
        finally:
            await supervisor.shutdown()


def _cmd_demo(args: argparse.Namespace) -> int:
    """Run the demo command."""
    import asyncio

    asyncio.run(_run_demo())
    return 0


def _cmd_version(args: argparse.Namespace) -> int:
    """Print version."""
    print(f"MyHarness v{__version__}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="myharness",
        description="MyHarness — Cognitive Operating System for AI Agents",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # serve
    p_serve = sub.add_parser("serve", help="Start the API server")
    p_serve.add_argument("--host", default="127.0.0.1", help="Bind host")
    p_serve.add_argument("--port", type=int, default=8000, help="Bind port")
    p_serve.add_argument("--debug", action="store_true", help="Enable debug/reload")
    p_serve.set_defaults(func=_cmd_serve)

    # demo
    p_demo = sub.add_parser("demo", help="Run an offline cognitive pipeline demo")
    p_demo.set_defaults(func=_cmd_demo)

    # version
    p_ver = sub.add_parser("version", help="Print version")
    p_ver.set_defaults(func=_cmd_version)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
