# Protocol 14.2 — Memory API 规范

> 设计稿依据：MyHarness v1.1 §4（Memory System）、§14.2（Memory API）
> 代码实现：`src/myharness/memory/interface.py`（抽象）、`memory/manager.py`（实现）、`memory/storage/`、`memory/stores/`、`memory/indexing/`
> 版本：v0.1（2026-08-02）· 状态：已实现 ✅

## 1. 目的

Memory 是**数据库，不是 Prompt，不是 Context**。本规范定义四类子存储的数据模型、读写检索接口、原始/衍生数据隔离（P9）与 Identity 外置流程（P3）。本模块是路线图 14.6 指定的**最高优先级模块**（已有实测经验）。

## 2. 四类子存储（设计稿 §4）

| 存储 | 数据模型 | 代码 | 持久性 |
|---|---|---|---|
| Identity Memory | Core Values / Mission / Preferences / Self Description / Behavioral Guidelines | `IdentityEntry`（schema/memory.py） | 原始数据，必须持久化 |
| Episodic Memory | Events / Experiences / Conversations（append-only 不可变） | `EpisodicEntry`（含 importance、tags、participants） | 原始数据 |
| Semantic Memory | 知识三元组（entity / attribute / value + confidence） | `SemanticEntry` | 原始数据 |
| Relationship Memory | 有向关系（entity_a → entity_b，relation_type + strength） | `RelationshipEntry` | 原始数据 |

## 3. 接口规范

设计稿的泛化接口 Read/Write/Search/Archive 在实现中按存储细化。映射关系：

| 设计稿接口 | 实现方法（MemorySystem 抽象，全部 async） |
|---|---|
| Read | `get_identity()` / `get_episode(id)` / `get_related_knowledge()` / `get_relationship(a,b)` / `get_recent_episodes(n)` |
| Write | `update_identity()` / `record_episode()` / `store_knowledge()` / `set_relationship()` |
| Search | `search_episodes()` / `search_knowledge()` / `search()`（跨存储混合检索）/ `get_all_relationships_for()` |
| Archive | `archive_old_episodes(before_timestamp)`（当前为查询层软归档统计，硬归档待定） |
| — | `apply_identity_proposal()`（P3 专属）/ `rebuild_indexes()`（P9 专属）/ `get_stats()` |

### 3.1 跨存储检索（MemoryQuery）

| 字段 | 类型 | 默认 | 说明 |
|---|---|---|---|
| query_text | str | "" | 自然语言查询 |
| query_embedding | Embedding \| None | None | 预计算向量（跳过嵌入生成） |
| categories | list[MemoryCategory] | 全部 | 限定检索的存储 |
| tags / time_range | list / tuple | — | 过滤条件 |
| top_k | int | 10 | 返回上限 [1,100] |
| min_importance | float | 0.0 | 情节记忆最低重要度 |
| hybrid_weight | float | 0.7 | 向量 vs 关键词权重 [0=纯关键词, 1=纯向量] |

## 4. 原始/衍生数据分离规范（P9，设计稿 §4.3）

| 类型 | 载体 | 要求 |
|---|---|---|
| 原始数据（Source of Truth） | `data/*/identity.json`、`episodic/*.jsonl`、`semantic/*.json`、`relationship/*.json` | **必须持久化、不可篡改**；JSONL 追加写受 `threading.Lock` 保护（Windows O_APPEND 非原子），`os.replace` 带重试 |
| 衍生数据（Derived/Rebuildable） | SQLite（DerivedStorage）、FTS5 全文索引（TextIndex）、FAISS 向量索引（VectorIndex） | **可删除、可重建**，不承担持久性保证 |

**重建契约**：任何衍生数据可经 `MemoryManager.rebuild_indexes()` 从 SourceOfTruth 全量重建（顺序：SQLite → FTS5 → FAISS）。此契约保证"删除衍生数据 = 零损失"。

## 5. Identity 外置流程（P3，设计稿 §3.1/§4）

```
LLM interpret_identity() ──读──> Identity Memory（归属 Memory，LLM 不拥有）
LLM propose_identity_update() ──写提案──> apply_identity_proposal()（版本冲突校验）
```

- LLM 只持有**读取解释**与**更新提议**两类接口，不直接持久化身份
- `IdentityEntry.version` 单调递增，更新时校验冲突（`IdentityConflictError`）
- 切换 LLM Provider（P8）时 Identity 完全保留

## 6. 嵌入与降级

- Memory 层通过窄接口 `Embedder`（`memory/embedder.py`）生成嵌入，**不依赖 LLM 系统**（保持四权分离）
- 嵌入不可用时自动降级：写入仍落库（可被全文检索命中），查询退化为关键词匹配——不静默丢数据

## 7. 待落地缺口

1. **协议文档对应的物理隔离检查**：衍生 SQLite/FTS5/FAISS 文件须与原始 JSON/JSONL 分目录存放（当前 `data/` 下已有分离，S4 验证测试覆盖）
2. **Archive 硬归档**：当前 `archive_old_episodes()` 仅统计可归档数（查询层软过滤）；设计稿要求真正的归档语义——S4 后期按需实现物理归档 + 衍生索引剔除
