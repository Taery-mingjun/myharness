# MyHarness (MYH) 项目配置文件

## 文件路径: pyproject.toml

```
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "myharness"
version = "0.1.0"
description = "MyHarness - Cognitive Operating System for AI Agents"
readme = "README.md"
license = {text = "MIT"}
requires-python = ">=3.11"
authors = [
    {name = "Taerymingjun"},
]
keywords = ["ai", "agent", "cognitive", "llm", "memory", "skill"]
classifiers = [
    "Development Status :: 3 - Alpha",
    "Intended Audience :: Developers",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
]

dependencies = [
    # Web Framework
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.30.0",

    # Data Validation
    "pydantic>=2.9.0",
    "pydantic-settings>=2.5.0",

    # Async
    "httpx>=0.27.0",
    "aiofiles>=24.0.0",

    # Database & Storage
    "aiosqlite>=0.20.0",

    # Vector Search
    "faiss-cpu>=1.8.0",
    "numpy>=1.26.0",

    # LLM Providers
    "openai>=1.50.0",
    "anthropic>=0.34.0",
    "google-generativeai>=0.8.0",

    # Dependency Injection
    "lagom>=2.0.0",

    # Prompt Templates
    "jinja2>=3.1.0",

    # Observability
    "structlog>=24.0.0",

    # Graph
    "networkx>=3.3.0",

    # Utilities
    "python-dotenv>=1.0.0",
    "pyyaml>=6.0.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0.0",
    "pytest-asyncio>=0.24.0",
    "pytest-cov>=5.0.0",
    "httpx>=0.27.0",
    "ruff>=0.6.0",
    "mypy>=1.11.0",
]

browser = [
    "playwright>=1.45.0",
]

all = [
    "myharness[dev,browser]",
]

[project.scripts]
myharness = "myharness.cli:main"

[tool.hatch.build.targets.wheel]
packages = ["src/myharness"]

[tool.ruff]
target-version = "py311"
line-length = 100
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM", "C4"]

[tool.mypy]
python_version = "3.11"
strict = true
warn_unreachable = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
addopts = "-v --cov=src/myharness --cov-report=term-missing"
```

## 文件路径: .env.example

```
# MyHarness Environment Configuration

# --- LLM Providers ---
# OpenAI
OPENAI_API_KEY=sk-...
OPENAI_DEFAULT_MODEL=gpt-4o

# Anthropic (Claude)
ANTHROPIC_API_KEY=sk-ant-...
ANTHROPIC_DEFAULT_MODEL=claude-3-opus-20240229

# Google (Gemini)
GOOGLE_API_KEY=...
GOOGLE_DEFAULT_MODEL=gemini-2.0-flash

# Qwen (通义千问)
QWEN_API_KEY=...
QWEN_DEFAULT_MODEL=qwen-max

# DeepSeek
DEEPSEEK_API_KEY=sk-...
DEEPSEEK_DEFAULT_MODEL=deepseek-chat

# --- Default Provider ---
# One of: openai, anthropic, google, qwen, deepseek, local
MYH_DEFAULT_LLM_PROVIDER=openai

# --- Local Model (Ollama) ---
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_DEFAULT_MODEL=llama3.1

# --- Memory ---
MYH_DATA_DIR=./data
MYH_EMBEDDING_DIMENSION=1536
MYH_VECTOR_INDEX_TYPE=IVFFlat

# --- API Server ---
MYH_API_HOST=0.0.0.0
MYH_API_PORT=8000
MYH_API_DEBUG=false

# --- Logging ---
MYH_LOG_LEVEL=INFO
MYH_LOG_FORMAT=json

# --- Runtime ---
MYH_COGNITIVE_LOOP_INTERVAL_MS=100
MYH_MAX_CONCURRENT_TASKS=10
MYH_DEFAULT_TASK_TIMEOUT=300
```

## 文件路径: README.md

```
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
```

## 文件路径: .gitignore

```
# Python
__pycache__/
*.py[cod]
*$py.class
*.egg-info/
dist/
build/
*.egg

# Virtual environments
.venv/
venv/
env/

# IDE
.idea/
.vscode/
*.swp
*.swo

# Environment
.env
.env.local

# Data (runtime generated)
data/memory/source/*
data/memory/derived/*
data/memory/indexes/*
data/skills/*
!data/memory/source/.gitkeep
!data/memory/derived/.gitkeep
!data/memory/indexes/.gitkeep
!data/skills/.gitkeep

# Testing
.coverage
htmlcov/
.pytest_cache/
.ruff_cache/

# OS
.DS_Store
Thumbs.db

# Logs
*.log
```
