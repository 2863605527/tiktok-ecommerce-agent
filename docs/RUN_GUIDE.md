# 启动与操作指南

本文档教你如何把项目跑起来并完成一次真实选品。全程 3 个窗口：**后端**、**前端**（可选）、**操作入口**。

---

## 0. 前置检查（一次性）

```powershell
# 项目根目录
cd F:\AI学习\简历项目\tiktok-ecommerce-agent

# 1. 激活 Python 虚拟环境
.\.venv\Scripts\activate

# 2. 检查 .env 配置（记事本打开）
#    - LLM_API_KEY / EMBEDDING_API_KEY 已填真实 Key（你已配置，healthcheck 全绿）
#    - RAG_BACKEND=milvus（已用 docker compose up -d milvus 启动）或 ragflow
#    - SUPPLIER_SOURCE=jiafang  ← 找家纺网真实货源（免费）
#    - PRODUCT_SOURCE=sample    ← TikTok 商品先用样本，配 FastMoss Key 后改 api

# 3. 一键验证环境 + 真实数据链路
python scripts\healthcheck.py      # 模型/向量库连通性
python scripts\verify_data_source.py  # 找家纺网真实货源连通性
```

---

## 1. 三种使用方式（任选一种）

### 方式 A：命令行（最快，不用浏览器）

```powershell
python scripts\demo_pipeline.py
```

输出：采集竞品 → 评论 RAG 分析 → 找家纺网货源匹配 → 日文上架素材（CSV 落在 `output/listings/`）。

### 方式 B：后端自带的 Web 控制台（FastAPI 内嵌页）

```powershell
python -m uvicorn tiktok_ecommerce.api.app:create_app --factory --port 8000
```

浏览器打开 **http://localhost:8000** —— 品类按钮 + 阶段勾选 + 运行流水线。

### 方式 C：Vue 3 工程化工作台（推荐日常使用）

开两个终端：

```powershell
# 终端 1：后端（保持运行）
.\.venv\Scripts\activate
python -m uvicorn tiktok_ecommerce.api.app:create_app --factory --port 8000

# 终端 2：前端
cd frontend
npm install          # 首次执行
npm run dev          # 开发服务器
```

浏览器打开 **http://localhost:5173**（Vite 已代理 `/api` → 后端 8000，无需配跨域）。

工作台功能：
- **数据源状态条**：实时显示商品/货源数据源、检索后端、FastMoss Key 是否配置
- **品类按钮**：床上用品（主推）/ 电子 / 服装 —— 可扩展体系
- **阶段勾选**：采集 / 分析 / 货源 / 素材，可裁剪
- **结果面板**：竞品列表（含评论）→ 评估报告（痛点聚类+证据）→ 货源对比（六维打分）→ 日文素材包

---

## 2. 后端怎么启动（最详细）

后端就是 FastAPI 服务（端口 8000），前端（Vue）只是它的操作界面。

```powershell
# 终端 1：启动后端
cd F:\AI学习\简历项目\tiktok-ecommerce-agent
.\.venv\Scripts\activate                          # 激活虚拟环境
python -m uvicorn tiktok_ecommerce.api.app:create_app --factory --port 8000
```

看到 `Uvicorn running on http://127.0.0.1:8000` 就是启动成功。
自检：浏览器打开 http://localhost:8000/docs（API 文档）或 http://localhost:8000/health（返回 `{"status":"ok"}`）。

> 注意：`--factory` 必须带上（应用是工厂函数 create_app），
> 不带会报 `Failed to find application`。
> 停后端：在终端按 `Ctrl+C`。

## 3. 前端怎么启动（可选）

```powershell
# 终端 2：前端（另开一个终端）
cd F:\AI学习\简历项目\tiktok-ecommerce-agent\frontend
npm install          # 首次执行（已装过可跳过）
npm run dev          # 开发服务器
```

浏览器打开 **http://localhost:5173**（Vite 已代理 `/api` → 后端 8000，无需配跨域）。
只想要命令行/自带控制台就不用开前端（见方式 A/B）。

## 4. 三种使用方式（任选一种）

### 方式 A：命令行（最快，不用浏览器）

```powershell
python scripts\demo_pipeline.py
```

输出：采集竞品 → 评论 RAG 分析 → 找家纺网货源匹配 → 日文上架素材（CSV 落在 `output/listings/`）。

### 方式 B：后端自带的 Web 控制台（FastAPI 内嵌页）

后端启动后打开 **http://localhost:8000** —— 品类按钮 + 阶段勾选 + 运行流水线。

### 方式 C：Vue 3 工程化工作台（推荐日常使用）

按上面第 2、3 节启动两个终端后，打开 **http://localhost:5173**。

**💬 首页 = 电商聊天模式（豆包式 + SSE 流式）**：
- 直接打字：「帮我分析 ボックスシーツ 冬用 能不能卖」「找 牛奶绒床笠 货源」「生成 法兰绒床笠 上架素材」
- **流式输出**：回复像大模型一样逐字打出；重活（选品流水线）先实时推送阶段进度
  （正在采集竞品 → 正在分析评论 → 正在匹配货源 → 正在生成素材），完成后才出卡片
- **左侧会话历史**：新对话 / 切换 / 删除，localStorage 本地持久化，刷新不丢
- 聊天回复带结构化卡片（真实竞品 / 评估报告 / 货源表 / 日文素材）
- **只聊商品/电商话题**：天气、八卦、代码等 → 回复"我是TikTok电商选品助手……不在回答范围"
- 意图路由在 `src/tiktok_ecommerce/services/chat_service.py`（规则引擎，中文+日文，可单测）
- 流式实现：后端 `POST /api/v1/chat/stream`（SSE，LangGraph `graph.stream` 逐阶段回调 +
  后台线程进度队列 + 打字机切块），前端 `frontend/src/stores/chat.ts` 用 fetch ReadableStream 消费

工作台功能（顶部导航「选品工作台」，浅色主题）：
- **数据源状态条**：实时显示商品/货源数据源、检索后端、各平台 Key 是否配置
- **品类按钮**：床上用品（主推）/ 电子 / 服装 —— 可扩展体系
- **阶段勾选**：采集 / 分析 / 货源 / 素材，可裁剪
- **运行进度**：点「运行流水线」后实时显示当前阶段（SSE：`POST /api/v1/selections/stream`），
  采集 → 分析 → 货源 → 素材逐步打勾，不再是"点了没反应"
- **结果面板**：竞品列表（含评论）→ 评估报告（痛点聚类+证据）→ 货源对比（六维打分）→ 日文素材包

---

## 5. 切换到真实 TikTok 商品数据（三选一，一键切换）

默认 `PRODUCT_SOURCE=sample`（内置样本，零成本跑通全流程）。三种真实源改 `.env` 一行即可：

| 源 | .env 设置 | 花多少钱 | 适合 |
| --- | --- | --- | --- |
| **SocialCrawl**（免费验证） | `PRODUCT_SOURCE=socialcrawl` + `SOCIALCRAWL_API_KEY=...` | **0 元**（新号送 100 credits） | 先免费验证真实数据链路 |
| **TikHub**（日常批量） | `PRODUCT_SOURCE=tikhub` + `TIKHUB_API_KEY=...` | $0.001/次（新号送 $0.05） | 日常批量采集 |
| **FastMoss**（日本站主力） | `PRODUCT_SOURCE=fastmoss` + `THIRD_PARTY_PRODUCT_API_KEY=...` | $0.01/次 | 日本站（region=JP） |

**注册拿 Key（都是 1 分钟级）：**
- SocialCrawl：https://www.socialcrawl.dev 注册 → Dashboard 生成 `x-api-key`（无需信用卡）
- TikHub：https://tikhub.io 注册 → https://user.tikhub.io/dashboard/api 生成 Bearer Token（送 $0.05）
- FastMoss：https://developer.fastmoss.com 注册 → Console 创建 client_secret

**验证 + 切换步骤：**
```powershell
# ① 记事本打开 .env，填好上面的 Key 并改 PRODUCT_SOURCE

# ② 一键验证真实连通（用哪个源就带哪个参数）
python scripts\verify_data_source.py --socialcrawl     # SocialCrawl（消耗 1 credit）
python scripts\verify_data_source.py --tikhub          # TikHub（消耗约 $0.001）
python scripts\verify_data_source.py --fastmoss        # FastMoss（消耗约 $0.01）

# ③ 重启后端（Ctrl+C 停掉再重新启动），工作台数据源状态条即变为对应真实源
```

> ⚠️ 日本站注意：SocialCrawl/FastMoss 搜索都支持 JP；TikHub 搜索官方区域未列 JP
> （但评论 V2 含 JP）——日本站批量场景推荐 FastMoss 或 SocialCrawl 搜索 + TikHub 评论。

---

## 6. 日常操作闭环（真实使用场景）

1. **日本站选品**：工作台输入关键词（如 `純棉 ボックスシーツ 1.8m`），品类=床上用品、区域=JP、语言=日本語
2. **看竞品**：哪个卖爆（销量）？评论在夸什么/骂什么（RAG 聚类出痛点证据）？
3. **找货源**：匹配度最高的找家纺网商家 → 价格/起批/发货时效对比
4. **上架**：复制日文标题/描述/关键词/规格翻译 → 直接粘到 TikTok Shop 后台
5. **反哺供应链**：评论里集中的痛点（如"洗后缩水"）→ 找货源时要求对应规格/工艺

---

## 7. 常用命令速查

| 目的 | 命令 |
| --- | --- |
| 环境自检 | `python scripts\healthcheck.py` |
| 真实数据源验证 | `python scripts\verify_data_source.py` |
| 命令行全流程 | `python scripts\demo_pipeline.py` |
| 启动后端 | `python -m uvicorn tiktok_ecommerce.api.app:create_app --factory --port 8000` |
| 启动前端(dev) | `cd frontend; npm run dev` |
| 前端类型检查 | `cd frontend; npm run typecheck` |
| 前端生产构建 | `cd frontend; npm run build` |
| 跑全部单测 | `python -m pytest tests/unit --no-cov -q` |
| API 文档 | http://localhost:8000/docs |

---

## 8. 常见问题

**Q: 工作台打不开？**
后端没启动（先起 8000）或前端端口被占（`npm run dev` 报 EADDRINUSE 就换 `npm run dev -- --port 5174`）。

**Q: 运行后显示"本地样本"而不是真实数据？**
`.env` 里 `PRODUCT_SOURCE=socialcrawl/tikhub/fastmoss`（任选一种真实源，需对应 Key）或 `SUPPLIER_SOURCE=jiafang`（免费，立刻有真实货源）。改完重启后端。

**Q: RAG 报错连不上 Milvus？**
确认 `docker compose up -d milvus` 已执行；或改 `RAG_BACKEND=memory`（无向量库也能跑，功能略减）。

**Q: 想换品类/语言/平台？**
品类：工作台按钮或 `GET /api/v1/categories`；语言：工作台下拉（ja 默认）；平台扩展点在 `src/tiktok_ecommerce/crawlers/factory.py`。

## 9. 官方"以图搜款"（找家纺视觉引擎，免费）

选品时自动执行两级图搜：
1. **本地视觉**（免费）：TikTok 商品图 vs 找家纺候选货源图，感知哈希+颜色直方图，
   先找到"最像"的国内货源款（限速 0.3s/图，合规）
2. **官方视觉增强**：用该站内款图调找家纺官方接口
   `POST /api/search/search_by_image`（阿里云视觉引擎，`ali_score` 0~1 高度相似），
   反查全平台同款供应商比价，`ali_score` 高者排最前

- 官方接口免费，无需 Key，仅需一个鉴权 token（站内图搜页 F12 抓取，见请求 URL 的 `token=` 参数）
- token 默认已内置；**过期/失效时**（图搜返回空）重新抓取：
  打开找家纺网「以图搜款」→ F12 → Network → 上传一张图触发搜索 → 复制
  `search_by_image` 请求 URL 里的 `token=xxx` → 粘贴进 `.env` 的
  `ZHAOJIAFANG_IMAGE_SEARCH_TOKEN=` 后重启后端
- 诚实边界：官方接口只处理找家纺站内图（`imgniu.zhaojiafang.com`）；TikTok 外站图
  直接传会返回空——所以先本地视觉拿到站内款，再交给官方引擎（两级链路的设计原因）
- 实现：`src/tiktok_ecommerce/crawlers/zhaojiafang.py`
  （`search_similar_by_image` / `_augment_with_official_image_search` / `_clean_image_url`）

