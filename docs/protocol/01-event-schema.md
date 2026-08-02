# Protocol 14.1 — Event Schema 规范

> 设计稿依据：MyHarness v1.1 §8（Event Bus）、§14.1（Event Schema）
> 代码实现：`src/myharness/schema/event.py`、`src/myharness/bus/`
> 版本：v0.1（2026-08-02）· 状态：草案（载荷强类型化待落地，见 §6）

## 1. 目的

MyHarness 系统内部**只有一种数据流：Event**。所有模块只处理 Event，不直接互相调用。本文档定义 Event 的通用结构与各类事件的载荷规范，保证跨模块、跨版本的一致性。

## 2. 通用字段（BaseEvent）

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `event_id` | str (uuid4) | ✅ | 全局唯一事件标识 |
| `event_type` | EventType 枚举 | ✅ | 事件判别符，路由依据 |
| `timestamp` | datetime (UTC) | ✅ | 事件创建时间，强制 UTC（naive 自动转换） |
| `source` | str | ✅ | 发出方标识（如 `"llm.engine"`、`"memory.system"`） |
| `correlation_id` | str \| None | — | 同一次认知任务的关联链 |
| `causation_id` | str \| None | — | 直接触发本事件的上一事件（事件溯源） |
| `payload` | 各事件专属类型 | ✅ | 事件载荷（**待强类型化**，见 §6） |
| `metadata` | dict | — | 可观测性扩展元数据 |

## 3. 事件类型目录（EventType）

### 3.1 外部输入
| 枚举 | 值 | 载荷要点 |
|---|---|---|
| `USER_MESSAGE` | user.message | content / attachments / role |
| `VISION_RESULT` | vision.result | image_id / detections / descriptions / confidence |
| `SENSOR_READING` | sensor.reading | sensor_id / sensor_type / value / unit / accuracy |
| `TIMER_TRIGGER` | timer.trigger | timer_id / scheduled_at / reason |

### 3.2 认知管线（LLM Engine 原语）
| 枚举 | 值 | 载荷要点 |
|---|---|---|
| `COGNITIVE_REQUEST` | cognitive.request | query / context / priority |
| `THINK_RESULT` | cognitive.think.result | thought / reasoning_trace / confidence / tokens_used |
| `PLAN_RESULT` | cognitive.plan.result | plan_id / steps / estimated_cost / alternatives |
| `REFLECT_RESULT` | cognitive.reflect.result | experience_id / insights / skill_update_proposals / identity_insights |
| `COMPILE_RESULT` | cognitive.compile.result | skill_proposal / compiled_from / validation_results |

### 3.3 身份（P3 Identity 外置）
| 枚举 | 值 | 载荷要点 |
|---|---|---|
| `IDENTITY_INTERPRETATION` | identity.interpretation | current_identity / contextual_interpretation / relevant_aspects |
| `IDENTITY_UPDATE_PROPOSAL` | identity.update_proposal | field / current_value / proposed_value / reasoning / confidence |

### 3.4 记忆操作
| 枚举 | 值 | 载荷要点 |
|---|---|---|
| `MEMORY_READ` / `MEMORY_WRITE` / `MEMORY_SEARCH` / `MEMORY_UPDATE` / `MEMORY_ARCHIVE` | memory.* | entry_id / category / query / filters / version |

### 3.5 Skill 生命周期
| 枚举 | 值 | 载荷要点 |
|---|---|---|
| `SKILL_DISCOVERED` | skill.discovered | capability / context / suggested_skill_name |
| `SKILL_LOADED` | skill.loaded | skill_id / version / parameters / driver |
| `SKILL_FINISHED` | skill.finished | skill_id / result / duration_ms / resources_used |
| `SKILL_FAILED` | skill.failed | skill_id / error / stage / retry_count |
| `SKILL_STATUS_CHANGED` | skill.status_changed | skill_id / from_status / to_status / reason |

### 3.6 执行
| 枚举 | 值 | 载荷要点 |
|---|---|---|
| `EXECUTION_START` / `EXECUTION_PROGRESS` / `EXECUTION_COMPLETE` / `EXECUTION_ERROR` | execution.* | task_id / action / result / error / recoverable |
| `ROBOT_FEEDBACK` | execution.robot_feedback | robot_id / sensor_data / joint_states / status |

### 3.7 系统
| 枚举 | 值 | 载荷要点 |
|---|---|---|
| `SYSTEM_STARTUP` / `SYSTEM_SHUTDOWN` | system.* | version / components / reason / pending_tasks |
| `ERROR` | system.error | error_type / message / stack_trace / component |
| `HEARTBEAT` | system.heartbeat | uptime_seconds / active_tasks / memory_usage_mb |

## 4. 路由规则（设计稿 §8.2）

```
Event → Harness → LLM → Memory → Skill → Execution
```

- 模块间禁止直接方法调用，一律通过 `EventBus.publish()` / `request()` / `enqueue()`（见 14.1 总线章节）
- 路由由 `bus/router.py` 的 `RouteRule` 规则表驱动；`correlation_id` 贯穿全程用于追踪
- 队列消费者必须显式 `claim_queue_consumer()` 声明归属（防多消费者竞争）

## 5. 事件可靠性要求

| 要求 | 说明 |
|---|---|
| 不可变 | Event 发出后不得修改；需要修正时发新事件 |
| 时间戳 | 一律 UTC；接收方不得依赖本地时区 |
| 幂等 | 消费方按 `event_id` 去重（系统级约定，执行层实现） |

## 6. 待落地缺口（P0）

1. **`priority` 字段缺失**：设计稿 14.1 明确通用字段含"优先级"，BaseEvent 暂无。Scheduler 无法做优先级调度。**计划**：`priority: int (0-9, 默认 5)`，纳入 BaseEvent。
2. **载荷未强类型化**：27 种事件 payload 均为 `dict[str, Any]`，格式只存在于 docstring。**计划**：为每类事件定义 pydantic 载荷模型（如 `UserMessagePayload`），payload 字段类型从 `dict` 改为具体模型；提供向后兼容的解析入口。
