# 市面竞品对比（2026-10）

本项目（tiktok-ecommerce-agent）与 GitHub 上主流开源项目的横向对比与借鉴结论。
对比对象：Anthropic `commerce-agents`、`vanszs/tiktok-viral-factory`、
`zeeshanahmad4/tiktok-shop-affiliate-outreach-bot`、`fariz-fadian/scout-cli`。

## 一、能力矩阵

| 能力 | 本项目 | commerce-agents (Anthropic) | tiktok-viral-factory | scout-cli | outreach-bot |
|---|---|---|---|---|---|
| 商品/评论真实采集 | ✅ SocialCrawl/TikHub/FastMoss 可插拔 | ✅ 自研 shopping agent | ❌ 只生成视频 | ✅ TikTok Shop + 1688 | ❌ |
| 评论 RAG 分析 | ✅ Milvus/RAGFlow/内存三后端 | ⚠️ 无 RAG，规则+LLM | ❌ | ❌ | ❌ |
| 货源匹配 | ✅ 找家纺网（免费真实）+1688 可切 | ❌（面向买家用） | ❌ | ✅ 1688 比价 | ❌ |
| 日文上架素材 | ✅ 标题/关键词/描述/规格翻译 | ❌ | ❌ | ❌ | ❌ |
| 图片处理（白底/OCR/翻译） | ✅ 独立工作台 | ❌ | ❌ | ❌ | ❌ |
| 带货视频脚本 | ✅ v0.6 新增 | ❌ | ✅ 全自动生成+发布 | ❌ | ❌ |
| 写操作人工批准 | ✅ 导出预览门控（v0.6） | ✅ merchant agent 批准模式 | ❌ | ❌ | ❌ |
| 达人建联 | ❌（待扩展） | ❌ | ✅ | ❌ | ✅ |
| 生命周期/跟卖窗口 | ✅ 萌芽/成长/爆款/衰退 | ❌ | ❌ | ⚠️ FastMoss 数据带趋势 | ❌ |
| 鉴权/用户隔离 | ✅ JWT+scrypt+会话隔离 | ❌ | ❌ | ❌ | ❌ |

## 二、借鉴落地点（已实现）

1. **人工批准门控**（来自 commerce-agents merchant agent）：下载 ZIP/CSV 前先弹预览确认。
2. **带货视频脚本生成**（来自 tiktok-viral-factory）：聊天一句"生成 X 的带货脚本"出日文口播。
3. **数据源可插拔**（来自 scout-cli）：PRODUCT_SOURCE 一键切 sample/fastmoss/socialcrawl/tikhub。

## 三、待扩展方向（按价值排序）

1. **达人建联模块**（对标 outreach-bot）：竞品视频 → 达人主页/联系方式/合作模板，
   帮卖家做 TikTok Shop 联盟营销。落地成本：一个 crawler + 一个 chat 意图 + 一张卡片。
2. **TikHub 批量源实测**：填 key 即用（.env TIKHUB_API_KEY），搜索 V1 无 JP 区域时
   自动回退 socialcrawl 并如实提示。
3. **1688 开放平台正式接入**：source=api 配置 THIRD_PARTY_SUPPLIER_API_*（需企业资质/付费）。
4. **自动发布**（对标 viral-factory 的 MCP 发布）：风险高（平台风控），当前只出素材，
   人工上传更稳妥——这是刻意的边界，不是缺陷。

## 四、结论

本项目在"选品→分析→货源→上架素材"全链路真实数据闭环上覆盖度高于上述任一单一项目；
差距主要在达人/发布等营销侧，已在 CHANGELOG 与 README 中如实标注为待扩展。
