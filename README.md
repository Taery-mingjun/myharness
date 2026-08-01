# MyHarness - Cognitive Operating System

MyHarness (MYH) 是一个认知操作系统，实现了LLM Agent的四权分离架构：Compute(算力)、Memory(记忆)、Skill(能力)、Execution(执行)完全解耦。

## 架构原则

- **P0**: LLM 是认知运行时，不是身份容器
- **P1**: 单一认知中心
- **P2**: 四权分离
- **P3**: 身份外置 (Identity 归属 Memory)
- **P4**: 事件驱动
- **P5**: 能力沉淀 (经验→Skill)
- **P6**: 计算最小化
- **P7**: 协议优先
- **P8**: 可插拔算力
- **P9**: 原始/衍生数据分离

## 快速开始

```bash
# 安装依赖
pip install -e ".[dev]"

# 配置环境变量
cp .env.example .env
# 编辑 .env 填入你的 LLM API Keys

# 运行测试
pytest

# 启动 API 服务
uvicorn myharness.api.app:create_app --reload
```

## 项目结构

```
src/myharness/
├── core/          # 配置、依赖注入、异常、日志
├── schema/        # Pydantic 数据模型
├── bus/           # 事件总线、路由
├── memory/        # 记忆系统 (Identity/Episodic/Semantic/Relationship)
├── llm/           # LLM 引擎 (多Provider适配)
├── skill/         # 能力商店
├── harness/       # 核心枢纽层
├── runtime/       # 运行时循环
├── driver/        # 执行驱动抽象
└── api/           # FastAPI REST API
```
