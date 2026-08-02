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
│   ├── supervisor.py    # 中央编排器
│   ├── guard.py         # 执行权限门
│   ├── healing.py       # 自愈合（DriftDetector + RollbackManager）
│   └── reflex.py        # 小脑反射层（§6.5）
├── runtime/       # 运行时循环
├── driver/        # 执行驱动抽象
└── api/           # FastAPI REST API
```

## Reflex Layer（小脑反射层，架构 v1.2 §6.5）

Stable Skill 经过连续成功调用达到阈值后，可被晋升到 Reflex Index。
晋升后的 Skill 在匹配到触发指纹时直接执行，跳过 think→plan 完整流程，
LLM 仅做参数填充。

- **晋升条件**：Skill 状态为 Stable + DriftDetector 记录连续成功 ≥5 次
- **触发方式**：关键词匹配（支持 CJK）或正则规则
- **时间复杂度**：O(k)，k = 反射索引中的触发器数量，不随 Memory 或 Skill Store 总量增长
- **降级安全**：未命中时无缝放行到完整认知流程

```python
from myharness.harness.reflex import ReflexIndex

reflex = ReflexIndex(skill_store=store, drift_detector=detector)
await reflex.promote_to_reflex(skill_id)  # 需满足晋升条件

match = reflex.match(user_message)  # O(k) 查找
if match:
    # 直接执行 skill，跳过 think/plan
else:
    # 放行到完整 think→plan→reflect 流程
```

## 自愈合机制（Phase 1）

- **DriftDetector**：SQLite 持久化采集 Skill 成功率、Identity 否决次数、异常响应率
- **RollbackManager**：生成回滚候选，人工确认后才执行回滚
- 触发条件：连续 N 次失败（默认 5，可配置）
