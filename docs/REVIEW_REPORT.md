# S1 现有代码审查报告（vs v1.1 设计稿）

> 日期：2026-08-02 · 审查范围：src/myharness 全部 100 个源码文件 + tests 14 个测试文件
> 对照基准：`myharness1.1(1).pdf`（MyHarness Architecture Design v1.1）

## 1. 总体结论

**现有代码完成度和质量显著高于预期，属于"可修补演进"而非"需重建"。**

- ✅ **282 个测试全部通过**（63s），无失败、无 skip
- ✅ 代码覆盖率 **67%**（5359 行 / 覆盖 3574 行）
- ✅ 架构分层与设计稿**一一对应**（见 §2 对照表），连设计稿 9.1 的"中断重规划"示例都有实现（`runtime/examples/walk_obstacle.py`）
- ✅ 注释质量高，多处直接引用设计稿原则（P3/P8/P9），代码体现了对设计意图的理解
- ✅ 遗留的 2 个未提交修改均为**高质量跨平台修复，建议保留**（见 §4）

## 2. 设计稿 ↔ 实现对照表

| 设计稿章节 | 要求 | 实现位置 | 符合度 |
|---|---|---|---|
| §3 LLM Engine | 唯一职责 Thinking；排除 Memory/Skill/Identity | `llm/engine.py`：think/plan/reflect/compile + interpret_identity/propose_identity_update + switch_provider | ✅ 高 |
| §11 LLM Replaceable | Think/Plan/Reflect/Compile 统一接口，切换保留 Memory/Skill/Identity | `llm/interfaces.py`（LLMProvider 适配层）+ providers/（openai/anthropic/gemini/openai_compatible） | ✅ 高 |
| §4 Memory System | Identity/Episodic/Semantic/Relationship 四存储；Read/Write/Search/Archive | `memory/interface.py`（抽象）+ `memory/manager.py` + `memory/stores/`（四实现） | ✅ 高 |
| §4.3 原始/衍生分离 | 原始数据不可篡改；衍生可重建 | `memory/storage/source.py`（JSON/JSONL）+ `storage/derived.py`（SQLite）+ `indexing/`（FTS5/FAISS）+ `rebuild_indexes()` | ✅ 高 |
| §5 Skill Store | Skill 定义字段；生命周期 6 态；版本管理归 Harness | `skill/lifecycle.py`（状态机）+ `skill/storage.py`（semver）+ `skill/validator.py` + `harness/registry.py` | ✅ 高 |
| §6 Learning | 非独立模块，LLM 完成 | `llm/engine.py` reflect/compile + prompts/（think/plan/reflect/compile/identity/memory） | ✅ 中高 |
| §7 Harness | Capability/Driver/Event/Resource/Permission/Lifecycle/Plugin/Compatibility | `harness/` 8 个类全覆盖（registry/scheduler/monitor/permission/guard/plugin/compatibility/supervisor） | ✅ 高 |
| §8 Event Bus | 唯一数据流 Event；路由 Event→Harness→LLM→Memory→Skill→Execution | `bus/dispatcher.py`（publish/request/enqueue/subscribe）+ `bus/router.py`（RouteRule） | ✅ 高 |
| §9 Runtime | 事件驱动无模式切换；中断重规划 | `runtime/loop.py`（EventLoop）+ `runtime/interrupt.py`（InterruptHandler/replan/resume_plan）+ examples/walk_obstacle.py | ✅ 高 |
| §10 Driver | 硬件细节不暴露；Grab()→Joint/Torque/CAN/PID | `driver/protocol.py`（UnifiedDriverProtocol）+ `driver/translation.py` + adapters/（robot/browser/mcp/api/computer/database/iot 7 个） | ✅ 高 |
| §14.1 Event Schema | 通用字段：类型/来源/时间戳/载荷/优先级；各类载荷格式 | `schema/event.py`：27 种事件类 + 通用字段 | ⚠️ 中（见 §3 缺口 A/B） |
| §14.2 Memory API | Read/Write/Search/Archive 签名；四存储数据模型；隔离规范 | `memory/interface.py` + `schema/memory.py` + `schema/identity.py` | ✅ 高（缺协议文档） |
| §14.3 Skill Interface | 标准描述格式；状态迁移；版本管理 | `schema/skill.py` + `skill/lifecycle.py` | ✅ 高（缺协议文档） |
| §14.4 Execution Driver | 统一驱动协议；Capability Discovery；安全校验 | `driver/protocol.py` + `harness/guard.py`（ExecutionGuard）+ `driver/capability.py` | ✅ 高（缺协议文档） |
| §14.5 LLM Provider | Think/Plan/Reflect/Compile 标准 IO；切换迁移规范 | `llm/interfaces.py` + `llm/engine.py` | ✅ 高（缺协议文档） |
| §7.2 Permission | 执行前安全校验 | `harness/permission.py` + `harness/guard.py` + API 认证 fail-closed（.env.example） | ✅ 高 |

## 3. 缺口与偏离清单

### P0（影响设计稿符合度，建议 S4 必做）

- **A. Event Schema 缺 priority 字段**：设计稿 14.1 明确通用字段含"优先级"，`BaseEvent` 无 `priority`，调度器无法做优先级排序（`harness/scheduler.py` 目前无优先级概念）
- **B. 事件载荷未强类型化**：27 种事件类的 `payload` 全部为 `dict[str, Any]`，载荷格式仅写在 docstring 注释里。设计稿要求"定义各类 Event 各自的载荷格式"——应改为 pydantic 强类型（如 `UserMessagePayload` 等）
- **C. 协议文档缺失**：`docs/protocol/` 目录不存在。设计稿 14.x 的五个协议规范（Event Schema / Memory API / Skill Interface / Execution Driver / LLM Provider）只有代码实现，没有规范化文档——这是"Protocol v0.1 规范化路线图"的核心交付物

### P1（完善度，建议 S4 处理）

- **D. skill 模块测试覆盖不足**：validator.py 60%、store.py 67%、registry.py 62%、semantic.py 61%——skill 三层（存储/注册/校验）是设计稿 §5 的核心，测试应补到 ≥85%
- **E. Memory 接口与设计稿 §4.1 形态差异**：设计稿的泛化 `Read()/Write()/Search()/Archive()` 在实现中按 store 细分（get_identity/record_episode/search...），行为上等价且更优，但协议文档（C）需给出两者映射，避免歧义
- **F. LLM Provider 底层接口风格**：`LLMProvider.complete()/embed()` 是 chat-completion 风格，Think/Plan/Reflect/Compile 在 LLMEngine 层组合——符合设计（§11 的 Think 等是引擎层原语），但协议文档（C）需明确两层边界

### P2（可选优化）

- **G. 覆盖率低区**：relationship.py 81%（52-54 等行）可补；skill/storage.py 的 `_sort_semver` 建议直接测
- **H. API 认证**：.env.example 已声明 fail-closed（MYH_API_KEY 为空则拒绝写操作），但未见专门测试文件（test_api_security.py 存在，需确认覆盖）

## 4. 遗留未提交修改评估（旧会话产物）

| 文件 | 内容 | 评估 |
|---|---|---|
| `memory/storage/source.py` | Windows 并发写入修复：O_APPEND 非原子 → `threading.Lock` 串行化追加；`os.replace` PermissionError 重试（20 次） | ✅ **保留并提交**——修复真实数据丢失风险，注释充分 |
| `tests/integration/test_runtime_loop.py` | Unix-only `resource.getrusage` → 跨平台 `time.process_time()` | ✅ **保留并提交**——修复 Windows 无法跑测试的问题 |

## 5. 对 S3 的建议输入

1. **无需重建**：现有代码是坚实的 v1.1 实现基础，S4 应在其上补齐缺口而非推翻
2. **S4 优先级建议**：C（协议文档，五份）→ A/B（Event Schema 规范化）→ D（skill 测试补强）→ 其余 P1/P2
3. **安全项**：旧计划 B2/B3/B4（登录限速、shell 沙箱、TLS）与现有 API fail-closed 认证设计不冲突，可在 S4 后期评估纳入
4. 待 S2 开源调研结果回来，与本报告合并形成 S3 决策
