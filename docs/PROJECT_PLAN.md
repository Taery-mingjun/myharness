# MyHarness 工程落地计划书

> 版本：v0.1（2026-08-02）· 依据：桌面 `myharness1.1(1).pdf` 设计稿 · 追踪：本仓库 `PROGRESS.md`

## 1. 项目目标

构建一个**完全达到 MyHarness v1.1 设计稿要求**的 agent 系统底层架构：

- **认知操作系统**：LLM（算力）只负责思考；技能归技能、算力归算力、记忆归记忆——四权（Compute / Memory / Skill / Execution）严格分离
- **可插拔算力**：LLM Provider 可替换（Think/Plan/Reflect/Compile 统一接口），切换引擎不丢 Identity/Memory/Skill
- **协议优先**：定义 Protocol v0.1 五个接口规范（Event Schema / Memory API / Skill Interface / Execution Driver / LLM Provider）
- **形态**：底层架构（Python 包 + FastAPI 服务 + 协议文档），非终端产品

## 2. 总原则（用户意图的工程化）

1. **不重复造轮子**：优先采用成熟开源组件（MCP、向量库、事件总线、LLM SDK 等）**适配进**本架构，仅对 MyHarness 特有部分（四权分离、Identity 外置、Skill 生命周期）自研
2. **完全免审批**：权限已配置为 `bypassPermissions`，自动化执行
3. **gitee 全量追踪**：所有阶段性进展写入 `PROGRESS.md` 并提交推送 gitee
4. **多 agent 防冲突**：见 §6 统筹规则——模块所有权 + 分支隔离，严禁两个 agent 同时改同一模块
5. **设计稿为准**：一切实现决策以 v1.1 设计稿为唯一依据；冲突时先记录到 PROGRESS.md 再定夺

## 3. 实施阶段

| 阶段 | 内容 | 产出 | 状态 |
|---|---|---|---|
| **S0 基线** | 权限配置、计划书、规范、PROGRESS 追踪机制、CLAUDE.md 更新 | 本文件 + PROGRESS.md | ✅ 进行中 |
| **S1 现有代码审查** | 逐模块审计 src/myharness 与设计稿的符合度、完善程度、代码质量 | `docs/REVIEW_REPORT.md`（差距报告） | ⬜ |
| **S2 开源轮子调研** | 调研认知架构/记忆系统/事件总线/驱动层成熟实现，评估替代与复用 | `docs/OPENSOURCE_SURVEY.md`（选型建议） | ⬜ |
| **S3 差距决策** | S1+S2 汇合：确定修补 vs 重建、技术栈替换清单 | 更新后的路线图（写回 §4） | ⬜ |
| **S4 按 v1.1 实施** | 依路线图顺序实施：① Memory API（含 Identity，设计稿 14.2 优先）→ ② Event Schema → ③ LLM Provider 接口 → ④ Skill Interface → ⑤ Execution Driver | 代码 + 协议文档 | ⬜ |
| **S5 验证发布** | 全量测试（pytest）、文档完善、版本标记、gitee 发布 | 通过 CI + v0.2.0 发布 | ⬜ |

## 4. 路线图（S3 后更新）

- 暂定优先级（设计稿 14.6 建议）：**Memory API（含 Identity 子系统）优先**——已有实测经验（衍生数据分离、索引重建可行性已验证）
- Skill Interface / Execution Driver 待接入真实执行设备后再具体化

## 5. 工程规范标准

1. **代码**：ruff（E/F/I/N/W/UP/B/SIM/C4）+ mypy strict，Python ≥3.11，已配置于 pyproject.toml
2. **提交规范**：Conventional Commits（`feat:` / `fix:` / `docs:` / `refactor:` / `test:`），信息含模块路径
3. **测试**：pytest + pytest-asyncio，新增功能必须带测试；`tests/unit`（单测）+ `tests/integration`（集成）
4. **文档**：协议规范放 `docs/protocol/`（每协议一文档，对应设计稿 14.1–14.5）
5. **追踪**：每个阶段完成 → 更新 PROGRESS.md → 提交推送 gitee（commit 信息含阶段号，如 `feat(S1): ...`）

## 6. 多 agent 统筹规则（防冲突）

### 6.1 模块所有权矩阵

| 模块（目录） | 对应设计稿 | 说明 |
|---|---|---|
| `src/myharness/memory/` | Layer 2 Memory System | 最高优先级，Identity 子系统重点 |
| `src/myharness/llm/` | Layer 1 LLM Engine / 14.5 | 仅 Think/Plan/Reflect/Compile 接口 |
| `src/myharness/skill/` | Layer 3 Skill Store / 14.3 | Skill 生命周期与版本 |
| `src/myharness/harness/` | Harness Layer | 核心枢纽，跨模块改动需协调 |
| `src/myharness/bus/` | Event Bus / 14.1 | Event Schema 规范化 |
| `src/myharness/driver/` | Execution Layer / 14.4 | 适配器模式 |
| `src/myharness/api/` | 对外 API | FastAPI 路由 |
| `src/myharness/core/` | 基础 | 配置/DI/日志，改动影响全系统 |
| `tests/` | — | 与所测模块绑定 |

### 6.2 工作规则

1. **一次一个 agent 一个模块**：任何 agent（含子代理）开工前先查 PROGRESS.md 与 git 分支，目标模块被占用则等待或改派
2. **分支隔离**：每个阶段任务开独立分支（`feat/S1-review`、`feat/S4-memory-api`…），完成合并回 main；工作区不得堆积跨任务修改
3. **共享状态唯一入口**：CLAUDE.md（项目记忆）+ PROGRESS.md（进度）+ git（代码），三处之外不产生新事实
4. **改动登记**：合并前必须在 PROGRESS.md 登记"谁、何时、改了哪个模块、依据设计稿哪一节"
5. **harness 与 core 需用户知悉**：改动核心枢纽层前先向用户说明影响面

## 7. 参考

- 设计稿：`C:\Users\10444\Desktop\myharness1.1(1).pdf`（v1.1，2026-08-02）
- 旧会话遗留：`~/.claude/plans/myharness-bubbly-cloud.md`（B2/B3/B4 安全项，未与 v1.1 对齐，暂缓，S3 决策时一并评估）
