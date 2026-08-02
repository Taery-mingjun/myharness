# Protocol 14.5 — LLM Provider Interface 规范

> 设计稿依据：MyHarness v1.1 §3（LLM Engine）、§11（LLM Replaceability）、§14.5（LLM Provider Interface）
> 代码实现：`src/myharness/llm/`（interfaces/engine/context/prompts/providers）
> 版本：v0.1（2026-08-02）· 状态：已实现 ✅

## 1. 目的

LLM 属于 **Compute Provider**（§11.1），是**可插拔算力**（P8）。本规范定义两层接口：

1. **Provider 适配层**（`LLMProvider`）：与具体厂商 SDK 对接的薄适配
2. **认知原语层**（`LLMEngine`）：Think / Plan / Reflect / Compile 四大认知操作 + Identity 接口

切换计算引擎时：**Harness 保留（负责新引擎适配）、Memory/Skill/Identity 完全保留**（§11.2）。

## 2. Provider 适配层（LLMProvider，interfaces.py）

| 成员 | 说明 |
|---|---|
| `provider_name` | 唯一标识（openai / anthropic / gemini / openai_compatible） |
| `complete(messages, model, temperature, max_tokens, tools) -> str` | 补全（支持工具调用定义） |
| `complete_stream(...) -> AsyncIterator[str]` | 流式补全 |
| `embed(text) -> list[list[float]]` | 嵌入生成 |
| `supported_models` / `default_model` | 模型清单与默认 |
| `health_check() -> bool` | 可达性检查 |

**已实现适配器**：`openai.py`、`anthropic.py`、`gemini.py`、`openai_compatible.py`（覆盖 DeepSeek 等 OpenAI 兼容端点——用户当前实际使用的 provider）。

## 3. 认知原语层（LLMEngine，engine.py）

| 原语 | 设计稿依据 | 输入 → 输出 |
|---|---|---|
| `think()` | §3.1 Reasoning | query/context → 思考文本 + 推理轨迹 |
| `plan()` | §3.1 Planning | 目标 → `Plan`（PlanStep 序列，可含 alternative） |
| `reflect()` | §3.1 Reflection / §6 | experience → `Reflection`（洞察 + skill/identity 提案） |
| `compile()` | §6 / 14.3 | Reflection → `SkillProposal` |
| `interpret_identity()` | §3.1 Identity Interpretation / P3 | 读取 IdentityEntry → 解释 |
| `propose_identity_update()` | §3.1 Identity Update Proposal / P3 | 经历 → `IdentityUpdateProposal` |
| `switch_provider()` | §11.2 | 运行时切换 Provider，不中断身份/记忆/技能 |
| `stream_think()` | — | think 的流式版本 |

- Prompt 模板位于 `llm/prompts/`（think/plan/reflect/compile/identity/memory，Jinja2）
- 上下文装配在 `llm/context.py`（Context 构建，防注入/长度控制）

## 4. 引擎切换迁移规范（§11.2 / §14.5）

1. 新引擎实现 `LLMProvider` 全部接口（或接入 openai_compatible）
2. `LLMEngine.switch_provider(new_provider)` 热切换；`active_provider_name` 可查询
3. 切换保留项：Identity（Memory 层持有，引擎只读）、Memory（全部存储）、Skill（全部）
4. **会话与状态迁移**：认知状态存于 `runtime/state.py`，不存 Provider 内——切换零迁移成本

## 5. 能力声明与兼容性校验（§14.5）

- `harness/compatibility.py::CompatibilityChecker.check_llm_provider_compatibility()`：验证 Provider 能力与引擎需求匹配
- Provider 的能力差异（如是否支持 tools、embed）由 `health_check` + 能力探测兜底

## 6. 待落地缺口

1. **LiteLLM 可选扩展（P2）**：S3 决策——保留自研适配器（已满足 P8），LiteLLM 作文档标注的可选统一后端；若引入必须锁版本（2026-03 PyPI 投毒事件）
2. **Provider 能力声明规范化（P2）**：`supported_models` 目前为静态列表，建议扩展为结构化能力声明（支持 tools/vision/embedding/stream），供 CompatibilityChecker 消费
