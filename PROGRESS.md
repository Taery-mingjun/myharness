# MyHarness 项目进度追踪（PROGRESS）

> 更新规则：每阶段完成或重要决策时更新本文件，并提交推送 gitee（commit 信息含阶段号）。
> 记录格式：`[日期] 阶段号 — 事项 — 依据（设计稿章节）— 结论`

## 当前阶段：S0–S5 完成 ✅ / S6 查缺补漏 ✅（2026-08-02）

| 阶段 | 状态 | 完成日期 | 备注 |
|---|---|---|---|
| S0 基线 | ✅ | 2026-08-02 | 权限免审批、计划书、规范、追踪机制、CLAUDE.md |
| S1 现有代码审查 | ✅ | 2026-08-02 | 282 测试全过、67% 覆盖；报告 docs/REVIEW_REPORT.md |
| S2 开源轮子调研 | ✅ | 2026-08-02 | 14 次 WebSearch 核实，产出 docs/OPENSOURCE_SURVEY.md |
| S3 差距决策 | ✅ | 2026-08-02 | 无需重建 + 选型定稿，路线图更新于 PROJECT_PLAN.md §4 |
| S4 按 v1.1 实施 | ✅ | 2026-08-02 | 协议文档×5、Event 强类型化、MCP 驱动、skill 测试补强 |
| S5 验证发布 | ✅ | 2026-08-02 | 349 测试全过、覆盖 70%；**v0.2.0 已发布**（tag 推送 gitee） |

## 决策记录

- **2026-08-02 S0** — 用户确认项目定位：MyHarness 认知操作系统底层架构，最终目标完全达到 v1.1 设计稿；核心理念"技能归技能、算力归算力、记忆归记忆"；优先采用成熟开源技术防重复造轮子；不混入桌面其他项目（JARVIS_CONSOLE 等）
- **2026-08-02 S0** — 权限模式改为 `bypassPermissions`（用户要求免审批）
- **2026-08-02 S0** — git 历史：`373c4b3`（初始）→ `a18e03b`（CLAUDE.md）；工作区遗留 2 个未提交修改（memory/storage/source.py、tests/integration/test_runtime_loop.py，旧会话产物，S1 审查时一并评估）
- **2026-08-02 S1** — 结论：**无需重建**。现有代码与 v1.1 设计稿逐章对应，282 测试全通过、覆盖 67%。已提交遗留修改（`309d9d2`，Windows 并发写入/CPU 计时修复，评估为高质量保留）
- **2026-08-02 S1** — 发现 P0 缺口 3 项：① Event Schema 缺 priority 字段、载荷未强类型化（设计稿 14.1）；② 五个协议规范文档缺失（docs/protocol/，设计稿 14.x 核心交付物）。P1 缺口：skill 模块测试覆盖不足（60–72%）。详见 docs/REVIEW_REPORT.md
- **2026-08-02 S2** — 开源调研定稿（docs/OPENSOURCE_SURVEY.md）：直接采用 4 件（LiteLLM 可选、MCP SDK、faiss-cpu 保持、技能注册表模式参照），必须自研 5 件（记忆层、Event Bus、Skill Store、Harness、Provider 协议）；OpenClaw 缺陷验证用户直觉（技能=提示词、记忆弱、单线程）
- **2026-08-02 S3** — 差距决策：**无需重建**；MCP 驱动现为 stub，S4 采用官方 SDK 实现；LiteLLM 因 PyPI 投毒事件只作可选扩展；Event Schema 协议文档优先于代码改动。路线图定稿见 PROJECT_PLAN.md §4
- **2026-08-02 S4** — 四项全部落地并推送：① 协议文档五份（docs/protocol/01–05，`da41959`）② Event Schema 规范化（priority 字段 + 27 种事件强类型载荷，向后兼容，`8277104`）③ MCP 驱动真实实现（官方 SDK 2.0，stdio + HTTP 传输，10 个集成测试，`c882245`）④ skill 测试补强至 98–100%（`19545bd`）。全量 349 测试通过、覆盖 70%
- **2026-08-02 S5** — v0.2.0 发布（tag 推送 gitee），349 测试全过
- **2026-08-02 用户改动** — gitee 新增 4 提交（`19ce21f` 发布清理 / `e4ffe33` 修复×4 / `f3210b5` 降级+self-healing+sandbox / `08ea338` Reflex 层），379 测试通过；GitHub 双仓同步
- **2026-08-02 S6 查缺补漏** — 审查修复 3 个 P0 + 3 个 P1：① `rollback_to_stable()` 缺失（自愈确认不可用）→ 实现版本指针机制；② Reflex/自愈未接入运行时（死代码）→ DI 装配 + boot rebuild + 指标采集；③ Reflex 命中不执行 skill → 接入 driver 执行 + 失败降级；④ 跨类私有访问 → 公共 API；⑤ CJK 关键词 bigram 提取；⑥ current_version 占位符。新增 12 测试，全量 391 通过、覆盖 71%。详见 docs/REVIEW_REPORT_2.md
