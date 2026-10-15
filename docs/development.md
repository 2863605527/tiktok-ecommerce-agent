# 开发指南

## 环境准备

```bash
# Python 3.10+
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS / Linux
source .venv/bin/activate

pip install -e ".[dev]"
pre-commit install
```

## 配置

复制 `.env.example` 为 `.env`，至少填写：

```
LLM_API_KEY=sk-xxx            # 必填
LLM_BASE_URL=https://api.openai.com/v1   # 可换 DeepSeek/豆包
```

## 常用命令

```bash
make lint        # ruff 检查
make format      # ruff 格式化
make type        # mypy
make test        # 单测（无需外部依赖）
make test-int    # 集成测试（标记 integration）
make run         # 跑一次流水线
make serve       # 起 API（http://127.0.0.1:8000/docs）
```

## 开发顺序（TODO 清单）

1. `crawlers/tiktok.py`：补全真实采集（playwright 或平台接口）
2. `crawlers/supplier.py`：补全货源搜索解析
3. `agents/sourcing_agent.py`：接入 LLM 关键词精炼
4. `agents/listing_agent.py`：接入真实图片源目录
5. 补充集成测试覆盖真实依赖

## 质量门槛

- 提交前 `make check` 全绿
- 新代码必须带单元测试
- 外部数据必须标注来源，禁止伪造
