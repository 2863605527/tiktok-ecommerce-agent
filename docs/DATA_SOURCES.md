# 数据来源说明（DATA SOURCES）

> 本项目最常被问的问题就是「数据怎么来」。本文给出三层答案：
> 现在跑通用的是样本数据；生产用第三方数据平台 API；TikTok 直连为什么不可行。

## 1. 当前：样本数据（离线可跑，默认）

| 文件 | 内容 |
|---|---|
| `data/samples/products_jp_bedding.json` | 3 个日本站床品竞品（纯棉床笠 / 冷感垫 / 被套四件套），含日语好评/差评、规格、销量 |
| `data/samples/suppliers_jiafang_bedding.json` | 8 条找家纺风格货源（南通叠石桥、一件代发） |
| `data/samples/suppliers_1688_bedding.json` | 6 条 1688 风格货源（**可选数据源**，保留供对比） |

样本不是"假数据糊弄"，而是工程上的**数据源抽象**：与真实 API 实现同一套接口
（`ProductCrawler` / `SupplierCrawler`），因此开发、测试、CI、演示不依赖外网与反爬。

```bash
# 现在跑的就是样本源（默认）
PRODUCT_SOURCE=sample
SUPPLIER_SOURCE=sample
```

## 2. 生产：第三方数据平台 API（跨境卖家主流）

TikTok 商品与评论的**企业现实获取方式**是按接口付费的跨境数据 SaaS：

| 平台 | 说明 | 接口能力 |
|---|---|---|
| FastMoss / Kalodata / EchoTik / TikStar | 跨境卖家主流数据平台 | 商品搜索、详情、评论、达人、销量趋势 |
| TikTok Shop Open Platform | 官方开放平台 | 授权店铺后拿商品/评论/订单（Review API） |

项目已实现三个 TikTok 商品/评论客户端（同为 `ProductCrawler` 接口，可切换）：

```bash
# .env 里 PRODUCT_SOURCE 一行切换，业务代码零改动
PRODUCT_SOURCE=socialcrawl   # SocialCrawl：免费100 credits验证（搜索/评论含JP）
PRODUCT_SOURCE=tikhub        # TikHub：$0.001/次批量（评论含JP，搜索官方未列JP）
PRODUCT_SOURCE=fastmoss      # FastMoss：$0.01/次（region=JP，日本站主力）
```

通用客户端做了三件事：**字段名多候选映射**（不同平台的字段叫法不同）、
**响应包裹兼容**（data/items/results 多种结构）、**货源去重**。

## 3. 为什么不直接用 requests 爬 TikTok？

真实结论：**requests 直连爬不到** TikTok 商品与评论：

1. 全站 JS 渲染 —— 静态 HTML 里没有数据
2. 签名参数 —— X-Bogus / msToken / _signature 由客户端生成，无法伪造
3. 风控 —— 设备指纹、滑块验证、IP 封禁（日本站需要日本住宅 IP）
4. 登录墙 —— 部分接口需要登录态
5. 评论走加密接口 + cursor 分页
6. TikTok Shop 比内容端更封闭

因此直连通道（`crawlers/tiktok.py` / `supplier.py` / `zhaojiafang.py`）的定位是：
**合规扩展点**——默认抛出带指引的 `CrawlerError`，留 Playwright + 指纹 + 住宅代理的
接入位置，但不承诺稳定可用。"我调研过直连的可行性，结论是不可行，
所以把架构设计为可插拔数据源，生产走第三方 API。"

## 4. 货源：找家纺网（默认，真实 API 已跑通） + 1688（可选）

- **找家纺网**（`www.zhaojiafang.com`）：南通叠石桥家纺垂直平台（用户指定），
  提供公开搜索 API（`api-pl-mobile.zhaojiafang.com/api/store_search/store_list`），
  返回店铺 + 主营 + 推荐商品（标题/价格/代发标识）。实现：`crawlers/zhaojiafang.py`，
  无需登录、无需付费，2026-10 实测跑通。
- **1688**：可选数据源（`SUPPLIER_SOURCE=1688`），保留样本与扩展点，由使用者自行选择接入。

```bash
# 默认：家纺样本（演示用，离线）
SUPPLIER_SOURCE=sample
# 接入真实数据（免费）：
SUPPLIER_SOURCE=jiafang      # 找家纺网直连（真实 API，免费）
SUPPLIER_SOURCE=1688         # 1688直连（可选，配代理）
SUPPLIER_SOURCE=api          # 开放平台/采购 API
```

## 5. 数据流全景

```
[TikTok 商品+评论]
   sample(本地JSON) ──┐
   api(第三方SaaS) ───┼──> ProductCrawler ──> Product 模型 ──> 切片 ──> 向量库(Milvus/RAGFlow)
   direct(RPA扩展点) ─┘                                                     │
                                                                             ▼
[国内货源]                                              Retriever 日语语义检索
   sample(家纺样本) ──┐                                                     │
   jiafang(找家纺网) ─┼──> SupplierCrawler ──> SupplierOffer ──> 多维打分     ▼
   1688(可选) ────────┘                                          AnalyzerAgent 评论RAG分析
   api(开放平台) ────┘                                             │
                                                                   ▼
                                               ListingAgent 日语文案 + 规格翻译 + CSV
```
