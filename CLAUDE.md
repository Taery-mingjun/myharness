# MyHarness — 项目记忆（CLAUDE.md）

## 项目目标

**MyHarness（MYH）**：一个认知操作系统（Cognitive Operating System），实现 LLM Agent 的**四权分离**架构——Compute（算力）、Memory（记忆）、Skill（能力）、Execution（执行）完全解耦。

- 远程仓库（唯一真相源）：`https://gitee.com/Taery-mingjun/myharness`
- 本工程目录：`C:\Users\10444\gitee_myharness_fetch\myharness\`（git 克隆，remote = origin/main）
- 核心大纲：桌面 `C:\Users\10444\Desktop\myharness1.1(1).pdf`（MyHarness Architecture Design v1.1，2026-08-02）

> ⚠️ **工程边界**：本工程是 myharness 的**唯一**工作目录。桌面的 `JARVIS_CONSOLE`、`jarvis-carrier-protocol`、`Harness+v2.0（最终定稿）.pdf` 等是其他项目/历史文档，**不要混淆、不要在本工程中引用其内容**。与设计文档冲突时以 `myharness1.1(1).pdf` 为准。

## 核心大纲（v1.1 设计文档要点）

### 设计哲学
LLM ≠ Agent ≠ Memory ≠ Skill ≠ Execution ≠ Hardware。所有模块完全解耦，可独立升级、替换、迁移。**系统中只有一个认知实体：LLM，其余均为资源或执行组件。**

### 分层架构
| 层 | 职责 | 要点 |
|---|---|---|
| Layer 1 LLM Engine | 唯一职责 Thinking | Reasoning / Planning / Routing / Reflection / Decision Making / Identity Interpretation / Identity Update Proposal。**不保存** Memory、Skill、Identity |
| Layer 2 Memory System | 记忆是数据库，不是 Prompt/Context | 四类子存储：Identity（Core Values/Mission/Preferences/Self Description）、Episodic（Events/Experiences/Conversations）、Semantic（Knowledge/Concepts）、Relationship（User Relationship/Social Context）。接口：Read/Write/Search/Archive |
| Layer 3 Skill Store | 执行模板，无思考能力 | Skill 字段：Name/Version/Input/Output/Parameters/Boundary/Capability/Confidence。生命周期：Draft→Testing→Verified→Stable→Deprecated→Archived。版本管理归属 Harness |
| Learning | 非独立模块，归属 LLM | Experience→Reflection→Trial→Parameter Tuning→Validation→Skill Update |
| Harness Layer | **Agent Driver Protocol**（类比 Windows Driver/CUDA/HAL/POSIX），非 Framework/Agent/Memory | Capability Discovery / Driver Adaptation / Event Routing / Resource Scheduling / Permission / Lifecycle / Plugin / Compatibility |
| Event Bus | 系统内唯一数据流：Event | 路由：Event → Harness → LLM → Memory → Skill → Execution |
| Runtime | 无模式切换，纯事件驱动 | 例：Walk(执行中 Skill) → Obstacle(Event) → LLM 重新规划 → Skill 重新参数化 → 继续执行 |
| Driver 抽象 | 硬件细节不向上暴露 | 例：上层调用 Grab()，Harness 翻译为 Joint/Torque/CAN/PID |

### 工程原则 P0–P9
- **P0** LLM 是认知运行时，不是身份容器
- **P1** 单一认知中心（只有 LLM 负责推理/规划/学习/路由）
- **P2** 四权分离（Compute/Memory/Skill/Execution 解耦）
- **P3** 身份外置（Identity 归属 Memory，LLM 仅持 Interpretation/Update Proposal 接口）
- **P4** 事件驱动
- **P5** 能力沉淀（经验经 LLM 反思沉淀为 Skill，不直接进运行时上下文）
- **P6** 计算最小化（优先调用已有 Skill，缺失/冲突/失效时才启用 LLM 深度推理）
- **P7** 协议优先（定义统一驱动协议，不绑定任何具体平台）
- **P8** 可插拔算力（LLM 可替换：Think/Plan/Reflect/Compile 统一接口；切换时 Memory/Skill/Identity 完全保留）
- **P9** 原始/衍生数据分离（原始数据如 experience.jsonl/identity.json/knowledge.json 必须持久化不可篡改；衍生数据如 embeddings.index/检索缓存可删除重建）

### Protocol v0.1 规范化路线图（14.x）
1. **14.1 Event Schema** — 通用字段（类型/来源/时间戳/载荷/优先级）+ 各类事件载荷格式
2. **14.2 Memory API** — ⚠️ **建议优先实施**（已有实测经验：衍生数据分离、索引重建可行性已验证）
3. **14.3 Skill Interface** — 标准描述格式、生命周期状态迁移、版本管理
4. **14.4 Execution Driver Interface** — 统一驱动协议、Capability Discovery、安全校验接口
5. **14.5 LLM Provider Interface** — Think/Plan/Reflect/Compile 标准输入输出、引擎切换迁移规范

实施顺序：**优先 Memory API（含 Identity 子系统）**；Skill Interface 与 Execution Driver Interface 待接入真实执行设备后再具体化，避免过度设计。

## 当前工程状态（2026-08-02）

- **git**：仅 1 个提交 `373c4b3 fix(api): PUT /memory/identity rejected every request it ever received`；有未提交修改：`src/myharness/memory/storage/source.py`、`tests/integration/test_runtime_loop.py`
- **技术栈**：Python ≥3.11、hatchling 构建、FastAPI/uvicorn、pydantic v2、aiosqlite、faiss-cpu、lagom（DI）、networkx、structlog；dev 依赖 pytest + pytest-asyncio + ruff + mypy(strict)
- **源码结构**（src/myharness/）：core（配置/DI/异常/日志）、schema、bus（事件总线）、memory、llm、skill、harness（含 guard/monitor/compatibility）、runtime、driver（adapters: robot/browser/mcp/api/computer/database/iot）、api（FastAPI：routers 含 memory/skill/harness/driver/cognitive/health）
- **测试**：tests/ 下 unit/ + integration/（含 test_runtime_loop.py），conftest.py 提供夹具
- **环境**：`.venv/` 已建；`.env.example` 可复制为 `.env` 填 LLM API Keys
- **待确认参考**：`C:\Users\10444\.claude\plans\myharness-bubbly-cloud.md` 是旧会话（安全审计向）写的 B2/B3/B4 落地计划（登录限速、shell 沙箱、TLS 前置）——**尚未与本 v1.1 大纲对齐，执行任何内容前需用户确认**

## 工作约定（防多会话混乱）

1. **所有会话必须在本目录打开**（`cd C:\Users\10444\gitee_myharness_fetch\myharness`），不要从 C:\Users\10444 或 D:\Microsoft VS Code 根目录开工作会话
2. 新任务先看本文件；已读过的进度不要再重复摸索
3. 修改前先 `git status` 确认工作区状态；commit/push 需用户明确要求
4. 需要恢复上下文时用 `/resume` 恢复旧会话，不要开新会话从头做
5. 涉及设计方案的问题，先读桌面 `myharness1.1(1).pdf`（本文件已含摘要，细节查 PDF）
