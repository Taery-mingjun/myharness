# MyHarness (MYH) 源代码导出

生成时间: 2026-08-02
总文件数: 94 个 .py 文件
总行数: 13531 行

## 目录树

```
├── api
│   ├── middleware
│   │   ├── __init__.py
│   │   ├── error_handler.py
│   │   └── tracing.py
│   ├── routers
│   │   ├── __init__.py
│   │   ├── cognitive.py
│   │   ├── driver.py
│   │   ├── harness.py
│   │   ├── health.py
│   │   ├── memory.py
│   │   └── skill.py
│   ├── __init__.py
│   ├── app.py
│   └── dependencies.py
├── bus
│   ├── __init__.py
│   ├── dispatcher.py
│   ├── middleware.py
│   ├── result.py
│   └── router.py
├── core
│   ├── __init__.py
│   ├── config.py
│   ├── di.py
│   ├── exceptions.py
│   ├── logging.py
│   └── types.py
├── driver
│   ├── adapters
│   │   ├── __init__.py
│   │   ├── api.py
│   │   ├── browser.py
│   │   ├── computer.py
│   │   ├── database.py
│   │   ├── iot.py
│   │   ├── mcp.py
│   │   └── robot.py
│   ├── __init__.py
│   ├── capability.py
│   ├── protocol.py
│   └── translation.py
├── harness
│   ├── __init__.py
│   ├── compatibility.py
│   ├── monitor.py
│   ├── permission.py
│   ├── plugin.py
│   ├── registry.py
│   ├── scheduler.py
│   └── supervisor.py
├── llm
│   ├── prompts
│   │   ├── __init__.py
│   │   ├── compile.py
│   │   ├── identity.py
│   │   ├── memory.py
│   │   ├── plan.py
│   │   ├── reflect.py
│   │   └── think.py
│   ├── providers
│   │   ├── __init__.py
│   │   └── openai.py
│   ├── __init__.py
│   ├── context.py
│   ├── engine.py
│   └── interfaces.py
├── memory
│   ├── indexing
│   │   ├── __init__.py
│   │   ├── base.py
│   │   ├── text.py
│   │   └── vector.py
│   ├── storage
│   │   ├── __init__.py
│   │   ├── derived.py
│   │   └── source.py
│   ├── stores
│   │   ├── __init__.py
│   │   ├── episodic.py
│   │   ├── identity.py
│   │   ├── relationship.py
│   │   └── semantic.py
│   ├── __init__.py
│   ├── interface.py
│   ├── manager.py
│   └── serializer.py
├── runtime
│   ├── examples
│   │   ├── __init__.py
│   │   └── walk_obstacle.py
│   ├── __init__.py
│   ├── interrupt.py
│   ├── loop.py
│   └── state.py
├── schema
│   ├── __init__.py
│   ├── capability.py
│   ├── driver.py
│   ├── event.py
│   ├── identity.py
│   ├── memory.py
│   └── skill.py
├── skill
│   ├── __init__.py
│   ├── interface.py
│   ├── lifecycle.py
│   ├── registry.py
│   ├── storage.py
│   ├── store.py
│   └── validator.py
└── __init__.py
```

## 文件行数统计

| 行数 | 文件路径 |
|------|----------|
|    23 | src/myharness/__init__.py |
|     9 | src/myharness/api/__init__.py |
|   110 | src/myharness/api/app.py |
|   104 | src/myharness/api/dependencies.py |
|     6 | src/myharness/api/middleware/__init__.py |
|   108 | src/myharness/api/middleware/error_handler.py |
|    52 | src/myharness/api/middleware/tracing.py |
|    10 | src/myharness/api/routers/__init__.py |
|   105 | src/myharness/api/routers/cognitive.py |
|   137 | src/myharness/api/routers/driver.py |
|    91 | src/myharness/api/routers/harness.py |
|    26 | src/myharness/api/routers/health.py |
|   208 | src/myharness/api/routers/memory.py |
|   238 | src/myharness/api/routers/skill.py |
|    35 | src/myharness/bus/__init__.py |
|   372 | src/myharness/bus/dispatcher.py |
|   100 | src/myharness/bus/middleware.py |
|    85 | src/myharness/bus/result.py |
|   226 | src/myharness/bus/router.py |
|    75 | src/myharness/core/__init__.py |
|   136 | src/myharness/core/config.py |
|   175 | src/myharness/core/di.py |
|   134 | src/myharness/core/exceptions.py |
|    94 | src/myharness/core/logging.py |
|    40 | src/myharness/core/types.py |
|    27 | src/myharness/driver/__init__.py |
|    63 | src/myharness/driver/adapters/__init__.py |
|   326 | src/myharness/driver/adapters/api.py |
|   167 | src/myharness/driver/adapters/browser.py |
|   170 | src/myharness/driver/adapters/computer.py |
|   166 | src/myharness/driver/adapters/database.py |
|   168 | src/myharness/driver/adapters/iot.py |
|   166 | src/myharness/driver/adapters/mcp.py |
|   177 | src/myharness/driver/adapters/robot.py |
|    82 | src/myharness/driver/capability.py |
|   238 | src/myharness/driver/protocol.py |
|   120 | src/myharness/driver/translation.py |
|    24 | src/myharness/harness/__init__.py |
|   149 | src/myharness/harness/compatibility.py |
|   166 | src/myharness/harness/monitor.py |
|   132 | src/myharness/harness/permission.py |
|   142 | src/myharness/harness/plugin.py |
|   136 | src/myharness/harness/registry.py |
|   240 | src/myharness/harness/scheduler.py |
|   389 | src/myharness/harness/supervisor.py |
|    42 | src/myharness/llm/__init__.py |
|   266 | src/myharness/llm/context.py |
|   643 | src/myharness/llm/engine.py |
|   106 | src/myharness/llm/interfaces.py |
|    26 | src/myharness/llm/prompts/__init__.py |
|    38 | src/myharness/llm/prompts/compile.py |
|    65 | src/myharness/llm/prompts/identity.py |
|    56 | src/myharness/llm/prompts/memory.py |
|    48 | src/myharness/llm/prompts/plan.py |
|    46 | src/myharness/llm/prompts/reflect.py |
|    27 | src/myharness/llm/prompts/think.py |
|    69 | src/myharness/llm/providers/__init__.py |
|   269 | src/myharness/llm/providers/openai.py |
|    33 | src/myharness/memory/__init__.py |
|     8 | src/myharness/memory/indexing/__init__.py |
|    66 | src/myharness/memory/indexing/base.py |
|   211 | src/myharness/memory/indexing/text.py |
|   265 | src/myharness/memory/indexing/vector.py |
|   175 | src/myharness/memory/interface.py |
|   307 | src/myharness/memory/manager.py |
|   117 | src/myharness/memory/serializer.py |
|     8 | src/myharness/memory/storage/__init__.py |
|   531 | src/myharness/memory/storage/derived.py |
|   268 | src/myharness/memory/storage/source.py |
|    21 | src/myharness/memory/stores/__init__.py |
|   267 | src/myharness/memory/stores/episodic.py |
|   197 | src/myharness/memory/stores/identity.py |
|   159 | src/myharness/memory/stores/relationship.py |
|   207 | src/myharness/memory/stores/semantic.py |
|    16 | src/myharness/runtime/__init__.py |
|    11 | src/myharness/runtime/examples/__init__.py |
|   140 | src/myharness/runtime/examples/walk_obstacle.py |
|   191 | src/myharness/runtime/interrupt.py |
|   174 | src/myharness/runtime/loop.py |
|    69 | src/myharness/runtime/state.py |
|   136 | src/myharness/schema/__init__.py |
|    66 | src/myharness/schema/capability.py |
|    72 | src/myharness/schema/driver.py |
|   331 | src/myharness/schema/event.py |
|   105 | src/myharness/schema/identity.py |
|   236 | src/myharness/schema/memory.py |
|   180 | src/myharness/schema/skill.py |
|    22 | src/myharness/skill/__init__.py |
|   190 | src/myharness/skill/interface.py |
|   130 | src/myharness/skill/lifecycle.py |
|   209 | src/myharness/skill/registry.py |
|   230 | src/myharness/skill/storage.py |
|   363 | src/myharness/skill/store.py |
|   172 | src/myharness/skill/validator.py |

## 拆分说明

本导出分为以下部分：

1. `code_dump_1_core_schema.md` — core/, schema/
2. `code_dump_2_bus_memory.md` — bus/, memory/
3. `code_dump_3_llm_skill.md` — llm/, skill/
4. `code_dump_4_harness_runtime.md` — harness/, runtime/
5. `code_dump_5_driver_api.md` — driver/, api/

附：项目配置文件见 `code_dump_config.md`（pyproject.toml, .env.example, README.md, .gitignore）