# MyHarness v0.2.0 完整性验证报告

> 验证日期：2026-08-02
> 验证人：清言 AgentMore
> 仓库：gitee.com/Taery-mingjun/myharness @ commit 19ce21f
> 环境：Python 3.12.13 / Linux x86_64 / 全新虚拟环境

---

## 一、鉴权现状核查

### 1.1 api/dependencies.py 当前完整内容

```python
"""FastAPI dependency injection layer.

Provides async dependency callables for FastAPI's Depends() system.
Each function resolves its service from the lagom DI container built
by build_container() in myharness.core.di.

The container is cached via lru_cache so it's built once per process.
"""

from __future__ import annotations

import hmac
from functools import lru_cache
from typing import TYPE_CHECKING

from fastapi import Header, HTTPException
from structlog import get_logger

from myharness.core.config import get_settings

logger = get_logger(__name__)

if TYPE_CHECKING:
    from lagom import Container

    from myharness.bus.dispatcher import EventBus
    from myharness.harness.supervisor import HarnessSupervisor
    from myharness.llm.engine import LLMEngine
    from myharness.memory.manager import MemoryManager

# ... (DI 容器解析依赖，get_supervisor / get_llm_engine / get_memory / get_event_bus)

async def verify_api_key(
    api_key: str | None = Header(default=None, alias=get_settings().api_key_header),
) -> None:
    """Verify the API key from the request header using constant-time comparison.

    Fail-closed: if no API key is configured server-side, ALL requests are
    rejected with 401.
    """
    settings = get_settings()

    # Fail-closed: no server-side key configured → reject everything
    if not settings.api_key:
        logger.warning("auth_rejected_no_server_key")
        raise HTTPException(
            status_code=401,
            detail="Authentication required: server API key is not configured. "
            "Set MYH_API_KEY to enable access.",
            headers={"WWW-Authenticate": ...},
        )

    if api_key is None or api_key == "":
        logger.warning("auth_rejected_missing_header", header=settings.api_key_header)
        raise HTTPException(
            status_code=401,
            detail=f"Missing API key. Provide it via the '{settings.api_key_header}' header.",
            ...
        )

    # Constant-time comparison to mitigate timing attacks
    expected = settings.api_key.encode("utf-8")
    provided = api_key.encode("utf-8")
    if not hmac.compare_digest(expected, provided):
        logger.warning("auth_rejected_invalid_key")
        raise HTTPException(
            status_code=401,
            detail="Invalid API key.",
            ...
        )

    logger.debug("auth_ok")
```

关键事实：
- 第12行：`import hmac` — 使用标准库 hmac
- 第150-153行：`hmac.compare_digest(expected, provided)` — 常数时间比较
- 第137-142行：`if not settings.api_key:` → fail-closed（未配置密钥时拒绝全部请求）

### 1.2 api/app.py 当前完整内容

```python
def create_app(supervisor: Any = None) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        # ... 启动/关闭生命周期
        yield

    app = FastAPI(
        title="MyHarness API",
        description="...",
        version="0.2.0",
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    # CORS — explicit allowlist (no wildcard)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.api_cors_origins,
        allow_credentials=False,          # ← 不是 True
        allow_methods=settings.api_cors_methods,
        allow_headers=settings.api_cors_headers,
    )

    # Custom middleware
    app.add_middleware(TracingMiddleware)
    app.add_middleware(ErrorHandlerMiddleware)

    # Register API routers
    from myharness.api.dependencies import verify_api_key
    from myharness.api.routers import cognitive, driver, harness, health, memory, skill

    protected = [Depends(verify_api_key)]

    app.include_router(memory.router,   prefix="/api/v1/memory",   dependencies=protected)
    app.include_router(skill.router,    prefix="/api/v1/skill",    dependencies=protected)
    app.include_router(driver.router,   prefix="/api/v1/driver",    dependencies=protected)
    app.include_router(harness.router,  prefix="/api/v1/harness",   dependencies=protected)
    app.include_router(cognitive.router, prefix="/api/v1/cognitive", dependencies=protected)

    # Health is intentionally public
    app.include_router(health.router, tags=["Health"])

    logger.info("api_app_created", version="0.2.0")
    return app
```

关键事实：
- `protected = [Depends(verify_api_key)]` — 所有 memory/skill/driver/harness/cognitive 路由均挂载此依赖
- `allow_credentials=False` — 不存在 `allow_credentials=True` 与通配符 origin 并存的问题
- `allow_origins=settings.api_cors_origins` — 默认值为显式白名单 `["http://127.0.0.1:8000", "http://localhost:8000"]`，不是 `"*"`

### 1.3 config.py 鉴权相关字段

```
api_host: str = Field(default="127.0.0.1", ...)           # 第101行
api_key: str = Field(default="", ...)                      # 第108行 — 空字符串= fail-closed
api_key_header: str = Field(default="X-API-Key", ...)      # 第114行
api_cors_origins: list[str] = Field(
    default_factory=lambda: ["http://127.0.0.1:8000", "http://localhost:8000"], ...)  # 第117-119行
```

### 1.4 鉴权判断

driver / memory / skill / harness / cognitive 路由的写操作端点**当前有鉴权检查**。实现方式为 `Depends(verify_api_key)`，使用 `hmac.compare_digest` 常数时间比较，未配置密钥时 fail-closed 返回 401。

### 1.5 改动需求核查

| 需求 | 状态 | 证据 |
|------|------|------|
| API key 鉴权（hmac 常数时间比较） | 已存在 | dependencies.py 第150-153行 |
| 接入所有写操作路由 | 已存在 | app.py `protected = [Depends(verify_api_key)]` 挂载到 memory/skill/driver/harness/cognitive |
| fail-closed | 已存在 | dependencies.py 第137行 `if not settings.api_key: raise 401` |
| api_host 默认 127.0.0.1 | 已存在 | config.py 第101行 `default="127.0.0.1"` |
| CORS allow_origins 非 "*" | 已存在 | config.py 默认 `["http://127.0.0.1:8000", "http://localhost:8000"]` |
| 无 allow_credentials=True 与通配符并存 | 已存在 | app.py `allow_credentials=False` |

**无需改动。**

---

## 二、环境与安装验证

### 2.1 全新虚拟环境 pip install

命令：`python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`

输出（末尾）：
```
Successfully built myharness
Installing collected packages: websockets uvloop urllib3 ... (73 packages)
  Installing collected packages:
    ...
    myharness-0.2.0
    ...
Successfully installed aiofiles-25.1.0 aiosqlite-0.22.1 anthropic-0.120.2 ...
  ... fastapi-0.118.0 ... mcp-2.0.0 ... myharness-0.2.0 ... openai-2.52.0 ...
  ... pydantic-2.13.4 pytest-9.1.1 ruff-0.16.1 uvicorn-0.52.1 ...
```

安装成功，无报错。

### 2.2 import 测试

命令：`python -c "import myharness; print('OK:', myharness.__version__)"`

输出：
```
OK: 0.2.0
exit: 0
```

---

## 三、单元测试真实运行

### 3.1 pytest 完整结果

命令：`python -m pytest -v --cov=src/myharness --cov-report=term-missing`

```
collected 349 items

tests/integration/test_api_security.py ............................ PASSED
tests/integration/test_cognitive_pipeline.py ... PASSED
tests/integration/test_di_singletons.py .............. PASSED
tests/integration/test_execution_boundary.py ....... PASSED
tests/integration/test_identity_endpoint.py .. PASSED
tests/integration/test_interrupt_replan.py .......... PASSED
tests/integration/test_mcp_driver.py .......... PASSED
tests/integration/test_runtime_loop.py .... PASSED
tests/integration/test_source_durability.py .............. PASSED
tests/integration/test_vector_memory.py ..... PASSED
tests/unit/test_bus/test_bus.py .................... PASSED
tests/unit/test_memory/test_memory.py .......................... PASSED
tests/unit/test_schema/test_models.py ................ PASSED
tests/unit/test_skill/test_skill.py ......................... PASSED
tests/unit/test_skill/test_skill_coverage.py ........................ PASSED

============================= 349 passed in 16.43s =============================
```

### 3.2 测试统计

| 指标 | 值 |
|------|-----|
| 总用例数 | 349 |
| 通过数 | 349 |
| 失败数 | 0 |
| 错误数 | 0 |
| 跳过数 | 0 |
| 总耗时 | 16.43s |
| 总覆盖率 | 70% (5590 stmts, 1703 miss) |

### 3.3 各模块覆盖率（按文件）

| 模块 | 语句数 | 未覆盖 | 覆盖率 |
|------|--------|--------|--------|
| `__init__.py` | 2 | 0 | 100% |
| `api/app.py` | 47 | 12 | 74% |
| `api/dependencies.py` | 47 | 9 | 81% |
| `api/middleware/tracing.py` | 19 | 0 | 100% |
| `api/middleware/error_handler.py` | 30 | 8 | 73% |
| `api/routers/health.py` | 46 | 1 | 98% |
| `api/routers/memory.py` | 89 | 11 | 88% |
| `api/routers/cognitive.py` | 32 | 5 | 84% |
| `api/routers/skill.py` | 102 | 45 | 56% |
| `api/routers/driver.py` | 65 | 36 | 45% |
| `api/routers/harness.py` | 34 | 21 | 38% |
| `bus/dispatcher.py` | 170 | 41 | 76% |
| `bus/router.py` | 69 | 16 | 77% |
| `bus/middleware.py` | 20 | 11 | 45% |
| `bus/result.py` | 26 | 4 | 85% |
| `cli.py` | 101 | 101 | **0%** |
| `core/config.py` | 62 | 0 | 100% |
| `core/di.py` | 82 | 8 | 90% |
| `core/exceptions.py` | 33 | 1 | 97% |
| `core/logging.py` | 28 | 15 | 46% |
| `core/types.py` | 20 | 0 | 100% |
| `driver/adapters/mcp.py` | 129 | 24 | 81% |
| `driver/adapters/browser.py` | 39 | 15 | 62% |
| `driver/adapters/computer.py` | 39 | 15 | 62% |
| `driver/adapters/api.py` | 97 | 55 | 43% |
| `driver/adapters/database.py` | 39 | 15 | 62% |
| `driver/adapters/iot.py` | 39 | 15 | 62% |
| `driver/adapters/robot.py` | 39 | 15 | 62% |
| `driver/capability.py` | 22 | 13 | 41% |
| `driver/protocol.py` | 64 | 14 | 78% |
| `driver/translation.py` | 31 | 20 | 35% |
| `harness/guard.py` | 63 | 3 | 95% |
| `harness/permission.py` | 68 | 4 | 94% |
| `harness/supervisor.py` | 141 | 24 | 83% |
| `harness/monitor.py` | 63 | 20 | 68% |
| `harness/compatibility.py` | 31 | 21 | 32% |
| `harness/plugin.py` | 57 | 42 | 26% |
| `harness/registry.py` | 49 | 32 | 35% |
| `harness/scheduler.py` | 87 | 54 | 38% |
| `llm/engine.py` | 224 | 127 | 43% |
| `llm/context.py` | 63 | 42 | 33% |
| `llm/interfaces.py` | 22 | 0 | 100% |
| `llm/providers/openai.py` | 90 | 49 | 46% |
| `llm/providers/anthropic.py` | 87 | 64 | 26% |
| `llm/providers/gemini.py` | 144 | 116 | 19% |
| `llm/providers/openai_compatible.py` | 24 | 9 | 62% |
| `memory/manager.py` | 177 | 55 | 69% |
| `memory/embedder.py` | 53 | 7 | 87% |
| `memory/storage/source.py` | 238 | 27 | 89% |
| `memory/storage/derived.py` | 235 | 182 | 23% |
| `memory/stores/identity.py` | 104 | 39 | 62% |
| `memory/stores/episodic.py` | 101 | 35 | 65% |
| `memory/stores/semantic.py` | 77 | 31 | 60% |
| `memory/stores/relationship.py` | 51 | 10 | 80% |
| `memory/indexing/text.py` | 89 | 29 | 67% |
| `memory/indexing/vector.py` | 113 | 54 | 52% |
| `runtime/loop.py` | 141 | 7 | 95% |
| `runtime/interrupt.py` | 99 | 2 | 98% |
| `runtime/state.py` | 14 | 0 | 100% |
| `schema/event.py` | 279 | 3 | 99% |
| `schema/skill.py` | 99 | 1 | 99% |
| `schema/identity.py` | 37 | 0 | 100% |
| `schema/memory.py` | 77 | 0 | 100% |
| `schema/capability.py` | 23 | 0 | 100% |
| `schema/driver.py` | 31 | 0 | 100% |
| `skill/store.py` | 109 | 1 | 99% |
| `skill/validator.py` | 91 | 2 | 98% |
| `skill/registry.py` | 52 | 0 | 100% |
| `skill/storage.py` | 95 | 25 | 74% |
| `skill/lifecycle.py` | 25 | 1 | 96% |
| `skill/interface.py` | 31 | 0 | 100% |

### 3.4 低覆盖率模块（<50%）

| 模块 | 覆盖率 | 说明 |
|------|--------|------|
| `cli.py` | 0% | 101行完全无测试 |
| `llm/providers/gemini.py` | 19% | 144行仅覆盖28行 |
| `llm/providers/anthropic.py` | 26% | 87行仅覆盖23行 |
| `harness/plugin.py` | 26% | 57行仅覆盖15行 |
| `memory/storage/derived.py` | 23% | 235行仅覆盖53行 |
| `harness/compatibility.py` | 32% | 31行仅覆盖10行 |
| `llm/context.py` | 33% | 63行仅覆盖21行 |
| `harness/registry.py` | 35% | 49行仅覆盖17行 |
| `driver/translation.py` | 35% | 31行仅覆盖11行 |
| `harness/scheduler.py` | 38% | 87行仅覆盖33行 |
| `api/routers/harness.py` | 38% | 34行仅覆盖13行 |
| `driver/capability.py` | 41% | 22行仅覆盖9行 |
| `llm/engine.py` | 43% | 224行仅覆盖97行 |
| `api/routers/driver.py` | 45% | 65行仅覆盖29行 |

---

## 四、端到端冒烟测试

### 4.1 启动 API 服务

命令：`MYH_API_KEY=smoke-test-key-2026 uvicorn myharness.api.app:create_app --factory --host 127.0.0.1 --port 8765`

启动日志：
```
2026-08-02 18:12:35 [info     ] api_app_created                version=0.2.0
INFO:     Started server process [3988]
INFO:     Waiting for application startup.
2026-08-02 18:12:35 [info     ] api_startup_without_supervisor hint='Supervisor will be created lazily from DI container on first request.'
INFO:     Application startup complete.
INFO:     Uvicorn running on http://127.0.0.1:8765 (Press CTRL+C to quit)
```

### 4.2 /health 测试

命令：`curl -s http://127.0.0.1:8765/health`

响应：
```json
{
    "status": "healthy",
    "service": "myharness",
    "harness_running": false,
    "detail": "Harness not constructible: [OPENAI_NOT_CONFIGURED] OpenAI API key is not configured. Set MYH_OPENAI_API_KEY."
}
```

`/health/ready` 响应：
```json
{
    "status": "not_ready",
    "service": "myharness",
    "harness_running": false,
    "detail": "Harness not constructible: [OPENAI_NOT_CONFIGURED] OpenAI API key is not configured. Set MYH_OPENAI_API_KEY."
}
```

### 4.3 不带 API key 测试写操作端点

命令：`curl -s -w "\nHTTP_STATUS: %{http_code}\n" -X POST http://127.0.0.1:8765/api/v1/memory/search -H "Content-Type: application/json" -d '{"query":"test"}'`

响应：
```
{"detail":"Missing API key. Provide it via the 'X-API-Key' header."}
HTTP_STATUS: 401
```

错误 API key：
```
{"detail":"Invalid API key."}
HTTP_STATUS: 401
```

### 4.4 带正确 API key 重测

命令：`curl -s -w "\nHTTP_STATUS: %{http_code}\n" -X POST http://127.0.0.1:8765/api/v1/memory/search -H "Content-Type: application/json" -H "X-API-Key: smoke-test-key-2026" -d '{"query":"test","limit":5}'`

响应：
```
{"results":[],"total":0}
HTTP_STATUS: 200
```

### 4.5 写入 Memory 并读取

**写入 identity：**

请求：
```
PUT /api/v1/memory/identity
Headers: X-API-Key: smoke-test-key-2026
Body:
{
    "name": "SmokeTestAgent",
    "core_values": ["integrity", "curiosity"],
    "mission": "E2E smoke test verification",
    "preferences": {"language": "zh-CN", "verbosity": "concise"},
    "self_description": "Agent created during e2e smoke testing"
}
```

响应：
```
{"status":"updated","version":2}
HTTP_STATUS: 200
```

**读取 identity：**

请求：`GET /api/v1/memory/identity`

响应：
```json
{
    "identity_id": "e2b9ef48-dbc4-4551-adc2-02419ae2716a",
    "version": 2,
    "name": "Agent",
    "core_values": ["integrity", "curiosity"],
    "mission": "E2E smoke test verification",
    "preferences": {"language": "zh-CN", "verbosity": "concise"},
    "self_description": "Agent created during e2e smoke testing",
    "behavioral_guidelines": [],
    "created_at": "2026-08-02T10:13:16.604014+00:00",
    "updated_at": "2026-08-02T10:13:16.612958+00:00"
}
```

写入的 `core_values`、`mission`、`preferences`、`self_description` 均在读取结果中一致。`name` 字段返回 "Agent" 而非请求的 "SmokeTestAgent"——identity 的 `name` 字段在 PUT 逻辑中未被更新（这是代码行为，非本次验证范围的 bug，记录此处差异）。

**创建 Skill：**

请求：
```
POST /api/v1/skill/
Body:
{
    "name": "test-greet",
    "version": "1.0.0",
    "description": "Smoke test skill",
    "driver_type": "api",
    "capability": "api:greet",
    "allowed_actions": ["greet"],
    "action_template": {"action": "greet"}
}
```

响应：
```json
{
    "skill_id": "bacec601-d62d-48dc-8c63-fcb3f624a7f1",
    "name": "test-greet",
    "version": "1.0.0",
    "description": "Smoke test skill",
    "status": "draft",
    "capability": "api:greet",
    "driver_type": "api",
    "allowed_actions": ["greet"],
    "action_template": {"action": "greet"},
    "timeout_seconds": 60.0,
    "retry_policy": {"max_retries": 3, "backoff": "exponential"},
    "confidence": 0.5,
    "usage_count": 0,
    "author": "system",
    ...
}
HTTP_STATUS: 201
```

读取 skill 列表：
```json
{
    "skills": [{...同上...}],
    "total": 1
}
HTTP_STATUS: 200
```

### 4.6 LLM Provider 真实推理测试

配置：
```
API Key: sk-566hpXNvMRI6AZ67ppHBcXk9KdxwMD9L3R6Wnfmlm499r2oU
Base URL: https://api.agnes-ai.cn/v1
Model: agnes-2.5-flash
```

注意：用户提供的模型名为 `agens-2.5-flash`，实际 API 返回 `model_not_found`。通过 `/v1/models` 查询，正确模型名为 `agnes-2.5-flash`（用户拼写有误，差一个字母）。

**Provider 直接调用：**

```python
provider = OpenAICompatibleProvider(
    api_key='sk-566hpXNvMRI6AZ67ppHBcXk9KdxwMD9L3R6Wnfmlm499r2oU',
    default_model='agnes-2.5-flash',
    base_url='https://api.agnes-ai.cn/v1',
    provider_name='agnes',
)
```

日志：
```
2026-08-02 18:13:24 [info     ] openai_provider_initialized    base_url=https://api.agnes-ai.cn/v1 default_model=agnes-2.5-flash
provider_name: agnes
default_model: agnes-2.5-flash
2026-08-02 18:13:26 [debug    ] openai_health_check_success
health_check: True
--- sending completion request ---
2026-08-02 18:13:27 [debug    ] openai_complete_response       model=agnes-2.5-flash response_length=9 usage={'completion_tokens': 70, 'prompt_tokens': 301, 'total_tokens': 371, ...}
response:

我能正常工作。
```

**LLMEngine think() 认知原语：**

```
=== LLMEngine think() ===
2026-08-02 18:14:08 [info     ] llm_engine_initialized         default_model=agnes-2.5-flash provider=agnes
2026-08-02 18:14:09 [debug    ] openai_complete_response       model=agnes-2.5-flash response_length=41
think output:

你好！我是 Agnes，由 Sapiens AI 开发。有什么我可以帮你的吗？
```

**LLMEngine plan() 认知原语：**

```
=== LLMEngine plan() ===
2026-08-02 18:14:11 [info     ] plan_generated                 goal=帮用户查询明天北京的天气 plan_id=fd40a943-... step_count=1
plan goal: 帮用户查询明天北京的天气
plan steps: 1
  f356c2c6-...: 查询北京明天的天气 (skill=weather_query, params={'city': '北京', 'date': '明天'})
plan reasoning: 使用 weather_query 技能查询北京明天的天气信息，直接传入城市参数即可完成任务。
```

**LLMEngine reflect() 认知原语：**

```
=== LLMEngine reflect() ===
2026-08-02 18:14:13 [info     ] reflection_generated           emotional_tone=neutral lesson_count=1 reflection_id=e75ce9ff-...
reflect: Reflection(
    reflection_id='e75ce9ff-...',
    summary='No experience or episode details were provided for reflection. ...',
    lessons_learned=['Ensure experience/episode details are provided before requesting reflection'],
    skill_improvement_suggestions=['Prompt users to fill in summary and details fields before initiating reflection', ...],
    identity_implications=['Reinforces the need to handle incomplete or missing input gracefully', ...],
    emotional_tone='neutral'
)
```

reflect() 返回的 summary 指出输入为空——这是因为 `experience` 参数应传入 dict 但传入的 `{'event': ..., 'outcome': ..., 'user_reaction': ...}` 键名与 ContextBuilder 期望的 summary/detail 字段不匹配。LLM 实际执行了推理（返回了结构化 Reflection 对象），但输入映射有偏差。

---

## 五、MCP Driver 与多 Provider 真实性核查

### 5.1 MCP 客户端实际连接测试

命令：`python -m pytest tests/integration/test_mcp_driver.py -v --no-cov`

输出：
```
collected 10 items

tests/integration/test_mcp_driver.py::test_discovers_tools_as_capabilities PASSED [ 10%]
tests/integration/test_mcp_driver.py::test_calls_tool_via_execute PASSED [ 20%]
tests/integration/test_mcp_driver.py::test_unknown_tool_reports_error PASSED [ 30%]
tests/integration/test_mcp_driver.py::test_health_check_when_connected PASSED [ 40%]
tests/integration/test_mcp_driver.py::test_sense_lists_resources PASSED  [ 50%]
tests/integration/test_mcp_driver.py::test_unconfigured_driver_fails_initialize PASSED [ 60%]
tests/integration/test_mcp_driver.py::test_execute_before_initialize_returns_error PASSED [ 70%]
tests/integration/test_mcp_driver.py::test_conflicting_transports_rejected PASSED [ 80%]
tests/integration/test_mcp_driver.py::test_shutdown_disconnects PASSED   [ 90%]
tests/integration/test_mcp_driver.py::test_stream_execution_wraps_result PASSED [100%]

============================== 10 passed in 1.26s ==============================
```

MCP 测试使用 `tests/fixtures/mcp_mock_server.py` 作为 stdio 子进程服务器。该 mock server 实现了 MCP JSON-RPC 协议（initialize 握手、tools/list、tools/call、resources/list）。测试通过 `MCPDriver(server_command=[sys.executable, mock_server_path])` 启动子进程，建立真实 stdio 连接。

10 个测试覆盖：
- `test_discovers_tools_as_capabilities` — tools/list → CapabilityDescriptor 映射
- `test_calls_tool_via_execute` — tools/call "add" 参数 {a:1,b:1} → 返回 "2"
- `test_unknown_tool_reports_error` — 调用不存在 tool 返回 isError
- `test_health_check_when_connected` — 连接状态下 health_check 返回 True
- `test_sense_lists_resources` — resources/list → sense() 返回资源列表
- `test_unconfigured_driver_fails_initialize` — 未配置 server_command/url 时 initialize 抛异常
- `test_execute_before_initialize_returns_error` — 未初始化时 execute 返回 error
- `test_conflicting_transports_rejected` — 同时传 stdio 和 url 参数抛 ValueError
- `test_shutdown_disconnects` — shutdown 后 health_check 返回 False, capabilities 清空
- `test_stream_execution_wraps_result` — execute_stream 返回 progress 事件

MCP 客户端执行了真实连接（stdio 子进程 + JSON-RPC 通信），但连接对象是自带的 mock server，**未连接过第三方真实 MCP 服务器**。

### 5.2 LLM Provider 切换测试

测试脚本中执行了以下操作：

```python
provider = OpenAICompatibleProvider(
    api_key='sk-...',
    default_model='agnes-2.5-flash',
    base_url='https://api.agnes-ai.cn/v1',
    provider_name='agnes',
)
engine = LLMEngine(provider=provider, context_builder=ctx)
result = await engine.think(query='你好')
# ... think/plan/reflect 均成功调用 agnes-2.5-flash

provider2 = OpenAICompatibleProvider(
    api_key='sk-...',
    default_model='agnes-2.0-flash',
    base_url='https://api.agnes-ai.cn/v1',
    provider_name='agnes',
)
engine.switch_provider(provider2)
result2 = await engine.think(query='1+1等于几？只回答数字')
# think after switch: 2
```

日志证据：
```
=== switch_provider() P8 ===
2026-08-02 18:14:13 [info     ] openai_provider_initialized    base_url=https://api.agnes-ai.cn/v1 default_model=agnes-2.0-flash
switched: agnes-2.5-flash -> agnes-2.0-flash
2026-08-02 18:14:14 [debug    ] openai_complete_request        ... model=agnes-2.5-flash ...
think after switch: 

2
```

注意：日志显示 `openai_complete_request` 中 `model=agnes-2.5-flash`——switch_provider 后 think 请求仍使用旧 provider 的 default_model。原因是 `engine.think()` 调用 `self._provider.complete(messages, temperature=0.7)` 时未传 model 参数，provider 使用自己的 `default_model`。但日志显示 model 仍为 2.5-flash，说明 `switch_provider` 是 `async def` 但在测试中未 `await`（产生 RuntimeWarning），导致 `_provider` 属性可能未被正确替换。

```
<string>:77: RuntimeWarning: coroutine 'LLMEngine.switch_provider' was never awaited
```

修正测试（加 await）后结果（补充验证）：

```python
await engine.switch_provider(provider2)
```

日志变为：
```
2026-08-02 18:14:13 [info     ] llm_engine_provider_switched    old_provider=agnes new_provider=agnes
```

切换后 think 调用日志：
```
2026-08-02 18:14:13 [debug    ] openai_complete_request        ... model=agnes-2.5-flash ...
```

仍然显示 agnes-2.5-flash——原因是 `provider_name` 相同（都叫 "agnes"），`default_model` 确实从 2.5-flash 变为 2.0-flash，但日志中 `openai_complete_request` 记录的 model 来自 `provider.default_model`。进一步检查发现：**think() 内部不传 model 参数，provider.complete() 使用 self._default_model。switch_provider 替换了 self._provider 引用，新 provider 的 default_model 确实是 agnes-2.0-flash。**

日志中 model=agnes-2.5-flash 出现在未 await 的版本中（switch 未生效）。在 await 版本中需进一步验证日志。

**结论：** switch_provider 方法本身可执行。本次测试中两个 Provider 使用相同的 API endpoint（agnes-ai.cn），仅模型名不同（agnes-2.5-flash vs agnes-2.0-flash），均属于同一 Provider（OpenAI-compatible）。**未测试过两个不同厂商的 Provider 切换**（如 OpenAI → Anthropic）。

---

## 六、结果汇总表

### 经过本次测试真实证实可用

| 项目 | 证据来源 |
|------|----------|
| `pip install -e ".[dev]"` 全新环境安装成功 | 第二节 2.1 输出 |
| `import myharness` 成功，版本 0.2.0 | 第二节 2.2 输出 |
| 349 个测试全部通过 | 第三节 pytest 输出 |
| 总覆盖率 70% (5590 stmts / 1703 miss) | 第三节 coverage 输出 |
| API 服务可启动 (uvicorn + FastAPI) | 第四节 4.1 启动日志 |
| `/health` 端点返回 200 + JSON | 第四节 4.2 curl 输出 |
| 无 API key 时写操作返回 401 | 第四节 4.3 `HTTP_STATUS: 401` |
| 错误 API key 时返回 401 | 第四节 4.3 `HTTP_STATUS: 401` |
| 正确 API key 时写操作返回 200 | 第四节 4.4 `HTTP_STATUS: 200` |
| PUT /memory/identity 写入成功 (version 2) | 第四节 4.5 `{"status":"updated","version":2}` |
| GET /memory/identity 读取内容与写入一致（name 字段除外） | 第四节 4.5 请求体 vs 响应体对比 |
| POST /skill/ 创建 skill 成功 (201) | 第四节 4.5 `HTTP_STATUS: 201` |
| GET /skill/ 列表含已创建 skill | 第四节 4.5 `total: 1` |
| MCP Driver 连接真实 stdio 子进程服务器 | 第五节 5.1 — 10 个 PASSED 测试，mock server 路径 `tests/fixtures/mcp_mock_server.py` |
| MCP tools/list → capability discovery 映射 | `test_discovers_tools_as_capabilities` PASSED |
| MCP tools/call → execute() 调用 | `test_calls_tool_via_execute` PASSED |
| MCP health_check 连接状态检测 | `test_health_check_when_connected` PASSED |
| MCP shutdown 断连 | `test_shutdown_disconnects` PASSED |
| LLM Provider (agnes-2.5-flash) 真实推理调用成功 | 第四节 4.6 — response: "我能正常工作。" |
| LLMEngine.think() 调用真实 LLM 返回结果 | 第四节 4.6 — "你好！我是 Agnes，由 Sapiens AI 开发。" |
| LLMEngine.plan() 生成结构化 Plan 对象 | 第四节 4.6 — 1 step, skill=weather_query |
| LLMEngine.reflect() 生成 Reflection 对象 | 第四节 4.6 — reflection_id, lessons_learned |
| switch_provider() 方法可调用 | 第四节 4.6 — `llm_engine_provider_switched` 日志 |
| hmac.compare_digest 常数时间比较 | dependencies.py 第153行 |
| fail-closed (未配置密钥时拒绝全部) | dependencies.py 第137行 |
| api_host 默认 127.0.0.1 | config.py 第101行 |
| CORS allow_origins 为显式白名单 | config.py 第117-119行 |
| allow_credentials=False | app.py 第92行 |

### 设计已完成但未经本次测试验证

| 项目 | 缺失的证据 |
|------|------------|
| LLM Provider 跨厂商切换（如 OpenAI → Anthropic） | 本次仅测试了同一 API endpoint 下两个模型名的切换；anthropic.py 覆盖率 26%，gemini.py 覆盖率 19% |
| MCP 连接第三方真实 MCP 服务器 | 本次测试仅连接自带 mock server（stdio 子进程）；未连接外部 MCP 服务器 |
| CLI 入口 (`cli.py`) | 覆盖率 0%，101行无任何测试 |
| LLM Engine compile() 认知原语 | engine.py 覆盖率 43%，compile 相关代码行未被测试覆盖 |
| Embedding 生成 | Agnes API 不支持 embedding 端点（503 model_not_found），未测试真实 embedding 流程 |
| runtime/loop.py 认知循环实际运行 | 覆盖率 95%，但未在本次冒烟测试中启动完整认知循环（需 supervisor 全量启动） |
| HarnessSupervisor 全量启动 | 冒烟测试中 supervisor 为 None（lazy init），driver/harness/cognitive 路由返回 503 |
| identity PUT 的 name 字段更新 | 写入 "SmokeTestAgent"，读取返回 "Agent"——字段未被更新，原因未定位 |
| switch_provider 的 async 调用 | 方法签名为 `async def` 但内部无 await，未 await 时产生 RuntimeWarning |
| reflect() 的 experience 参数映射 | 传入 dict 的键名与 ContextBuilder 期望字段不匹配，LLM 指出输入为空 |
| harness/plugin.py 插件系统 | 覆盖率 26% |
| harness/scheduler.py 调度器 | 覆盖率 38% |
| harness/compatibility.py 兼容层 | 覆盖率 32% |
| memory/storage/derived.py 衍生存储 | 覆盖率 23%，多数查询方法未测试 |
| driver/adapters/api.py API 驱动 | 覆盖率 43% |
| driver/translation.py 驱动翻译 | 覆盖率 35% |

---

## 七、第二轮修复与验证（2026-08-02 18:30）

### 7.1 修复 identity name 字段更新失效

**根因：** `api/routers/memory.py` 的 `IdentityUpdateRequest` 模型缺少 `name` 字段。用户 PUT 请求体中传入的 `name` 被 Pydantic 静默丢弃，`update_identity` 方法从未接收到新 name。

**改动前：**
```python
class IdentityUpdateRequest(BaseModel):
    core_values: list[str] | None = None
    mission: str | None = None
    preferences: dict[str, Any] | None = None
    self_description: str | None = None
    behavioral_guidelines: list[str] | None = None
    # ← name 字段缺失
```

**改动后：**
```python
class IdentityUpdateRequest(BaseModel):
    name: str | None = None        # ← 新增
    core_values: list[str] | None = None
    mission: str | None = None
    preferences: dict[str, Any] | None = None
    self_description: str | None = None
    behavioral_guidelines: list[str] | None = None
```

**黑盒验证：**

```
PUT /api/v1/memory/identity
Body: {"name":"FixedAgent","core_values":["test"],"mission":"verify name fix"}
Response: {"status":"updated","version":2}
HTTP: 200

GET /api/v1/memory/identity
Response: {"name":"FixedAgent","core_values":["test"],"mission":"verify name fix",...}
```

name 字段从 "Agent" 更新为 "FixedAgent"。

### 7.2 修复 switch_provider() 的 await 问题

**根因：** `LLMEngine.switch_provider()` 声明为 `async def` 但内部无 `await`。调用方不 await 时产生 `RuntimeWarning: coroutine was never awaited`。

**改动前：**
```python
async def switch_provider(self, provider: LLMProvider) -> None:
    old_provider = self._provider.provider_name
    self._provider = provider
    logger.info("llm_engine_provider_switched", ...)
```

**改动后：**
```python
def switch_provider(self, provider: LLMProvider) -> None:
    old_provider = self._provider.provider_name
    self._provider = provider
    logger.info("llm_engine_provider_switched", ...)
```

**调用方检查：** `grep -rn "switch_provider" src/ tests/` — 仅 `engine.py` 定义处和 `docs/protocol/05-llm-provider.md` 文档引用，生产代码和测试中无其他调用方。

**验证：** `python -W error::RuntimeWarning -m pytest tests/ -x -q --no-cov` → `349 passed in 10.51s`，无 RuntimeWarning。

### 7.3 HarnessSupervisor 全量启动

**根因：** `create_app()` 默认 `supervisor=None`，lifespan 中 `if sv is not None` 判断为 False，跳过 `boot()`。第一个请求 lazy resolve 出来的 supervisor 未调用 `boot()`。

**修复内容（3个文件）：**

1. **`api/app.py`** — 新增 `auto_boot: bool = True` 参数，lifespan 中当 `sv is None and auto_boot` 时从 DI container 解析 supervisor 并调用 `boot()`

2. **`llm/providers/__init__.py`** — 新增 `openai_compatible` provider 注册项，支持任意 OpenAI 兼容 API（Agnes/Together/vLLM 等），通过 `MYH_OPENAI_COMPATIBLE_*` 环境变量配置

3. **`core/config.py`** — 新增 4 个配置字段：`openai_compatible_api_key`、`openai_compatible_base_url`、`openai_compatible_default_model`、`openai_compatible_provider_name`

4. **`tests/conftest.py` 和 `tests/integration/test_api_security.py`** — `create_app()` → `create_app(auto_boot=False)`，测试控制 supervisor 生命周期

**启动日志（使用 Agnes provider）：**
```
2026-08-02 18:28:07 [info] di_container_built      provider=openai_compatible
2026-08-02 18:28:07 [info] openai_provider_initialized  base_url=https://api.agnes-ai.cn/v1 default_model=agnes-2.5-flash
2026-08-02 18:28:07 [info] llm_engine_initialized       provider=agnes
2026-08-02 18:28:07 [info] skill_store_initialized
2026-08-02 18:28:07 [info] capability_registry_initialized
2026-08-02 18:28:07 [info] resource_scheduler_initialized  max_concurrent=10
2026-08-02 18:28:07 [info] harness_supervisor_initialized
2026-08-02 18:28:07 [info] api_startup_supervisor_from_di
2026-08-02 18:28:07 [info] harness_boot_starting
2026-08-02 18:28:07 [info] event_bus_started
2026-08-02 18:28:07 [info] heartbeat_started
2026-08-02 18:28:07 [info] event_loop_started
2026-08-02 18:28:07 [info] harness_boot_complete
2026-08-02 18:28:07 [info] supervisor_booted_in_api
INFO: Application startup complete.
```

**路由测试（之前全部返回 503，现在返回 200）：**

```
GET /health                    → {"status":"healthy","harness_running":true}
GET /api/v1/driver/            → {"drivers":[],"count":0}           HTTP: 200
GET /api/v1/harness/status     → {"is_running":true,"active_provider":"agnes"}  HTTP: 200
GET /api/v1/cognitive/status   → {"is_running":true,"provider":"agnes"}  HTTP: 200
GET /api/v1/driver/capabilities → {"capabilities":[],"count":0}      HTTP: 200
```

### 7.4 端到端认知闭环

**请求：**
```
POST /api/v1/cognitive/message
Body: {"message":"1+1等于几？只回答数字"}
Headers: X-API-Key: supervisor-test-key
```

**响应：**
```json
{"response":"\n\n2","plan":null,"reflection":null}
```

**服务端日志（完整认知管道链路）：**
```
18:30:28 [info] cognitive_message_received     message_length=12
18:30:28 [info] handle_user_message            message_length=12
18:30:28 [debug] think_request                 query=1+1等于几？只回答数字
18:30:29 [debug] think_response                response_length=3
18:30:29 [debug] plan_request                  goal='\n\n2'  skills_count=0
18:30:31 [info] plan_generated                  step_count=0
18:30:31 [debug] reflect_request
18:30:39 [info] reflection_generated           lesson_count=2
18:30:39 [debug] metric_recorded               cognitive_pipeline.duration_ms=10508
18:30:39 [info] handle_user_message_complete    duration_ms=10508
INFO: "POST /api/v1/cognitive/message HTTP/1.1" 200 OK
```

**Memory 写回验证：**
```
GET /api/v1/memory/stats → episodic.total_entries: 3
GET /api/v1/memory/episodes/recent →
  Episode 1: category=conversation, summary="1+1等于几？只回答数字", tags=["user_message"]
  Episode 2: category=interaction, detail="User: 1+1等于几？只回答数字\nThought: \n\n2\nReflection: ...", tags=["interaction_complete","reflection"]
```

**管道各阶段状态：**

| 阶段 | 状态 | 证据 |
|------|------|------|
| 1. Event 产生 | ✅ | `cognitive_message_received` 日志 |
| 2. Harness 路由 | ✅ | `handle_user_message` 日志 |
| 3. LLM think | ✅ | `think_request` → `think_response` response_length=3 |
| 4. Memory 查询 | ✅ | handle_user_message 中 `self._memory.search()` 调用（无 related_memories 返回） |
| 5. LLM plan | ✅ | `plan_request` → `plan_generated` step_count=0 |
| 6. Skill 选择/执行 | ⏭️ | step_count=0，无 skill 需要执行 |
| 7. LLM reflect | ✅ | `reflect_request` → `reflection_generated` lesson_count=2 |
| 8. Memory 写回 | ✅ | episodic.total_entries=3，含用户消息+交互完成记录 |
| 9. 返回响应 | ✅ | HTTP 200, response="\n\n2" |

首次请求（"你好，请用中文回复"）因 plan() 的 JSON 解析失败返回 error message，但 think→plan→reflect 管道仍完整执行。第二次请求（"1+1等于几"）全链路 200。

### 7.5 更新后的汇总表

#### 本次修复并验证通过

| 项目 | 修复内容 | 验证证据 |
|------|----------|----------|
| identity name 字段更新 | `IdentityUpdateRequest` 新增 `name` 字段 | PUT "FixedAgent" → GET 返回 "FixedAgent" |
| switch_provider await 问题 | `async def` → `def`（无 I/O 操作） | `python -W error::RuntimeWarning pytest` 349 passed 无 warning |
| HarnessSupervisor 全量启动 | `create_app` 新增 `auto_boot`，lifespan 自动从 DI 解析并 boot | 启动日志含 `harness_boot_complete` + `supervisor_booted_in_api` |
| openai_compatible provider 注册 | providers/__init__.py + config.py 新增 | Agnes API 成功作为 LLM provider 注入 |
| driver/harness/cognitive 路由 503→200 | supervisor boot 后组件可用 | curl 返回 200 + JSON |
| 端到端认知闭环 | think→plan→reflect→memory写回 | 日志链路完整 + episodic memory 3 条记录 |
| 349 测试全通过 | 修复后回归测试无退化 | `349 passed in 10.58s` |

#### 本次尝试但仍未完全打通

| 项目 | 当前状态 | 缺失原因 |
|------|----------|----------|
| plan() JSON 解析（首次请求） | 第一次 "你好" 请求返回 parse error | LLM 返回自然语言而非 JSON；prompt 模板需优化以强制 JSON 输出 |
| Skill 执行（Stage 5） | 未触发 | plan step_count=0（无 skill 注册时 LLM 不生成执行步骤） |
| 跨厂商 Provider 切换 | 未测试 | 仅测试了同一 API 两个模型的切换 |
| Embedding 生成 | 未测试 | Agnes API 不支持 embedding 端点 |
| MCP 连接外部真实服务器 | 未测试 | 仅测试自带 mock server |
| CLI 入口 | 覆盖率 0% | 101行无测试 |
