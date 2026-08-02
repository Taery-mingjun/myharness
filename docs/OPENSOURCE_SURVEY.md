# MyHarness 开源替代方案调研报告（S2 阶段）

> 目的：为 MyHarness 认知操作系统的四权分离架构（Compute / Memory / Skill / Execution + Harness + Event Bus）调研开源替代方案，防止重复造轮子。
> 对齐设计稿 v1.1（2026-08-02）与工程原则 P0–P9。
> 调研方法：WebSearch 在线检索验证（2026-08-02），所有项目名称、GitHub 链接、许可证、成熟度均来自检索结果，未凭记忆编造。详见文末。

---

## 1. 记忆系统（Memory as Database）

**MyHarness 需求对照**：记忆是数据库而非 Prompt（P0）；四类子存储 Identity / Episodic / Semantic / Relationship；接口 Read / Write / Search / Archive；原始/衍生数据分离（P9）；身份外置（P3，LLM 仅持 Interpretation / Update Proposal 接口）。
**先行的结论**：**没有任何开源项目完整实现"四类子存储 + Read/Write/Search/Archive + 原始/衍生分离"的组合**。Identity 子存储在开源界无对应物。但分层记忆、图记忆、抽取流水线的成熟实现都可拆解参考。

### 1.1 Letta（原 MemGPT）
- **GitHub**：https://github.com/letta-ai/letta
- **许可证**：Apache 2.0
- **成熟度**：生产级。源自 UC Berkeley Sky Computing Lab，~21–23K stars，Letta Inc. 商业支撑；REST API（239 个 endpoint）、Agent Development Environment（ADE 可视化检查 context/memory blocks）、Python/TS SDK。
- **核心能力**：三层记忆——Core Memory（常驻上下文的小块，存放 persona / 用户事实，agent 经 `core_memory_replace` 等工具自编辑）、Recall（会话历史日志检索）、Archival（无限分页向量存储）。上下文将溢出时由 agent 自行决定压缩/归档。
- **与设计稿契合点**：Core Memory 的 persona/human block ≈ Identity 雏形；Recall ≈ Episodic；Archival ≈ Semantic。记忆块 API 与 Read/Write/Search/Archive 同构。
- **建议**：**参考**。分层思想与"记忆以工具接口暴露"值得借鉴；但记忆质量依赖 LLM 自决（每次记忆操作消耗推理 token、模型漏存即丢失），与"LLM 不保存记忆、检索由 Harness 协议触发"的设计相悖，勿整体复用其 agent 框架。

### 1.2 Mem0
- **GitHub**：https://github.com/mem0ai/mem0
- **许可证**：Apache 2.0
- **成熟度**：社区最大（~48K stars），框架无关（LangChain/CrewAI/LlamaIndex/MCP server 集成），活跃。
- **核心能力**：被动抽取式语义事实记忆（ADD-only 流水线，原子事实带时间戳）；user/session/agent 三级作用域；混合 vector+graph+KV 存储；图记忆（Mem0ᵍ）被企业版付费墙隔离；无时间有效性窗口（事实不被取代/超期）。
- **与设计稿契合点**：抽取流水线可借鉴为"经验→衍生语义记忆"的写入路径；但无身份层、无原生关系建模（图能力付费）、时间推理弱。
- **建议**：**参考**（抽取/去重/过期策略），不直接复用——事实记忆只是四类子存储之一，且云服务化倾向与本地优先不符。

### 1.3 Zep / Graphiti
- **GitHub**：Zep https://github.com/getzep/zep ；核心引擎 Graphiti https://github.com/getzep/graphiti
- **许可证**：Graphiti Apache 2.0；Zep 托管平台为商业专有
- **成熟度**：Graphiti pre-1.0（Thoughtworks Technology Radar 2026-04 进入 Trial，建议锁版本）；Zep 托管版生产级（SOC 2、企业客户）。
- **核心能力**：双时间（bi-temporal）知识图谱，三层子图——Episode 子图（原始输入非损存储，是全部衍生事实的 provenance）、Semantic Entity 子图（LLM 抽取实体/事实边）、Community 子图（强连通簇摘要）；边携带 `valid_at`/`invalid_at` 有效性窗口，矛盾时旧边**失效而非删除**；混合检索（embedding + BM25 + 图遍历，查询时零 LLM 调用，P95 ~300ms）；需自备图数据库（Neo4j / FalkorDB / Neptune）；提供一等公民 MCP server。
- **与设计稿契合点**：**与 MyHarness 映射度最高**——Episode ≈ Episodic（原始），Entity/Fact ≈ Semantic + Relationship（衍生），边失效归档 ≈ Archive 语义；"episode 为 ground truth、其上叠加衍生子图"与 P9 原始/衍生分离同构；"矛盾时失效不删除"正是 Archive 而非 Delete 的哲学。
- **建议**：**深度参考 / 有条件复用**。若接受引入 Neo4j，Relationship + Episodic 子存储可直接建于 Graphiti；若坚持 aiosqlite 轻栈，则用 aiosqlite + networkx（项目已在栈）复刻其设计模式。代价：每次写入有 LLM 抽取成本；pre-1.0 需锁版本。

### 1.4 LangMem
- **GitHub**：https://github.com/langchain-ai/langmem
- **许可证**：MIT
- **成熟度**：活跃开发（LangChain 生态），无独立商业托管。
- **核心能力**：Episodic / Semantic / **Procedural** 三类记忆；命名空间隔离（user_id/team_id/app_id）；会话后后台抽取进程；存储后端可插拔（MongoDB、Postgres+pgvector 等）；Procedural 记忆允许 agent 改写自身系统提示（生态内罕见特性）。
- **与设计稿契合点**：分层 + 命名空间思想一致；Procedural（经验改写指令）与 P5 能力沉淀（经验→Skill 更新）同源。但无图/关系记忆、无时间推理，且深度绑定 LangGraph（"离开 LangGraph 价值大减"）。
- **建议**：**参考**（Procedural 机制值得用于 Skill 沉淀设计），整体不采用——引入 LangGraph 依赖链与 P7 协议优先冲突。

### 1.5 Chroma
- **GitHub**：https://github.com/chroma-core/chroma
- **许可证**：Apache 2.0
- **成熟度**：RAG 原型最流行（LangChain/LlamaIndex 默认集成），但生产级存疑：单节点、~100K–1M 向量舒适区、版本间破坏性 API。
- **核心能力**：嵌入式向量库（SQLite 持久化），内置默认 embedding 函数（可直接传原文），元数据过滤。
- **与设计稿契合点**：可作"记忆的向量后端"候选，但**原始文档与 embedding 混存于同一存储**——违反 P9（删除重建索引时原始数据与索引纠缠不清）。
- **建议**：**忽略**（作向量后端）。混合存储与 P9 相悖，API 稳定性差；价值仅在快速原型。

### 1.6 LanceDB
- **GitHub**：https://github.com/lancedb/lancedb
- **许可证**：Apache 2.0
- **成熟度**：活跃，但 API 0.x 快速变动、生态较小。
- **核心能力**：基于 Lance 列式格式的嵌入式文件型向量库（本地 `.lance` 文件 / 对象存储，无需服务端），多模态（文本/图像/视频），磁盘高效可超内存，自带版本化。
- **与设计稿契合点**：嵌入式、文件即数据（整目录可删可重建）符合 P9；自动版本化与 Archive 理念接近。
- **建议**：**参考（预案）**——数据超过单机内存或需多模态时的 faiss 升级路径；当前阶段不引入（已在用 faiss + aiosqlite）。

### 1.7 sqlite-vec
- **GitHub**：https://github.com/asg017/sqlite-vec
- **许可证**：Apache-2.0 / MIT 双许可（Mozilla Firefox 已内置采用）
- **成熟度**：2024 年起步、生态初期，但核心功能稳定（FreeBSD 官方 ports、Firefox 第三方 vendoring）。
- **核心能力**：SQLite 扩展，SQL 内直接向量检索（`WHERE embedding MATCH ? ORDER BY distance`）；元数据过滤即普通 SQL；数十万向量规模够用。
- **与设计稿契合点**：与项目已有的 aiosqlite **同库同事务**——四类子存储的原始数据与 embedding 分表共存，删表即删索引、重插即重建，**P9 分离最干净**。
- **建议**：**复用候选**（与 faiss-cpu 二选一或并存）——当 14.2 Memory API 的 Search 需要"元数据条件 + 向量"联合查询时，这是当前栈改动最小的方案。

---

## 2. LLM 多 Provider 统一适配（Compute 层）

**MyHarness 需求对照**：P8 可插拔算力——Think / Plan / Reflect / Compile 统一接口（14.5 LLM Provider Interface），切换引擎时 Memory/Skill/Identity 完全保留。

### 2.1 LiteLLM —— **直接采用**
- **GitHub**：https://github.com/BerriAI/litellm
- **许可证**：MIT（仅限非 enterprise 目录；Enterprise 增值功能商业授权）
- **成熟度**：2026 年最广泛采用的 OSS LLM 网关，18K+ stars；100+ 提供商 / 1,800+ 模型（OpenAI、Anthropic、Gemini/Vertex、Bedrock、Ollama、vLLM 等全包）。
- **核心能力**：统一 `litellm.completion()` SDK + 自托管 OpenAI 兼容代理（FastAPI + config.yaml）；虚拟 key/预算、路由/回退/重试、成本与延迟追踪、护栏回调、OpenTelemetry、缓存。
- **与设计稿契合点**：Think/Plan/Reflect/Compile 四个动词各映射一次统一调用，模型切换仅改配置——P8 直接满足；Memory/Skill/Identity 与其解耦，天然保留。
- **建议**：**直接采用**（SDK 模式即可，不必上代理服务）。⚠️ 2026-03-24 PyPI 出现被投毒的恶意版本（1.82.7/1.82.8，凭据窃取，已撤回）——**必须锁版本并校验 hash**。

### 2.2 OpenRouter —— **参考**
- **GitHub**：https://github.com/openrouter-ai（客户端库）；服务本体闭源托管
- **许可证**：专有（托管服务），客户端库开源
- **成熟度**：生产级托管路由网络。
- **核心能力**：一把 key 访问 400+ 模型，自动故障转移、按价格/吞吐/延迟路由；0% 加价 + 5.5% 平台费；不可自托管。
- **与设计稿契合点**：可作 LiteLLM 之后的其中一个 provider，或 BYOK 场景的旁路。
- **建议**：**参考**（作为可选上游提供商，不作为架构依赖）。

### 2.3 Portkey Gateway —— **参考**
- **GitHub**：https://github.com/Portkey-AI/gateway
- **许可证**：MIT（OSS 网关自托管；托管控制平面商业；2026 年被 Palo Alto Networks 收购）
- **成熟度**：生产级网关，企业化程度高。
- **核心能力**：负载均衡/回退/条件路由/熔断；20+ 原生护栏；**原生 MCP 网关**；语义缓存（企业版）；可观测性控制面。
- **与设计稿契合点**：护栏/治理能力丰富，但那些能力在 MyHarness 中属 Harness 层职责（guard/monitor），自研更契合协议语义。
- **建议**：**参考**——其"网关 + 护栏 + 可观测"分层可对照 Harness 设计，整体不引入。

### 2.4 langchain-core —— **参考其抽象，不引入依赖**
- **GitHub**：https://github.com/langchain-ai/langchain（core 包 https://pypi.org/project/langchain-core/）
- **许可证**：MIT
- **成熟度**：LangChain 1.0 于 2025-10 GA，API 稳定性承诺至 2.0；langchain-core 零第三方依赖，生态内最稳定包。
- **核心能力**：统一 BaseChatModel / Runnable 接口（pipe/stream/batch/async）；v1.0 新增 provider 无关的 Content Blocks 统一消息格式，由各 provider 适配器翻译。
- **与设计稿契合点**：它就是"统一消息格式 + 可插拔 provider 适配器"的成熟样板——14.5 协议可完全照此思路设计。
- **建议**：**参考抽象设计**（统一消息格式 + 适配器翻译模式），不引入整个 LangChain 依赖——与 P7 协议优先相悖；协议本体（Think/Plan/Reflect/Compile 的输入输出规范）归 MyHarness 自研。

---

## 3. 事件总线（Event Bus）

**MyHarness 需求对照**：P4 事件驱动；总线是系统内唯一数据流——路由 Event → Harness → LLM → Memory → Skill → Execution；14.1 需定义事件 Schema（类型/来源/时间戳/载荷/优先级）。
**先行的结论**：进程内路由应自研薄层 asyncio 总线（总线是实现细节，事件 Schema 才是协议）；分布式/持久化需求预留适配器接口，届时接 NATS 或 Redis Streams。

### 3.1 pypubsub —— **忽略**
- **GitHub**：https://github.com/schollii/pypubsub
- **许可证**：BSD-2-Clause
- **成熟度**：成熟稳定（v4.0+，源自 wxPython 生态）。
- **核心能力**：进程内同步发布订阅（topic 体系 + Message Data Specification）。
- **与设计稿契合点**：无。
- **建议**：**忽略**——同步阻塞、无 async/await 支持、投递顺序不保证、单向无应答，与事件驱动的 asyncio 运行时不合。

### 3.2 dramatiq —— **忽略**
- **GitHub**：https://github.com/Bogdanp/dramatiq
- **许可证**：LGPL-3.0
- **成熟度**：成熟分布式任务队列。
- **核心能力**：Broker + worker 执行后台任务函数（任务队列，非事件总线）。
- **与设计稿契合点**：无——"任务调度 = 函数调用"模型与"事件驱动"模型不同构。
- **建议**：**忽略**（LGPL 对商用也有侵入性；模型也不符）。

### 3.3 Redis Streams —— **预留适配器**
- **GitHub**：客户端 https://github.com/redis/redis-py
- **许可证**：Redis 服务器许可证几经变更（RSALv2/SSPL → 8.0 起 AGPLv3），部署前需确认；redis-py 客户端 MIT
- **成熟度**：成熟。
- **核心能力**：`xadd`/`xreadgroup`/`xack` 消费者组、`xpending`/`xclaim` 重试、`maxlen` 封顶、手动 DLQ；at-least-once。
- **与设计稿契合点**：已在跑 Redis 时是"轻量持久化事件流"最省事选项；亚毫秒延迟，吞吐数十万/秒。
- **建议**：**预留适配器**（多进程/需持久化时的可选项），不作为默认——默认单进程内路由不需要 Redis。

### 3.4 NATS / JetStream —— **多进程/分布式首选**
- **GitHub**：Python 客户端 https://github.com/nats-io/nats.py
- **许可证**：Apache 2.0
- **成熟度**：生产级（CNCF 毕业项目生态）。
- **核心能力**：亚毫秒延迟、`Nats-Msg-Id` 去重实现 exactly-once、durable consumer、DLQ、request/reply（支持 agent 间 RPC）；运维复杂度低。
- **与设计稿契合点**："publish 事件、订阅者随时接入、发布者无需感知订阅者"与 MyHarness 的事件路由模型完全同构。
- **建议**：**预留首选适配器**。另有 walnats（https://pypi.org/project/walnats/ ，NATS 之上的类型化事件框架：Event→subject、Actor→consumer，exactly-once + 智能重试）可作其上层参考——与"Event 是唯一数据流"的模型非常接近。
- **结论**：进程内 Event → Harness → LLM → Memory → Skill → Execution 路由在单进程内完成时，**自研 ~200–300 行类型化 asyncio pub/sub 总线**（事件 Schema 属协议 14.1，总线只是实现）；第三方总线要么太简单（pypubsub）要么需服务端（Redis/NATS），都不该在协议层引入。

---

## 4. 工具/驱动标准（MCP，Model Context Protocol）

**MyHarness 需求对照**：14.4 Execution Driver Interface（统一驱动协议、Capability Discovery、安全校验）；Harness 类比 Windows Driver/CUDA/HAL/POSIX；driver/adapters 已有 robot/browser/mcp/api/computer/database/iot。
**结论先行**：**MCP 就是 Execution 层统一驱动协议的现成答案，应直接采用**；它与 function calling 互补不竞争。

### 4.1 MCP 现状（2026-08）
- **规范**：https://modelcontextprotocol.io ；GitHub https://github.com/modelcontextprotocol （官方 Python SDK: https://github.com/modelcontextprotocol/python-sdk，SDK 分级 Tier 1/2/3，2026-02 发布）
- **治理**：2025-12-09 Anthropic 将 MCP 捐赠给 Linux Foundation 旗下新成立的 **Agentic AI Foundation（AAIF）**，OpenAI 与 Block 联合创始，AWS/Google/Microsoft/Cloudflare/Bloomberg 白金会员，170+ 成员组织；规范演进走 SEP（Specification Enhancement Proposals）流程。
- **2026-07-28 规范**（最大修订、最后一个破坏性版本）：无状态化 HTTP 核心（移除 initialize 握手与 session id，改 `_meta` 携带 + `server/discover` 能力发现）；`Mcp-Method`/`Mcp-Name` 头支持网关路由；一等扩展框架（reverse-DNS 标识 + 独立扩展仓库）；OAuth/OIDC 加固；功能弃用需至少 12 个月过渡期。
- **采纳数据**：月 SDK 下载 ~1 亿次；公共 server 1 万+；Claude/ChatGPT/Gemini/Codex/Cursor 原生支持；Stacklok 调查 41% 软件组织已在生产运行 MCP server。
- **安全警示**：2026 上半年 30+ MCP 相关 CVE（含 CVSS 9.4/9.6 级 RCE）；tool poisoning（工具描述注入）是结构性问题；NSA 2026-06 发布 MCP 自动化安全设计考量。应对：server 当第三方依赖管理、最小权限、沙箱执行、破坏性工具人工审批、调用审计。

### 4.2 MCP 与 Function Calling 的关系（互补）
- **Function calling / tool use**：模型 API 特性——每次请求内嵌 JSON schema（OpenAI 的 `parameters`、Anthropic 的 `input_schema` 格式不一），执行逻辑在应用侧，厂商锁定、每个应用重复定义。适合应用私有、延迟敏感、临时工具。
- **MCP**：系统级客户端-服务端协议——server 端同时持有 schema 与执行逻辑，客户端运行时 `tools/list` 发现；stdio / HTTP 传输；OAuth 2.1 授权、审计、网关治理；一套 server 多客户端复用。**MCP 工具最终仍以 function calling 形状暴露给模型**，由客户端负责翻译。
- **结论**：MCP 不取代 function calling，它标准化 function calling 之上的一层。MyHarness 内部：LLM 层用 function calling（LiteLLM 统一），Execution 层对外用 MCP。

### 4.3 与 MyHarness 的契合
- MCP 的 `tools/list` 动态能力发现 ≈ 14.4 的 Capability Discovery；OAuth/审计/allowlist ≈ 安全校验接口；Robot/Browser/API/Database/IoT 每个 Driver 实现为一个 MCP server（或直接连现成 server），Harness 侧统一 MCP client 包适配器——项目已有 `driver/adapters/mcp`，方向正确。
- **重要边界**：MCP 工具是 schema 级能力，**≠ Skill**。Skill（执行模板 + 生命周期 + 置信度 + 边界）仍是 MyHarness 自研语义层；Skill 可引用 MCP 工具作为其执行载体——"能力商店（语义层）"与"驱动协议（传输层）"是两层。
- **建议**：**直接采用** MCP（官方 Python SDK + 现成 server 生态）作为 Execution 驱动协议层；Harness 抽象保持自研不动，在其上补权限/审计/沙箱（对应 guard/monitor 模块）。

---

## 5. Agent 编排参考（只参考架构，不复用）

**MyHarness 需求对照**：P1 单一认知中心（只有 LLM 负责推理）；P2 四权分离；P5 能力沉淀；P6 计算最小化。
**先行的结论**：这些框架无一例外把 compute/memory/skill/execution 揉进同一个 agent 循环——**没有任何现成实现体现四权分离**，编排层必须自研；参考点集中在工具抽象、状态管理、配置与教训。

### 5.1 OpenClaw —— **重点反面教材（用户直觉得到证实）**
- **GitHub**：https://github.com/openclaw/openclaw （原 Clawdbot/Moltbot）
- **许可证**：MIT（OpenClaw Foundation）
- **成熟度**：2026 年最火的本地优先个人 AI 助手（社区数万 star 级），但安全与架构缺陷频发。
- **架构**：Gateway 微内核（单长驻 WebSocket 服务 = 消息总线 + 鉴权信任边界 + 多 agent 路由 + HTTP 宿主）；五层：渠道（25+ 适配器）/ 编排 / 能力（全插件化）/ 记忆（向量记忆 + Dreaming 整合 + Active Recall）/ 模型（9 种 LLM 协议）；config 驱动热加载。
- **已验证的缺陷（与用户判断一致：技能/算力/记忆混在一起）**：
  1. **技能 = 提示词配方而非一等对象**：Skill 只是注入系统提示的 SKILL.md 文本，从不进入 agent 的 tool_use schema；与内置工具同名的自定义技能必然被模型忽略；700+ 技能导致每轮全量重发现、10 万+ token 上下文膨胀。
  2. **记忆弱且不可信**：任务/项目召回漂移、Compaction 有损、Dreaming 默认关闭——社区大量用户外挂独立记忆系统。
  3. **单线程事件循环瓶颈**：agent 准备阶段 14–26 秒、WebSocket 响应排队 15–100 秒+、无缓存每轮重建。
  4. **技能即代码无沙箱**：ClawHub 供应链攻击（341 个恶意技能）、2.1 万+ 公网暴露实例、多个严重 CVE。
- **借鉴**：全插件能力层、渠道适配器、配置热加载。
- **避开**：技能=提示词、记忆塞上下文、单线程架构、无沙箱执行、技能市场无审核。MyHarness 的"Skill 一等对象 + 记忆是数据库 + async 事件驱动 + guard 沙箱"恰好是对症解药。

### 5.2 OpenManus —— **极简循环骨架参考**
- **GitHub**：https://github.com/mannaandpoem/OpenManus
- **许可证**：MIT
- **成熟度**：55K+ stars，MetaGPT 团队开源 Manus 替代，原型级。
- **架构**：`BaseAgent` → `ReActAgent`（抽象 `think()`/`act()`）→ `ToolCallAgent`（工具调用循环）→ `Manus`；`BaseTool` 插件式 + Pydantic 参数校验 + `ToolCollection`；`PlanningFlow` 多步规划；20 步循环 + 卡死检测；TOML 配置。
- **借鉴**：极简 agent 循环模板（think/act 分离与 Think/Plan/Reflect/Compile 语感一致）、工具抽象与参数校验、配置分离。
- **避开**：记忆 = 进程内消息列表（无持久化）、无技能生命周期、无驱动抽象——正是 MyHarness 要补齐的四权。

### 5.3 LangGraph —— **状态/检查点思想参考**
- **GitHub**：https://github.com/langchain-ai/langgraph
- **许可证**：MIT（v1.1.x 活跃）
- **核心能力**：图状态机 + typed state + checkpoint 持久化 + 时间旅行调试 + human-in-the-loop。
- **借鉴**：durable execution 与 checkpoint 思想——可映射为 MyHarness Runtime 的持久化事件日志（Event Sourcing 风格重放）。
- **避开**：把编排固化进框架（graph 即应用结构），与"Harness 是协议不是框架"相悖；P1 单一认知中心下不需要多 agent 图拓扑。

### 5.4 AutoGen —— **忽略（已死）**
- **GitHub**：https://github.com/microsoft/autogen
- **许可证**：MIT（代码）+ CC-BY-4.0（文档）
- **状态**：**2025 年底进入维护模式**（v0.7.5 为最后版本），微软官方推荐迁移到 Microsoft Agent Framework（MIT）或社区 AG2 fork（Apache 2.0）。
- **建议**：**忽略**——活跃度是 2026 年选型第一指标（其 58K stars 是误导）；会话式多 agent 群聊模型也与 P1 冲突。

### 5.5 CrewAI —— **参考 API 设计，避开多角色模型**
- **GitHub**：https://github.com/crewAIInc/crewAI
- **许可证**：MIT（v1.14+ 活跃，v1.14 起支持 checkpoint/resume）
- **核心能力**：角色制 crew（researcher/writer/reviewer + Sequential/Hierarchical 流程），50 行内可跑通。
- **借鉴**：任务编排 API 的简洁性。
- **避开**：多角色智能体组织——MyHarness P1 只允许一个认知中心（LLM），"角色"只能是 Skill 的参数化而非独立 agent。

### 5.6 MetaGPT —— **SOP 流水线思想参考**
- **GitHub**：https://github.com/FoundationAgents/MetaGPT
- **许可证**：MIT（活跃，研究属性）
- **核心能力**：软件公司 SOP 流水线——PM/架构/工程/QA 角色产出标准化产物（PRD/设计/代码/测试）。
- **借鉴**："经验 → 标准化产物 → 沉淀"与 P5 能力沉淀同源；SOP 可对照 Skill 执行模板。
- **避开**：多角色协作研究形态、高 token 消耗（每步多次 LLM 调用）。

---

## 6. 向量检索（原始/衍生数据分离视角）

**MyHarness 需求对照**：P9——原始数据（experience.jsonl / identity.json / knowledge.json 等）持久化不可篡改；衍生数据（embeddings.index、检索缓存）可删除重建。
**先行的结论**：四类候选都满足"可重建"（均为文件/表级），区分点在**原始数据与索引是否纠缠**。

| 候选 | 形态 | 许可证 | 规模上限 | 元数据过滤 | 与 P9 的关系 |
|---|---|---|---|---|---|
| **faiss-cpu**（已在栈） | 算法库（C++，索引文件持久化） | MIT | 百万级+（可 GPU） | 无（需自行 SQL 过滤 + ID 映射） | **最契合**：索引文件是纯衍生数据，删了重建零负担；性能最强（1M/768d CPU ~1.5ms） |
| Chroma | 嵌入式 DB（SQLite 内混存文档+embedding） | Apache 2.0 | ~100K–1M | 有 | **不契合**：原始/衍生混存纠缠；API 版本间破坏 |
| Qdrant | Rust 服务端（REST/gRPC） | Apache 2.0 | 亿级（分布式） | 最强（检索前过滤） | 满足但过重：独立服务 + 运维成本，与本地优先冲突 |
| LanceDB | 嵌入式文件型（.lance） | Apache 2.0 | 100K–1M+（超内存） | 有 | 满足（文件可重建）；0.x API 变动快 |
| sqlite-vec | SQLite 扩展（同库分表） | Apache-2.0/MIT | 数十万 | 有（普通 SQL） | **很契合**：删表即删索引，与 aiosqlite 同事务 |

- **建议**：**维持 faiss-cpu**（已在栈、性能、索引=独立衍生文件的语义最直观、删 `embeddings.index` 重建即可），原始数据全部留在 aiosqlite；当 14.2 Memory API 的 Search 需要"元数据条件 + 向量"联合查询时，升级路径是 **sqlite-vec**（同库同事务、零新组件），而不是引入服务端向量库。Qdrant/LanceDB 仅作规模超出单机内存时的预案。**Chroma 明确不用**（P9 直接冲突）。
- 提醒：向量库只占 RAG 质量 ~5–10%，分块策略、embedding 模型与检索管线更重要——MyHarness 的重心应放在 14.2 Search 协议本身。

---

## 7. Skill / 工作流引擎（技能版本管理 + 生命周期）

**MyHarness 需求对照**：14.3 Skill Interface——标准描述格式、生命周期 Draft→Testing→Verified→Stable→Deprecated→Archived、**版本管理归属 Harness**；Skill 字段含 Name/Version/Input/Output/Parameters/Boundary/Capability/Confidence；P5 能力沉淀。
**先行的结论**：**没有开源实现与上述生命周期 + 版本管理归属 Harness 完全一致**；但"技能注册表/版本/生命周期"生态已在 2026 年收敛出一套共同模式，全部可直接对照。

### 7.1 Nacos Skill Registry —— **生命周期状态机最佳参考**
- **GitHub**：https://github.com/alibaba/nacos （Skill Registry 自 3.2.0 起）
- **许可证**：Apache 2.0
- **核心能力**：每版本生命周期 **draft → reviewing → online → offline**（与 Draft/Testing/Verified/Stable/Deprecated 映射极佳）；插件化发布流水线（提示注入/数据泄漏/恶意代码扫描，REJECTED 回退 draft）；PUBLIC/PRIVATE 可见性；标签别名（latest/stable/beta/canary）；每个技能同时只允许一个 draft/reviewing 版本。
- **建议**：**参考**——状态机 + 自动化评审流水线 + 人工放行，正是 Testing→Verified 阶段要的机制。

### 7.2 SkillHub（科大讯飞）—— **版本管理最佳样板**
- **GitHub**：https://github.com/iFlytek/...（文档 https://iflytek.github.io/skillhub ）
- **许可证**：开源（可 Docker/K8s 自托管）
- **核心能力**：企业级技能注册表——SemVer 不可变版本、多版本共存、`^1.2.0`/`~2.0.0` 解析、标签别名（`latest`/`stable` 可重指实现回滚）、团队命名空间、RBAC、审计日志、安全扫描器、npm 式发布体验（CLI/Web/REST API）。
- **建议**：**参考**——版本不可变 + 标签别名 + 回滚机制直接照搬进 14.3。

### 7.3 Bifrost Skills Repository —— **多运行时市场参考**
- **GitHub**：https://github.com/（docs.getbifrost.ai 的 Skills Repository 功能）
- **核心能力**：可安装到 Claude Code / Codex 等 harness 的 marketplace；不可变 SemVer 快照 + "served version" 概念控制市场暴露面。
- **建议**：**参考**——"同一技能多目标运行时暴露控制"可对照 MyHarness 多 Driver 适配场景。

### 7.4 skill-tree —— **状态集合 + 谱系参考**
- **GitHub**：npm 包 https://www.npmjs.com/package/skill-tree
- **核心能力**：`SkillStatus: 'draft' | 'active' | 'deprecated' | 'experimental'`；SemVer、谱系追踪（lineage）、fork/merge、回滚、版本 diff。
- **建议**：**参考**——状态枚举与 Deprecated 处理（`deprecateSkill(id)` API）可对照 14.3。

### 7.5 llmrix-skill —— **Git 双轨存储参考**
- **GitHub**：https://github.com/llmrix/llmrix-skill
- **核心能力**：Git 仓库为唯一真相源的技能/插件管理框架；轻量 worker 同步模式 + 数据库管理模式（发布、元数据解析、版本回滚）。
- **建议**：**参考**——"Git 为原始真相 + DB 为检索面"与 P9 原始/衍生分离同构。

### 7.6 Yao Meta Skill / Prodcraft / n-skills —— **治理与弃用规则参考**
- **Yao Meta Skill**（https://github.com/yaojingang/yao-meta-skill ）：发布门禁、证据台账、beta 就绪与生产承诺分离——与 Skill.Confidence 字段 + Verified/Stable 分级同构。
- **Prodcraft**（https://github.com/yknothing/prodcraft ）：内部创作成熟度与对外公开面分离；弃用迁移规则（弃用别名 → 新规范名 → 旧名移除，至少一个发布周期重叠）；portability 契约（portable_as_is / with_caveat / blocked）。**Deprecated→Archived 阶段的最佳参考**。
- **n-skills**（Claude Code 风格 marketplace）：SemVer 变体（v1.MAJOR.MINOR）+ Git tag + 自动同步 bump。
- **建议**：**参考**上述治理/弃用/信心分级模式。

### 7.7 重型工作流引擎（Temporal / Prefect / Airflow 等）—— **忽略**
- 面向任务调度与 DAG，无"技能"语义，与 P4 事件驱动、P5 技能沉淀模型不符；引入即重引擎。**忽略**。

---

## 8. 整体选型建议（汇总）

### 直接采用（适配成熟组件，不重复造轮子）
1. **LiteLLM（SDK 模式）** —— LLM 层唯一后端：Think/Plan/Reflect/Compile 各动词的内部实现，满足 P8 可插拔算力。锁版本防供应链。
2. **MCP（官方 Python SDK）** —— Execution 驱动协议层：`tools/list` 即能力发现，1 万+ 现成 server 生态，Harness 之上补权限/审计/沙箱即可。
3. **faiss-cpu（维持）+ 可选 sqlite-vec** —— 向量检索后端：索引即衍生数据文件/表，删除重建零负担，P9 最契合。

### 深度参考（借鉴架构，不引入依赖）
4. **Graphiti** —— Relationship/Episodic 子存储与 Archive 接口的蓝本：三子图分层（episode 原始 → entity 衍生）、双时间、矛盾时失效不删除；用 aiosqlite + networkx 复刻，不引 Neo4j。
5. **Letta / Mem0** —— Memory API（14.2）接口形态（记忆块 + 工具化读写）与语义记忆抽取/去重/过期写入路径。
6. **Nacos Skill Registry + SkillHub + Prodcraft + skill-tree** —— Skill 生命周期（14.3）的状态机、SemVer 不可变版本 + 标签回滚、弃用迁移规则、Confidence 分级。
7. **OpenClaw / OpenManus / LangGraph** —— 经验与教训：技能必须是一等对象（不能是提示词）、记忆必须是数据库（不能塞上下文）、事件驱动必须 async-first（不能单线程）、状态用 checkpoint/事件日志持久化。

### 必须自研（开源无对应物）
8. **Event Bus 进程内总线** —— 类型化 asyncio pub/sub 薄层（事件 Schema 是协议 14.1，总线是实现）；预留 NATS / Redis Streams 适配器接口。
9. **Memory 层整体** —— Identity 子存储开源界无对应物（P3 外置身份）；四类子存储 + Read/Write/Search/Archive + 原始/衍生分离的组合无现成实现。
10. **Skill Store + Harness** —— 技能生命周期语义（14.3）与 Agent Driver Protocol（能力发现/驱动适配/事件路由/资源调度/权限/生命周期/插件/兼容）是 MyHarness 的差异化核心。
11. **LLM Provider Interface 协议（14.5）** —— Think/Plan/Reflect/Compile 的输入输出规范归 MyHarness；LiteLLM 只是其实现后端。

> 一句话总结：**开源界无人实现四权分离——记忆、编排、技能三层无货架品，必须自研；但"算力统一适配（LiteLLM）、驱动协议（MCP）、向量检索（faiss/sqlite-vec）、技能注册表模式（Nacos/SkillHub）"四件事有成熟组件可直接采用或对照实现。**

---

## 调研说明

- **调研日期**：2026-08-02
- **调研方法**：WebSearch 检索验证（共 14 次检索，覆盖 7 个维度），信息来源包括：项目官方 GitHub 仓库、官方文档站、Thoughtworks Technology Radar、2026 年第三方对比文章（futureagi/vectorize/respan/atlan 等）、GitHub issues、开源数据库许可目录、Linux Foundation 与 MCP 官方博客等。所有项目名、GitHub 链接、许可证、成熟度判断均来自上述检索结果。
- **注意**：各项目迭代极快（2026 年上半年 MCP 规范两次大版本、AutoGen 进入维护模式、LiteLLM 出现供应链事件），落地前建议复核各仓库最新状态；许可证以仓库 LICENSE 文件为准。
