# tiktok-ecommerce-agent

> TikTok 跨境选品与上架全链路多 Agent 系统 —— 企业级工程框架。

面向 TikTok 跨境自营店铺的内部提效工具：打通「竞品采集 → RAG 商品分析 → 国内货源匹配 → 上架素材自动生成」全流程，通过 LangGraph 编排 4 个 Agent 协作完成。

## 快速开始

```bash
# 1. 创建虚拟环境（推荐）
python -m venv .venv
.venv\Scripts\activate          # Windows
source .venv/bin/activate       # macOS/Linux

# 2. 安装（开发模式）
pip install -e ".[dev]"

# 3. 配置密钥
copy .env.example .env          # Windows
cp .env.example .env            # macOS/Linux
# 编辑 .env 填入 LLM_API_KEY

# 4. 启动 Milvus（需 Docker）
docker compose up -d milvus

# 5. 运行选品流水线（日本站，日语文案）
tiktok-agent run-selection --product "純棉 ボックスシーツ 1.8m" --region "JP"

# 切换上架文案语言
tiktok-agent run-selection --product "pure cotton sheet" --region "US" --language en

# 6. 启动 API 服务
tiktok-agent serve --port 8000
# 文档: http://127.0.0.1:8000/docs
# 控制台: http://127.0.0.1:8000 （品类按钮 + 阶段勾选 + 运行流水线）

# 7. 启动 Vue 3 工程化工作台（推荐日常使用，详见 docs/START_HERE.md 零基础教程）
cd frontend
npm install        # 首次
npm run dev        # http://localhost:5173 （Vite 代理 /api → 8000）

# 8. 聊天模式（豆包式电商限定对话，首页默认 · SSE 流式）
#    打开 http://localhost:5173 → 先注册/登录（用户名/邮箱/密码均有格式验证，JWT 鉴权）
#    登录后直接打字：
#    「帮我分析 ボックスシーツ 能不能卖」选品 / 「找 牛奶绒床笠 货源」/ 「生成 床笠 上架素材」
#    非电商话题 → 回复"不在回答范围"（意图路由见 src/tiktok_ecommerce/services/chat_service.py）
#    流式：POST /api/v1/chat/stream（阶段进度 + 深度思考步骤 + 完成事件）
#    左侧会话历史 localStorage 持久化；工作台运行流水线同样实时进度（/api/v1/selections/stream）
#    ── 前端工作台 v2 功能清单（2026-10）────────────────────────────
#    视觉：浅色设计系统 v2（渐变品牌点+层级阴影+滚动条/骨架屏/打字光标 token）
#    会话：搜索会话、双击重命名、导出 Markdown（复盘/交接）、时间显示
#    收藏：★ 一键收藏竞品/货源/素材（按用户隔离）→ 收藏库导出 CSV（交接运营）
#    素材：日文/英文一键复制完整 listing；价格徽章、匹配度进度条、评论情感占比条
#    图片：单图下载、批量下载全部、图片加载失败占位
#    状态：数据源状态徽章化（绿/黄状态点，点击跳数据源页）
#    快捷键：Ctrl+Enter 发送 / Ctrl+K 聚焦 / Ctrl+N 新对话
#    ── 前端工作台 v3 功能清单（第二轮 12 项提升，2026-10）──────────────
#    后端新能力：
#      · 选品结果库（SQLite saved_selections，按用户隔离，流式跑完自动存档）
#        GET/POST/DELETE /api/v1/selections/history —— 跨设备可回看
#      · 素材包 ZIP 下载（POST /api/v1/listings/package：listing.json+商品图打包，
#        RFC5987 文件名、路径穿越防护、图片下载失败跳过不阻塞）
#    前端新能力：
#      · 全局 Toast 通知（收藏/复制/导出/清空统一反馈，防"点击无反应"）
#      · 评论证据展开：RAG 洞察点击展开命中评论原文（可溯源）
#      · 定价助手：货源价格带（最低/中位/最高）+ 建议售价（成本×3 估算）
#      · 报告导出 Markdown：选品评估完整报告一键下载
#      · 失败重试：报错消息一键重新发送
#      · 批量选品：聊天/工作台输入多行商品 → 串行逐个分析（真实可用）
#      · 工作台历史面板：历史列表/回放完整结果/删除（防误触确认）
#      · 窄屏适配：<860px 侧栏抽屉式折叠（☰/✕ 开关）
#      · 图片翻译复制：单图/批量日文翻译一键复制
#      · 素材 ZIP 一键下载（工作台素材面板）
#    ── 前端工作台 v4 功能清单（第三轮 13 项提升，2026-10）──────────────
#    后端新能力：
#      · 推荐评分模型（services/scoring.py）：0-100 四维（热度/口碑/货源/上架），
#        每维带可解释 reasons，缺失字段保守给分，输出 level（强推/推荐/谨慎/观望）
#      · 市场价位分布（services/market.py）：5 档价格带 + 均价/中位/样本数，
#        样本 <3 时明确标注"样本不足"（不编造）
#      · 关键词挖掘（services/keyword_mining.py）：报告提炼/评论聚类/竞品标题命中
#        品类词三来源去重加权；来源为空时用本次检索词兜底拆词（保证面板可用）
#      · 利润测算 API（POST /api/v1/business/profit）：售价 JPY + 成本/运费 CNY
#        → 毛利/平台费/净利/净利率/广告回本件数，费率与汇率（FX_CNY_JPY=21）参数化
#      · TikTok 上架批量 CSV（POST /api/v1/listings/csv）：UTF-8 BOM 模板，
#        表头与卖家中心一致（商品名称/描述/类目/关键词/标签），可直接导入
#      · 一键诊断（GET /api/v1/diagnostics）：SocialCrawl/Milvus/找家纺网/LLM 四项
#        独立检查不互阻，用与流水线相同的工厂真实通路验证（1-2 credits/次）
#    前端新能力：
#      · 聊天推荐评分卡：圆形总分（按 level 变色）+ 4 维进度条 + 可解释理由
#      · 市场价位分布条形图 + 均价/中位参考线（ChatMessage 与报告面板一致）
#      · 关键词面板：chips 展示 + 点击复制（上架标题/搜索词直接取用）
#      · 利润卡（聊天说"这款利润多少"自动计算，支持参数如"售价3500 成本85 运费40"）
#      · 工作台利润测算器：4 输入口 + 「一键代入当前结果」（竞品最低售价/货源最低进价）
#      · 竞品勾选对比表格：≥2 项对比、最低价高亮、取消/对比按钮
#      · 素材「⇩ 上架 CSV」下载按钮（与 ZIP 并列）
#      · 「数据源与使用」页一键诊断面板：逐项状态点 + 汇总（无需翻日志）
#      · 聊天「最近分析」chips：跨会话最近 5 条选品，点击回填输入框
#    质量门：全量 pytest 294+ passed（tests/unit），前端 vue-tsc --noEmit 0 错，
#            冒烟脚本覆盖 login/profit/diagnostics/csv/完整选品流（真实 SocialCrawl）
#    ── 货源平台切换（会话级，聊天即说即切）──────────────────────────────
#    「去1688找货源」    → 会话后续货源搜索走 1688（综合批发）
#    「换回找家纺网」    → 切回默认找家纺网（家纺垂直站，免费真实 API）
#    「用1688找 牛奶绒床笠 货源」→ 切换 + 立即用目标平台搜索
#    「去其他地方找货源」→ 未点名平台时给出可选提示，不擅自切换
#    降级策略：1688 直连需登录态/开放平台 API（默认未配置）→ 自动回退找家纺网
#              并如实说明原因（不把 CrawlerError 抛给用户）；要真正接入 1688：
#              配置 .env THIRD_PARTY_SUPPLIER_API_BASE/KEY（source='api'）或
#              Playwright 登录态小量采集（source='1688'，需控频）。
#    会话上下文：同一次会话可"继续聊下去"——说「第一条货源生成素材」「这个货源多少钱」，
#    直接引用刚才的真实结果，不会重新搜索（contexts 模块级共享，见 chat_service.py）
#    竞品卡片带商品图；货源卡片带找家纺网详情超链接（detail 站，点击跳转）
#    认证：src/tiktok_ecommerce/common/security.py（scrypt 密码哈希 + 标准库 HS256 JWT）
#          src/tiktok_ecommerce/auth/store.py（SQLite 用户库，data/app.db，已 gitignore）
#          注册/登录/当前用户见 src/tiktok_ecommerce/api/v1/auth.py；chat/selection 接口均需登录

# 9. 以图找货（聊天选品自动启用，官方视觉引擎 + 本地免费兜底）
#    TikTok 商品带图 → 本地视觉特征匹配（RGB 感知哈希 192bit + 16³ 颜色直方图 +
#    HSV 主色，中心裁剪去背景干扰）先找到"最像"的国内货源款
#    → 用找家纺官方"以图搜款"接口（用户 F12 抓取，阿里云视觉引擎，ali_score 0~1）
#    以该站内款反查全平台同款供应商比价 → ali_score 高者排最前（不做六维稀释）
#    官方接口免费，token 配置：.env 里 ZHAOJIAFANG_IMAGE_SEARCH_TOKEN
#    （当前内置默认值，过期时 F12 重新抓取替换，见 docs/RUN_GUIDE.md 第 9 节）
#    实现：src/tiktok_ecommerce/crawlers/zhaojiafang.py
#          search_similar_by_image + _augment_with_official_image_search
#    LLM 精炼关键词无货（如"法兰绒床笠"在找家纺无货）→ 自动用品类模板词兜底重试

# 10. 商品图片优化工作台（http://localhost:5173/images · 上架刚需）
#    上架最头疼的商品图：规格化（白底/目标比例/压缩）+ 图上文字识别 + 日文翻译 + 上架建议
#    - 输入：商品图 URL（TikTok 竞品图 / 找家纺货源图），单图 + 批量（1~20 张并发）双通道
#    - 处理：等比缩放 → 目标比例白边填充（1:1/3:4/4:3/9:16/16:9）→ 背景白底化
#      白底双模式：ai=AI 智能抠图（rembg U2-Net 本地离线，u2netp 已内置，阴影/渐变/灰底都能去）
#                 heuristic=快速启发式去底（角部采样+阈值，适合干净浅色底，AI 失败自动回退）
#    - OCR：本地 RapidOCR（ONNX 实现，CPU 稳定、离线免费、中文准），PaddleOCR 兜底
#    - 翻译：DeepSeek（现有对话模型，不新增费用）逐条图上中文 → 日文
#    - 输出：处理后图片（/static/images/**）+ 文字清单/翻译表 + 上架建议
#    实现：src/tiktok_ecommerce/image_processing/{processor,ocr,ocr_backend}.py
#          src/tiktok_ecommerce/api/v1/images.py
#          （POST /api/v1/images/process 单图 | /process/batch 批量，均需登录）
#    OCR 引擎不可用时自动降级为"仅规格化"，主流程不阻塞
#    模型：u2netp.onnx 已内置（~/.u2net）；放置 u2net.onnx（176MB）可提精度
```

## 十步开发路线（本仓库按此交付）

| 步骤 | 内容 | 验证方式 |
|---|---|---|
| 0 | 工程骨架（src-layout/配置/异常） | `python -m pytest tests/unit -q` |
| 1 | 环境自检 healthcheck | `python scripts\healthcheck.py`（五项全绿） |
| 2 | 领域模型 + 文本工具 | 单测（text/models） |
| 3 | 采集层（sample/api/direct 可插拔） | `python scripts\demo_crawlers.py` |
| 4 | 检索层（memory/Milvus/RAGFlow 三后端） | `python scripts\demo_rag.py` |
| 5 | 分析 Agent（评论 RAG 痛点聚类+证据） | `python scripts\demo_analyze.py` |
| 6 | 货源匹配 Agent（六维打分） | `python scripts\demo_source.py` |
| 7 | 上架素材 Agent（日语文案+规格翻译+CSV） | `python scripts\demo_listing.py` |
| 8 | LangGraph 编排（阶段裁剪+错误短路） | `python scripts\demo_pipeline.py` |
| 9 | FastAPI + Web 联调 | `tiktok-agent serve` + 冒烟测试 |
| 10 | 测试/文档/工程化 | `docs/architecture.md` |

**演示脚本（都在项目根目录、激活 venv 后运行）：**

```bash
# 3. 采集演示（样本数据，日语关键词搜出竞品+货源打分）
.venv\Scripts\python scripts\demo_crawlers.py

# 4. 检索演示（先跑一次入库，再用日语提问语义检索；后端可切换）
$env:RAG_BACKEND='memory'; .venv\Scripts\python scripts\demo_rag.py      # 免安装
$env:RAG_BACKEND='milvus';  .venv\Scripts\python scripts\demo_rag.py      # 需 docker compose up -d milvus
$env:RAG_BACKEND='ragflow'; .venv\Scripts\python scripts\demo_rag.py      # 需本机 RAGFlow（v0.27）

# 5. 评论 RAG 分析（多主题检索 → 痛点聚类 + 证据）
.venv\Scripts\python scripts\demo_analyze.py

# 6. 货源匹配（六维打分：标题/价格/起批/发货/日文规格/背书）
.venv\Scripts\python scripts\demo_source.py

# 7. 上架素材（日语文案 + 规格翻译 + JSON/CSV 输出到 output/listings/）
.venv\Scripts\python scripts\demo_listing.py

# 8. 端到端流水线（一键全流程，支持 --stages 裁剪）
.venv\Scripts\python scripts\demo_pipeline.py
.venv\Scripts\python scripts\demo_pipeline.py --stages crawler,analyzer,listing

# 9. 服务
tiktok-agent serve --port 8000     # 浏览器打开 http://127.0.0.1:8000
```

**数据从哪来？** 见 [docs/HOW_TO_GET_DATA.md](docs/HOW_TO_GET_DATA.md)（真实数据落地手册：
找家纺网免费直连已跑通 + FastMoss 按量付费接入步骤 + 成本估算）与
[docs/DATA_SOURCES.md](docs/DATA_SOURCES.md)（样本→第三方 API→扩展点，以及"为什么 TikTok 不能直连爬"）。

**快速验证真实数据（10 秒）：**
```powershell
# 免费验证找家纺网真实货源（无需任何 Key）
.venv\Scripts\python scripts\verify_data_source.py
# 加测 FastMoss 商品接口（需已按手册注册充值，消耗约 $0.01）
.venv\Scripts\python scripts\verify_data_source.py --fastmoss
```

## 语言体系（默认日语，可扩展）

项目以 **TikTok 日本站为主**：上架文案（标题/关键词/描述）默认用**日语**生成，
贴近日本买家搜索习惯（天然素材、接触冷感、防ダニ、洗える等家纺习惯词）；
`translated_title` 额外输出一份英语标题供多语言店铺参考。

语言注册表在 `src/tiktok_ecommerce/i18n/languages.py`：

```bash
# 默认日语（ja），无需指定
tiktok-agent run-selection --product "純棉 ボックスシーツ 1.8m" --region "JP"

# 切换其他语言（英语/西语/法语/德语/韩语）
tiktok-agent run-selection --product "wireless earbuds" --region "US" --language en

# API：POST /api/v1/selections  body 加 "language": "ja|en|es|fr|de|ko"
# Web：http://127.0.0.1:8000  「上架文案语言」下拉框（日语默认）
```

新增语言 = 在 `LANGUAGES` 字典加一行，CLI / Web 下拉自动出现该语言选项，无需改业务代码。

## 架构

```
┌─────────────────────────────────────────────────────────────┐
│  Entry: CLI (click) / REST API (FastAPI /api/v1)            │
├─────────────────────────────────────────────────────────────┤
│  Pipeline: LangGraph 状态机                                  │
│    crawler_agent → analyzer_agent → sourcing_agent → listing_agent │
├─────────────────────────────────────────────────────────────┤
│  Layer:                                                      │
│    crawlers/  采集层（接口 + TikTok/1688 实现 + HTTP 重试限速）  │
│    rag/       检索层（VectorStore 接口 + Milvus 实现 + Retriever）│
│    agents/    Agent 层（BaseAgent 抽象 + 4 个业务 Agent）       │
│    services/  业务服务层（报告落盘等）                          │
│    image_processing/  图片处理层                              │
├─────────────────────────────────────────────────────────────┤
│  Cross-cutting: config(pydantic-settings) / logging(JSON)    │
│  / exceptions(统一异常体系) / models(Pydantic v2)             │
└─────────────────────────────────────────────────────────────┘
```

## 目录结构

```
tiktok-ecommerce-agent/
├── pyproject.toml              # 依赖与工程配置（替代 requirements.txt）
├── Makefile                    # 常用命令入口
├── .pre-commit-config.yaml     # 提交前质量检查
├── docker-compose.yml          # Milvus / 应用编排
├── Dockerfile                  # 应用镜像
├── src/tiktok_ecommerce/       # 主包（src layout）
│   ├── config.py               # pydantic-settings 配置
│   ├── models/                 # Pydantic 领域模型
│   ├── common/                 # 日志/异常/LLM/文本工具
│   ├── crawlers/               # 采集层
│   ├── rag/                    # 检索层
│   ├── agents/                 # Agent 层
│   ├── services/               # 业务服务层
│   ├── pipelines/              # LangGraph 编排
│   ├── image_processing/       # 图片处理
│   └── api/                    # FastAPI（v1 版本化）
├── tests/                      # unit / integration 分层
├── scripts/                    # 运维脚本
├── docs/                       # 设计文档
├── data/ raw|processed|vectors
├── output/ reports|listings
└── logs/
```

## 品类体系（可扩展）

项目默认主推 **床上用品（家纺）**，内置面料/支数/规格/日美欧尺寸体系等完整领域知识；同时内置电子产品、服装两个示例品类，并支持自定义。

**品类过滤（默认只找本品类商品）**：用户聊天时未指定品类，采集到的竞品会按当前品类判定词（`category_markers`，中日英标题命中任一即通过）过滤。泛问如"日本冬天有什么好卖"搜到靴子/电暖夹克等非家纺 → 如实剔除并提示"搜到的都不是床上用品，建议明确家纺品名"，绝不把非本品类商品当结果（数据真实性原则）。切换品类后按对应品类过滤。

```bash
# 默认品类就是床上用品（日本站，日语文案）
tiktok-agent run-selection --product "純棉 ボックスシーツ 1.8m" --region "JP"

# 切换品类
tiktok-agent run-selection --product "无线耳机" --category electronics

# 只跑部分阶段（阶段可裁剪）
tiktok-agent run-selection --product "純棉 四件套" --stages "analyzer,sourcing"

# 浏览器控制台（品类按钮 + 语言选择 + 阶段勾选）
tiktok-agent serve --port 8000   # 打开 http://127.0.0.1:8000
```

新增品类 = 继承 `CategoryProfile` 写一个配置类 → 在 `categories/registry.py` 注册，CLI 与 Web 按钮自动出现该品类选项。

## 开发流程

```bash
make lint        # ruff 检查 + 格式化
make type        # mypy 类型检查
make test        # pytest 单测
make test-int    # 集成测试（需真实依赖）
make run         # 本地跑一次流水线
make serve       # 启动 API
```

详见 [docs/architecture.md](docs/architecture.md) 和 [docs/development.md](docs/development.md)。

## 多 Agent 编排（Supervisor 并行）

本仓库提供**两种编排模式**，产物完全等价，调度不同：

| 模式 | 调度 | 适用 |
|---|---|---|
| 串行 LangGraph（默认，`parallel=False`） | crawler → analyzer → sourcing → listing 链式 | 阶段裁剪、逐步调试 |
| **Supervisor 并行（`parallel=True`，聊天默认启用）** | Phase1 crawler → Phase2 **analyzer ∥ sourcing.pre_search 并行** → Phase3 refine_merge → listing | 真实选品（提速明显） |

并行依据：RAG 评论分析（LLM 慢）与货源搜索（真实网络请求 + 以图找货视觉，也慢）**互不依赖**，
串行被排队 = 耗时相加；并行后总耗时 ≈ 最慢阶段。实现见
`src/tiktok_ecommerce/orchestrator/supervisor.py`（ThreadPoolExecutor 并行分发 + 聚合，
短路规则与串行一致：无商品→结束；无报告→保留预搜货源但不编造关键词、跳过素材）。

```python
# 代码路径（聊天服务默认已开）
result = pipeline.run(query=..., region="JP", parallel=True)
```

## 诚实边界

- 内部自用工具，本地/小流量运行，不做商用并发承诺
- 货源匹配给出匹配分数，**最终由人工复核**，不直接下单采购
- 生成的标题/图片是初稿，人工微调后上架

## v6 增强（2026-10 · 深度审计 + 市面对标轮）

**安全加固（真实修复）**
- 会话上下文**按用户隔离**（`_SHARED_CONTEXTS` key 带 user_id：两用户同 conversation_id 不串数据）+ 容量上限 500（防内存膨胀）
- **注册限流**：同 IP 每小时 ≤5 新账号（登录已有 5 次失败锁 15 分钟）
- 图片接口 SSRF 防护（`common/net.py` 公共模块：listings/images 两处共用，拒绝内网/回环/云元数据地址）
- CSV 公式注入转义（`= + - @` 前缀）；找家纺图搜 token 移入 `.env`（源码零硬编码）

**新功能（对标市面项目落地）**
- **带货视频脚本**（对标 `vanszs/tiktok-viral-factory`）：聊天说「生成 X 的带货脚本」→ LLM 生成日文 30-45 秒口播（开场钩子/卖点/CTA），流式输出
- **导出前预览门控**（对标 Anthropic `commerce-agents` merchant 人工批准模式）：下载 ZIP/CSV 前弹窗预览标题/关键词/描述/规格，确认后才下载
- **生命周期+进场时机**：竞品评论时间序列 → 萌芽/成长/爆款/衰退四阶段 + 跟卖窗口建议；评分卡新增"进场时机"旁路维度
- **RAGFlow 诊断项**：一键诊断覆盖 ragflow 后端（真实混合检索验证知识库）
- 找家纺搜索 TTL 缓存（10 分钟，省请求提速）

**市面对标结论**（详见 docs/COMPARISON.md）
- 已覆盖 Anthropic commerce-agents 的选品分析能力，且多了评论 RAG/货源匹配/生命周期
- 已覆盖 scout-cli 的 TikTok Shop + 1688 货源核心；FastMoss skills 的跟卖窗口已落地
- 待扩展：达人建联（outreach-bot）、TikHub 批量源实测（填 key 即用）

**质量门**：全量 pytest **308+ passed**、vue-tsc 0 错、诊断 5/5 全绿、真实浏览器端到端验证货源排序修复。

## 执照与提交

- LICENSE：MIT（见仓库 LICENSE 文件）
- 密钥保护：`.env` / `data/app.db`（含密码哈希）/ `output/**` 均已被 `.gitignore` 排除；`.env.example` 仅含占位符
- 变更历史：CHANGELOG.md
- 底层大模型走第三方 API，本项目做 **Agent 编排 + RAG + 数据处理 + 流程串联**
