# Protocol 14.3 — Skill Interface 规范

> 设计稿依据：MyHarness v1.1 §5（Skill Store）、§6（Learning）、§14.3（Skill Interface）
> 代码实现：`src/myharness/schema/skill.py`、`skill/`（lifecycle/store/registry/validator/storage）
> 版本：v0.1（2026-08-02）· 状态：已实现 ✅（测试覆盖待补强至 ≥85%）

## 1. 目的

Skill 是**保存已学习完成的能力**——执行模板，没有思考能力。本规范定义 Skill 的标准描述格式（§5.1）、生命周期（§5.2）、存储原则（§5.3）与版本管理，作为 Learning（§6）产出与 Harness 调度的契约。

## 2. Skill 标准描述（§5.1 ↔ SkillDefinition）

| 设计稿字段 | 实现字段 | 说明 |
|---|---|---|
| Name | `name` | 全局唯一（如 `walk`、`grab`） |
| Version | `version` | SemVer（`storage.py::_sort_semver` 排序） |
| Input | `input_schema` | 驱动动作输入 schema（dict） |
| Output | `output_schema` | 输出 schema |
| Parameters | `parameters: list[SkillParameter]` | name/type/required/default/enum_values/validation |
| Boundary | `preconditions` / `postconditions` / `constraints` | 前置/后置/约束条件 |
| Capability | `capability` | 高层能力名（供 Capability Registry 发现） |
| Confidence | `confidence` | 可靠性估计 [0,1] |

**执行绑定**：`driver_type`（robot/browser/api/mcp/computer/database/iot）+ `action_template` + `allowed_actions`（动作白名单，防注入）。
**权限契约**：`SkillDefinition.permits_action(action)` → 白名单解析（`resolve_allowed_actions`：显式 allowlist > template 内 actions > template 单 action > skill.name 兜底）。空动作一律拒绝；`["*"]` 需显式授权。
**溯源**：`compiled_from`（产生该 Skill 的经历 ID）+ `parent_skill_id`（特化/变体链）。

## 3. 生命周期状态机（§5.2 ↔ SkillStatus）

```
DRAFT → TESTING → VERIFIED → STABLE → DEPRECATED → ARCHIVED（终态）
   ↑        ↕         ↕         ↑
   └────────┴─────────┴─────────┘（回退边：TESTING↔DRAFT、VERIFIED→TESTING、DEPRECATED→STABLE、DRAFT→ARCHIVED）
```

- 状态迁移校验：`schema/skill.py::SKILL_LIFECYCLE_TRANSITIONS`（模型层）+ `skill/lifecycle.py::SkillLifecycle`（服务层，双保险）
- 每次迁移记录 `SkillLifecycleTransition`（from/to/reason/timestamp/triggered_by）入 `lifecycle_history`（审计）
- **版本管理职责归属 Harness 层**（设计稿 §5.2）：`skill/storage.py` 按 `name/version` 组织目录，支持多版本共存与列表

## 4. Skill 文件存储（§5.3）

```
skills/
├── walk/          # 按名称目录
│   ├── 0.1.0.skill  # 版本文件（原始数据，JSON 序列化）
│   └── 0.2.0.skill
└── grab/...
```

- Skill 定义为**原始数据**（source_of_truth 标记），编译缓存/运行时优化产物为衍生数据（P9）
- `SkillStore`（接口）→ `SkillStorage`（磁盘）→ `SkillRegistry`（匹配）→ `SkillValidator`（校验）四层分离

## 5. Learning 工作流契约（§6）

```
Experience → Reflection → Trial → Parameter Tuning → Validation → Skill Update
```

- Learning **不是独立 Agent**，归属 LLM Engine 能力范畴（`llm/engine.py::reflect/compile`）
- LLM 产出 `SkillProposal`（建议名/描述/schema/driver_type/action_template/allowed_actions/compiled_from/reasoning/confidence_estimate）→ 经 `SkillValidator.validate_proposal` → 创建 DRAFT 技能
- 运行时遵循 P6：**优先调用已有 Skill**，仅缺失/冲突/失效时启用 LLM 深度推理

## 6. 待落地缺口

1. **测试覆盖不足（P1）**：validator 60% / store 67% / registry 62%——S4 补强至 ≥85%
2. 参照开源模式（S2 调研）：Nacos Skill Registry 状态机、SkillHub SemVer 不可变版本+标签回滚——当前实现已覆盖核心，回滚标签机制列为 P2
