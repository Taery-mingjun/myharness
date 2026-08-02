# S6 查缺补漏审查报告（用户新增改动审查）

> 日期：2026-08-02 · 审查范围：`19ce21f`→`08ea338` 四个新提交（发布清理 / 修复×4 / self-healing+sandbox / Reflex 层）
> 基线：合并后 379 测试通过、覆盖 70% → 审查修复后 **391 通过、覆盖 71%**

## 1. 用户新增改动概述（质量评价）

| 提交 | 内容 | 评价 |
|---|---|---|
| `19ce21f` | 发布清理：LICENSE、ruff 配置修正、F821 修复、删 code_dump、模型默认更新 | ✅ 高质量，公开发布前的必要清理 |
| `e4ffe33` | identity name 字段、switch_provider、supervisor auto-boot、openai_compatible 注册 | ✅ 4 个真实 bug 修复，方向正确 |
| `f3210b5` | plan/reflect 优雅降级 + self-healing 阶段 1 + sandbox | ✅ 降级逻辑正确；healing 有设计缺陷（见 §2） |
| `08ea338` | Reflex 层（§6.5）+ 16 测试 | ⚠️ 实现良好但**未接入运行时**（见 §2-A/B） |

## 2. 发现的问题与修复

### P0（功能断裂）

- **A. `rollback_to_stable()` 不存在**（healing.py 调用 → 必然失败）
  - 现象：`RollbackManager.confirm_rollback()` 调用 `skill_store.rollback_to_stable()`，但 SkillStore/SkillStorage 均无此方法，confirm 永远走 except 返回 error——**自愈确认机制实际不可用**。
  - 修复：SkillStorage 增加 `current.json` 当前版本指针（`save_current`/`load_current`，指针为衍生数据符合 P9）；SkillStore 实现 `rollback_to_stable(name, target_version)`（显式版本或最新 STABLE）；`register()` 后指针自动指向新版本；`get_by_name()` 无版本时优先读指针；接口层同步声明。

- **B. Reflex/自愈系统未接入运行时（死代码）**
  - 现象：`ReflexIndex`、`DriftDetector` 在 src/ 生产代码中**零实例化点**；`record_skill_execution` 等指标采集无任何调用者；supervisor 的 `reflex_index` 参数默认 None——系统实际运行时这些功能完全不生效。
  - 修复：DI 容器装配 `DriftDetector`（`data/healing/drift.db`）+ `ReflexIndex`（skill_store + drift_detector）；supervisor 构造接收两者；boot 时自动 `rebuild()`（P9 衍生数据）；`_execute_plan` 与 reflex 执行后均 `record_skill_execution`。新增 3 个配置项（healing_failure_threshold / healing_window_size / reflex_success_threshold）。

- **C. Reflex 命中后不执行 skill，只返回字符串**
  - 现象：supervisor 的 reflex 分支提取参数后直接 `return "[reflex:xxx] Executed with params"`——**skill 从未真正执行**，违反 §6.5 "skill is executed directly"。
  - 修复：经 `driver_manager.execute(driver_type, action_template.action, params)` 真实执行；执行成功返回结果；**失败则降级到完整认知流程**（reflex 是优化，不是失败点）；记录执行结果 episode + drift 指标。

### P1（设计缺陷）

- **D. 跨类私有访问**：reflex.py 直接 `self._drift_detector._get_conn()` 手写 SQL。修复：`DriftDetector.get_consecutive_successes()` 公共 API，reflex 改调。
- **E. 中文关键词提取缺陷**：CJK 文本无空格，原 `split()` 会把整个描述变一个关键词（如"打开冰箱取出食物"整段），实际不可匹配。修复：CJK 连续片段按 2 字 bigram 提取（限 16 个），"打开冰箱" → ["打开","开冰","冰箱"]。
- **F. `current_version` 硬编码 "current"**：回滚候选记录的当前版本是占位符。修复：`_generate_rollback_candidate` 接受真实版本；`confirm_rollback` 时占位则从 SkillStore 解析真实版本。

### P2（遗留，未修）

- G. `EXPIRED` 状态定义了但无过期迁移逻辑
- H. `drift_metrics` 表无清理策略（长期运行会膨胀）
- I. Reflex 慢路径（regex）当前恒空，为扩展预留

## 3. 修复验证

- 新增 12 个测试（`tests/integration/test_reflex_supervisor.py`）：rollback 5 项（显式/最新 STABLE/无目标/缺失目标/指针持久化）、CJK 提取 3 项、supervisor reflex 执行路径 3 项（成功执行、失败降级、无索引跳过）、DI 装配 1 项
- 全量 **391 通过**（379 + 12），覆盖 70% → 71%

## 4. 结论

用户新增的四个提交整体质量良好（发布清理、bug 修复、降级逻辑都到位），主要问题集中在**新功能（Reflex/自愈）未接通运行时链路**——修复后 Reflex Layer 与 self-healing 从"测试覆盖的模块"变为"系统实际运行的能力"，且补齐了自愈确认机制缺失的底层方法。剩余 P2 项建议纳入下一迭代。
