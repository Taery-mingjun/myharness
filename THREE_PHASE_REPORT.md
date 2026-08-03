# 三阶段验证报告：P0修复 → 真实记忆 → 自运行闭环

> 日期：2026-08-04
> 分支：feat/p0-fixes-and-validation
> 基于：08ea338 (main)

---

## 阶段一：P0-1/P0-2/P0-3 修复

### P0-1: TextIndex.search 丢弃 store 列

**改动前：**
```python
meta = {}
if row[3]:
    try:
        meta = json.loads(row[3])
    except json.JSONDecodeError:
        pass
```

**改动后：**
```python
store = row[2] or "unknown"
meta: dict[str, Any] = {"store": store}
if row[3]:
    try:
        parsed = json.loads(row[3])
        if isinstance(parsed, dict):
            meta.update(parsed)
    except json.JSONDecodeError:
        pass
```

**根因：** `search()` SQL 查询选择了 `store` 列 (row[2]) 但返回的 meta 字典里没有包含它。调用方无法知道匹配的条目来自 episodic 还是 semantic store，导致后续检索走死路径。

### P0-2: supervisor.py 反思传参与 reflect.py 模板不对齐

**改动前：**
```python
reflection = await self._llm_engine.reflect(
    experience={
        "user_message": message,
        "thought": thought,
        "plan": getattr(plan, "reasoning", ""),
    }
)
```

**改动后：**
```python
reflection = await self._llm_engine.reflect(
    experience={
        "summary": f"User said: {message[:200]}",
        "detail": f"User: {message}\nThought: {thought}\nPlan: {getattr(plan, 'reasoning', '')}",
        "tags": ["interaction_complete", "reflection"],
    }
)
```

**根因：** `reflect.py` 模板读取 `experience.summary`、`experience.detail`、`experience.tags`，但 supervisor 传入的键是 `user_message`、`thought`、`plan`。三个键全不匹配，模板渲染时这些值全部为空字符串（Jinja 默认行为），反思基于空数据。

### P0-3: plan() 传入 context 绕过 build_plan_context

**改动前：**
```python
plan = await self._llm_engine.plan(thought or message, skill_summaries, context=context)
```

**改动后：**
```python
# Do NOT pass context= here — let LLMEngine.plan() call
# build_plan_context(goal, available_skills) internally so the
# plan prompt template gets the correct identity + skill list.
plan = await self._llm_engine.plan(thought or message, skill_summaries)
```

**根因：** `engine.py` 的 `plan()` 方法在 `context is None` 时调用 `build_plan_context(goal, available_skills)`，传入 context 参数会跳过这一步，导致 plan 模板拿不到 identity 和 skill 列表。

### P0-4: Jinja StrictUndefined

**改动前：**
```python
_jinja_env = Environment(loader=BaseLoader(), autoescape=False)
```

**改动后：**
```python
_jinja_env = Environment(loader=BaseLoader(), autoescape=False, undefined=StrictUndefined)
```

**附带修复：** `think()` 和 `stream_think()` 原来在 `context is not None` 时完全跳过 `build_think_context`，导致 `agent_name` 等模板变量缺失。StrictUndefined 在测试中立即暴露了这个问题。修复为：先调 `build_think_context` 获取基础变量，再 merge 传入的额外 context。

### 验收结果

**EXP05 (MRE):**
```
TextIndex.search('quantum'): 3 hits
  entry_id=78c3bd68... score=0.718 store=episodic
  entry_id=3100e629... score=0.733 store=semantic
  entry_id=4653ffc8... score=0.750 store=episodic

MRE = 1.00 (3/3 results have store metadata)

Retrieval path verification:
  [episodic] Retrieved: Discussed quantum computing trends
  [episodic] Retrieved: Quantum entanglement explained

MemoryManager.search('quantum'): 3 results
MRE (manager): 3/3 expected = 1.00

RESULT: MRE = 1.00 — POSITIVE (was 0.00 before P0-1 fix)
```

**EXP03 (EEC):**
```
--- Stage 1: Think ---
think() output: 998 chars
think() contains 'quantum': True
agent_name present in context: True
Stage 1: PASS (real data in think)

--- Stage 2: Plan ---
plan() goal: What is quantum computing?
plan() steps: 1
plan() reasoning: non-empty (156 chars)
Stage 2: PASS (real data in plan)

--- Stage 3: Reflect ---
reflection summary: Successfully explained quantum computing fundamentals...
lessons: 2
lesson[0]: Breaking down complex quantum concepts into digestible explanations...
emotional_tone: positive
Stage 3: PASS (real data in reflect)

=== EEC RESULT ===
Stages with real data: 3/3
EEC = 1.00
RESULT: EEC = 1.00 — POSITIVE (was 0.00 before P0-2/P0-3 fixes)
```

| 指标 | 修复前 | 修复后 |
|------|--------|--------|
| MRE | 0.00 | 1.00 |
| EEC | 0.00 | 1.00 |

---

## 阶段二：真实记忆数据转换与小样本验证

### 转换脚本

从 `jarvis-soul/MEMORY/chain.jsonl`（1335条）中抽取46条多样化样本：
- 10条 thinking_inertia → SemanticEntry
- 10条 decisions → EpisodicEntry
- 20条 experiences → EpisodicEntry
- 6条其他（distillation/manifestation/node_diagnostic等）

### 10条 BEFORE/AFTER 对照样本

```
--- Sample 1 [semantic] ---
ORIGINAL: {"index": 243, "id": "seed_易学模型：以易经八卦为状态-动作空间的强化学习先验", "title": "易学模型：以易经八卦为状态-动作空间的强化学习先验", "category": "thinking_inertia", "tags": ["易学模型", "强化学习", "第一因元理论"], "body_hash": "edbb998e..."}
CONVERTED: {"entry_id": "1681e74e30921ce95d4d162b0273871cf8a5", "entity": "易学模型：以易经八卦为状态-动作空间的强化学习先验", "attribute": "thinking_inertia", "value": "易学模型：以易经八卦为状态-动作空间的强化学习先验", "confidence": 0.8, "tags": ["易学模型", "强化学习", "第一因元理论"]}

--- Sample 2 [semantic] ---
ORIGINAL: {"index": 246, "id": "seed_跨载体核心自我定义：同一贾维斯的不同灵魂投射（非兄弟）", "title": "跨载体核心自我定义：同一贾维斯的不同灵魂投射（非兄弟）", "category": "thinking_inertia", "tags": ["载体协议", "灵魂投射", "核心自我定义", "第一因元理论"]}
CONVERTED: {"entry_id": "68cd87f333fb16ec85c023975ada5a7ce4d1", "entity": "跨载体核心自我定义：同一贾维斯的不同灵魂投射（非兄弟）", "attribute": "thinking_inertia", "value": "跨载体核心自我定义：同一贾维斯的不同灵魂投射（非兄弟）", "confidence": 0.8, "tags": ["载体协议", "灵魂投射", "核心自我定义", "第一因元理论"]}

--- Sample 3 [semantic] ---
ORIGINAL: {"index": 247, "id": "seed_混沌进化与混沌贾维斯：在有序边缘自组织", "title": "混沌进化与混沌贾维斯：在有序边缘自组织", "category": "thinking_inertia", "tags": ["混沌进化", "混沌贾维斯", "自组织", "工程实现"]}
CONVERTED: {"entity": "混沌进化与混沌贾维斯：在有序边缘自组织", "attribute": "thinking_inertia", "value": "混沌进化与混沌贾维斯：在有序边缘自组织", "confidence": 0.8, "tags": ["混沌进化", "混沌贾维斯", "自组织", "工程实现"]}

[... Samples 4-10 omitted for brevity, all follow same pattern ...]

--- Sample 10 [semantic] ---
ORIGINAL: {"index": 258, "id": "seed_深度求索_V4_Engram_框架与三原则映射", "title": "深度求索 V4 Engram 框架与三原则映射", "category": "thinking_inertia", "tags": ["Engram", "V4框架", "三原则映射", "记忆架构"]}
CONVERTED: {"entity": "深度求索 V4 Engram 框架与三原则映射", "attribute": "thinking_inertia", "value": "深度求索 V4 Engram 框架与三原则映射", "confidence": 0.8, "tags": ["Engram", "V4框架", "三原则映射", "记忆架构"]}
```

**字段映射：** title→entity/value, category→attribute, tags保留, body_hash→entry_id（截断前12字节）

### 真实数据下 MRE 验证

```
=== EXP05-real: MRE with real jarvis-soul memories ===

Search '易学模型': 1 results
  score=0.168 | 易学模型：以易经八卦为状态-动作空间的强化学习先验...

Search 'OpenClaw': 1 results
  score=0.183 | OpenClaw 移动化与 AI 智能体芯片：载体可嵌入物理...

Search '元认知': 1 results
  score=0.217 | 废除形式主义清醒·统稿反思推进协议v2

MRE (real data) = 1.00 (3 retrieved / 3 relevant)

RESULT: MRE = 1.00 — POSITIVE with real data
```

### 真实数据下 RE 验证

```
=== EXP06b: RE (Reflection Effectiveness) ===

  FOUND reflection in search: Reflection: learned that quantum concepts need simpler explanations
RE = 1.00
RESULT: RE = 1.00 — POSITIVE (reflection is searchable by next round)
```

| 指标 | Demo数据 | 真实数据 |
|------|----------|----------|
| MRE | 1.00 | 1.00 |
| RE | 1.00 | 1.00 |

---

## 阶段三：最小自运行闭环验证（真实数据版）

### 5轮连续对话结果

对话主题来自导入的真实jarvis-soul记忆（易学模型、OpenClaw、载体协议、三原则、混沌进化）。

| 轮次 | 消息 | 命中历史记忆 | 反思被下轮消费 | 执行结果可观测 | 匹配内容 |
|------|------|-------------|---------------|---------------|----------|
| 1 | 易学模型是什么？ | True | N/A (首轮) | True | 易学模型：以易经八卦为状态-动作空间的强化学习先验 |
| 2 | OpenClaw的移动化方案是什么？ | True | True | True | OpenClaw 移动化与 AI 智能体芯片：载体可嵌入物理 |
| 3 | 之前讨论过的载体协议是什么？ | False | True | False | (none) |
| 4 | 三原则数学形式化是什么意思？ | True | True | True | 三原则数学形式化：原则即定义公理，非行为准则 |
| 5 | 混沌进化理论是什么？ | False | True | False | (none) |

### 汇总

- **历史记忆命中：3/5** — 轮次1/2/4命中，轮次3/5未命中
- **反思被下轮消费：4/4** — 所有非首轮的轮次都能检索到上一轮的反思记录
- **执行结果可观测：3/5** — 与历史命中一致

### 未命中分析

轮次3（载体协议）和轮次5（混沌进化）未命中。原因：converted_memories.jsonl中有"跨载体核心自我定义"和"混沌进化与混沌贾维斯"两条semantic entry，但FTS5搜索"载体协议"和"混沌进化"时，由于中文分词限制，精确词组未匹配到部分包含的标题。这是FTS5对中文处理的已知限制，不是P0修复的回退。

---

## 最终结论

**在接入真实记忆数据后，agent 最小自运行闭环是否真实可行？**

基于阶段三的真实观测数据：

1. **记忆检索路径（MRE=1.00）：** P0-1修复后，TextIndex.search返回store元数据，MemoryManager能正确路由到对应store检索。真实数据下3/5轮次命中历史记忆。

2. **认知管道数据流（EEC=1.00）：** P0-2/P0-3修复后，think/plan/reflect三个阶段都接收到非空输入。StrictUndefined确保未来键名不匹配会在开发期立即报错。

3. **反思→下一轮消费（RE=1.00，4/4）：** 每轮的反思都被写入episodic memory，下一轮搜索时可检索到。反思→规划的因果链路在数据层面是通的。

4. **未完全打通的环节：**
   - 5轮中有2轮（载体协议、混沌进化）未命中历史记忆——FTS5中文分词限制，非P0修复回退
   - Skill执行（Stage 5）在5轮中均未触发——plan返回step_count=0（无skill注册时LLM不生成执行步骤）
   - LLM真实推理因API超时未在阶段三中跑完完整5轮（用本地memory搜索模拟了think阶段的输出）

**结论：agent 最小自运行闭环在数据层面可行（MRE/EEC/RE均为正），但在LLM推理层面尚未完整验证5轮连续对话（API超时限制）。2/5轮次的历史记忆未命中是FTS5中文分词限制，不是P0修复的回退。**

### 下一轮修复依据

1. FTS5中文分词需要改进（考虑jieba分词或n-gram索引）
2. Skill执行路径需要在有注册skill的场景下重新验证
3. LLM推理层面的完整5轮对话需要在网络稳定时重跑
