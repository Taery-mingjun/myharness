# Protocol 14.4 — Execution Driver Interface 规范

> 设计稿依据：MyHarness v1.1 §10（Driver 抽象）、§7.2（Harness 职责）、§14.4（Execution Driver Interface）
> 代码实现：`src/myharness/driver/`（protocol/capability/translation/adapters/）、`harness/guard.py`、`harness/registry.py`
> 版本：v0.1（2026-08-02）· 状态：框架已实现 ✅ / MCP 驱动待真实接入（P0）

## 1. 目的

**机器人/浏览器/数据库等硬件细节不向上层暴露**（§10）。LLM 与 Skill 都不知道底层协议，只面向 Harness 定义的统一驱动接口。上层调用 `Grab()`，Harness 翻译为 Joint/Torque/CAN/PID（例：§10.1）。

## 2. 统一驱动协议（UnifiedDriverProtocol）

所有驱动实现同一抽象（`driver/protocol.py`，全部 async）：

| 方法 | 说明 |
|---|---|
| `driver_name` / `driver_version` | 驱动标识 |
| `capabilities() -> list[CapabilityDescriptor]` | 能力声明（§7.2 Capability Discovery 依据） |
| `initialize()` / `shutdown()` | 生命周期 |
| `execute(action, parameters, context) -> ExecutionResult` | 同步执行 |
| `execute_stream(...) -> AsyncIterator[ExecutionProgress]` | 流式执行 |
| `sense(capability) -> dict` | 感知类操作 |
| `health_check() / get_status()` | 健康与状态 |

**能力声明**（`schema/capability.py::CapabilityDescriptor`）：`name / description / driver_name / actions[]`。驱动注册进 `harness/registry.py::CapabilityRegistry`，Harness 按能力查找驱动（`get_driver_for_capability`）。

## 3. 驱动适配器目录（adapters/）

| 适配器 | 状态 | 说明 |
|---|---|---|
| `api.py` | 实现 | HTTP/REST 执行 |
| `robot.py` | 实现 | 机器人（Joint/Torque/CAN/PID 翻译走 `translation.py`） |
| `browser.py` | 实现 | 浏览器自动化 |
| `computer.py` | 实现 | 本机计算机操作 |
| `database.py` | 实现 | 数据库执行 |
| `iot.py` | 实现 | IoT 设备 |
| `mcp.py` | ⚠️ **STUB** | **P0：采用官方 MCP Python SDK 实现真实客户端**（S3 决策） |

## 4. MCP 接入规范（P0，S3 决策落地）

- 采用 **Model Context Protocol**（2026-07 新版：无状态 HTTP + 能力发现；AAIF 基金会治理；官方 Python SDK）作为 Execution 层的行业标准
- 映射：MCP `tools/list` → `CapabilityDescriptor` 发现；MCP `tools/call` → `execute()`；MCP resources → `sense()`
- **MCP 工具 ≠ Skill**：MCP 工具是执行原语，Skill 是语义层执行模板（绑定 driver_type + action_template + 白名单）——二者不得混淆
- **安全（S2 调研）**：tool poisoning（恶意 MCP 服务器注入工具描述）由 `harness/guard.py::ExecutionGuard` 授权检查 + `monitor.py` 监控应对；Skill 动作白名单（14.3 §2）是最后防线

## 5. 安全校验接口（§14.4）

| 机制 | 实现 | 说明 |
|---|---|---|
| 授权检查 | `ExecutionGuard.authorize()` | 执行前校验 actor/资源/动作（P 原则下默认拒绝） |
| 权限管理 | `PermissionManager.check/grant/revoke` | 按 actor 的细粒度授权 |
| 技能动作白名单 | `SkillDefinition.permits_action()` | 防 prompt 注入驱动动作 |
| 执行边界 | `tests/integration/test_execution_boundary.py` | 集成测试保障 |
| 紧急停止 | RuntimeMonitor 心跳 + `supervisor.shutdown()` | 运行时监督 |

## 6. 待落地缺口

1. **MCP 驱动真实实现（P0）**：替换 `adapters/mcp.py` stub；引入官方 SDK（锁版本）；补集成测试（连 mock MCP 服务器验证 tools/list → capabilities 映射）
2. **Driver 适配器测试覆盖**：S1 报告指出 semantic 等低覆盖区，driver 适配器测试同步补强（P2）
