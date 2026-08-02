# MyHarness - Cognitive Operating System

MyHarness (MYH) 是一个认知操作系统，实现了LLM Agent的四权分离架构：Compute(算力)、Memory(记忆)、Skill(能力)、Execution(执行)完全解耦。

> **v0.2.0**（2026-08-02）：协议文档 14.1–14.5 落地（`docs/protocol/`）、Event 强类型化、MCP 真实驱动（官方 SDK）、349 测试通过 / 覆盖 70%。

## 协议规范（Protocol v0.1，依据设计稿 §14）

| 规范 | 文档 | 状态 |
|---|---|---|
| 14.1 Event Schema | `docs/protocol/01-event-schema.md` | ✅ 已实现（priority + 强类型载荷） |
| 14.2 Memory API | `docs/protocol/02-memory-api.md` | ✅ 已实现 |
| 14.3 Skill Interface | `docs/protocol/03-skill-interface.md` | ✅ 已实现 |
| 14.4 Execution Driver | `docs/protocol/04-execution-driver.md` | ✅ 已实现（含 MCP SDK 客户端） |
| 14.5 LLM Provider | `docs/protocol/05-llm-provider.md` | ✅ 已实现（多 Provider 可插拔） |

## 项目文档

- 工程计划：`docs/PROJECT_PLAN.md` · 进度追踪：`PROGRESS.md` · 代码审查：`docs/REVIEW_REPORT.md` · 开源调研：`docs/OPENSOURCE_SURVEY.md`

## 架构原则

- **P0**: LLM 是认知运行时，不是身份容器
- **P1**: 单一认知中心
- **P2**: 四权分离
- **P3**: 身份外置 (Identity 归属 Memory)
- **P4**: 事件驱动
- **P5**: 能力沉淀 (经验→Skill)
- **P6**: 计算最小化
- **P7**: 协议优先
- **P8**: 可插拔算力
- **P9**: 原始/衍生数据分离

## 快速开始

```bash
# 安装依赖
pip install -e ".[dev]"

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 LLM API Keys

# 运行测试
pytest

# 启动 API 服务
uvicorn myharness.api.app:create_app --reload
```

## 项目结构

```
src/myharness/
├── core/          # 配置、依赖注入、异常、日志
├── schema/        # Pydantic 数据模型
├── bus/           # 事件总线、路由
├── memory/        # 记忆系统 (Identity/Episodic/Semantic/Relationship)
├── llm/           # LLM 引擎 (多Provider适配)
├── skill/         # 能力商店
├── harness/       # 核心枢纽层
├── runtime/       # 运行时循环
├── driver/        # 执行驱动抽象
└── api/           # FastAPI REST API
```
