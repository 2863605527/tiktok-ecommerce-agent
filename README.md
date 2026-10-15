# tiktok-ecommerce-agent

TikTok 日本站床上用品卖家的选品工具。从竞品采集、评论分析、国内货源匹配到上架素材生成，一条命令跑完；网页端提供聊天界面，直接对话使用。

## 功能

- **选品分析**：抓取 TikTok Shop 日本站竞品与评论，基于评论做 RAG 分析，提炼优缺点和卖点，输出 0-100 评分、市场价位和跟卖建议
- **货源匹配**：默认从找家纺网匹配国内床上用品货源，支持按图片搜款，也可切换 1688
- **上架素材**：自动生成日文标题、关键词、描述和规格翻译，可导出 TikTok 卖家中心可直接导入的 CSV，或打包 ZIP（含商品图）
- **图片处理**：商品图白底化、图上文字识别、日文翻译，支持单张和批量
- **带货脚本**：根据商品生成日文短视频口播脚本（开场钩子、卖点、结尾引导下单）
- **利润测算**：输入售价和成本，计算毛利、平台费、净利和回本件数
- **聊天界面**：Vue 前端，流式回复，登录后使用，会话历史保存在本地

## 快速开始

```bash
# 1. 创建虚拟环境并安装
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux
pip install -e ".[dev]"

# 2. 配置
copy .env.example .env          # Windows
cp .env.example .env            # macOS/Linux
# 编辑 .env，至少填入 LLM_API_KEY（对话模型）和 LLM_EMBEDDING_API_KEY（向量模型）

# 3. 启动后端
tiktok-agent serve --port 8000
# 接口文档: http://127.0.0.1:8000/docs

# 4. 启动前端（另一个终端）
cd frontend
npm install        # 首次
npm run dev        # http://localhost:5173
```

打开 http://localhost:5173，注册账号后即可使用。可以直接在聊天框输入，例如：

- `帮我分析 ボックスシーツ 冬用 能不能卖` —— 选品分析
- `找 牛奶绒床笠 四件套 的货源` —— 找货源
- `生成 牛奶绒床笠 的上架素材` —— 生成日文上架素材
- `生成 牛奶绒床笠 的带货脚本` —— 生成带货脚本
- `去1688找货源` —— 切换到 1688 找货源

非电商话题会提示不在回答范围。

## 命令行使用

```bash
# 跑完整选品流水线（日本站，日语文案）
tiktok-agent run-selection --product "純棉 ボックスシーツ 1.8m" --region "JP"

# 只跑部分阶段
tiktok-agent run-selection --product "純棉 四件套" --stages "analyzer,sourcing"

# 切换上架文案语言
tiktok-agent run-selection --product "wireless earbuds" --region "US" --language en
```

演示脚本都在 `scripts/` 下，激活 venv 后运行：

```bash
.venv\Scripts\python scripts\demo_crawlers.py    # 采集演示（样本数据）
.venv\Scripts\python scripts\demo_analyze.py     # 评论 RAG 分析
.venv\Scripts\python scripts\demo_source.py      # 货源匹配
.venv\Scripts\python scripts\demo_listing.py     # 上架素材生成
.venv\Scripts\python scripts\demo_pipeline.py    # 端到端流水线
```

验证真实数据源是否可用：

```powershell
.venv\Scripts\python scripts\verify_data_source.py
```

## 数据源

商品数据源通过环境变量切换（`PRODUCT_SOURCE`），支持：

| 数据源 | 说明 | 费用 |
|---|---|---|
| `sample` | 内置样本数据 | 免费 |
| `socialcrawl` | TikTok Shop 搜索与评论 | 1 credit/次，新号送 100 credits |
| `tikhub` | TikTok Shop 数据 | $0.001/次起 |
| `fastmoss` | TikTok Shop 数据 | $0.01/次起 |

货源数据源（`SUPPLIER_SOURCE`）：`jiafang` 为找家纺网直连（免费真实 API，默认），`1688` 为 1688 综合批发，`sample` 为内置样本。

注册和接入步骤见 [docs/HOW_TO_GET_DATA.md](docs/HOW_TO_GET_DATA.md)，各数据源能力对比见 [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)。

## 检索后端

评论入库后做向量检索，支持三种后端，通过 `RAG_BACKEND` 切换：

| 后端 | 说明 |
|---|---|
| `memory` | 内存检索，免安装，适合开发和测试 |
| `milvus` | 自建 Milvus，需要 `docker compose up -d milvus` |
| `ragflow` | 本机已运行的 RAGFlow（配置 `RAG_BASE_URL` / `RAG_API_KEY` / `RAG_DATASET`） |

## 语言与品类

默认面向 TikTok 日本站，上架文案（标题、关键词、描述）默认用日语生成，贴近日本买家的搜索习惯；`translated_title` 同时输出英语标题。语言在 `src/tiktok_ecommerce/i18n/languages.py` 注册，新增语言只需在注册表加一行。

默认品类是床上用品，内置面料、尺寸、日美欧规格等领域知识，并带电子产品和服装两个示例品类。品类在 `src/tiktok_ecommerce/categories/` 下注册，支持自定义。

## 架构

```
Entry: CLI (click) / REST API (FastAPI /api/v1) / Vue 前端
  ↓
Pipeline: LangGraph 状态机
  crawler_agent → analyzer_agent → sourcing_agent → listing_agent
  可切换串行 / Supervisor 并行（分析 ∥ 货源预搜）
  ↓
Layers:
  crawlers/          采集层（TikTok / 找家纺网 / 1688，HTTP 重试限速）
  rag/               检索层（VectorStore 接口，Milvus / RAGFlow / memory 实现）
  agents/            Agent 层（BaseAgent 抽象 + 4 个业务 Agent）
  services/          业务服务（评分、市场分析、关键词、利润、生命周期）
  image_processing/  图片处理（白底化 / OCR / 翻译）
  api/               FastAPI v1
Cross-cutting: config (pydantic-settings) / logging / exceptions / models (Pydantic v2)
```

完整设计见 [docs/architecture.md](docs/architecture.md)。

## 开发与测试

```bash
make lint        # ruff 检查
make type        # mypy 类型检查
make test        # pytest 单元测试（316 项）
make test-int    # 集成测试（需要真实依赖）
make run         # 本地跑一次流水线
make serve       # 启动 API
```

## License

MIT，见 [LICENSE](LICENSE)。
