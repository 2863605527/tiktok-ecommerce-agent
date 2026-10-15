# 真实数据落地手册（怎么获取数据 + 花多少钱 + 操作步骤）

> 本文是"数据从哪来、怎么付费、怎么配置"的操作手册，
> 覆盖商品/评论/货源三条数据链路，价格与端点均来自官方页面实测。
> 最后更新：2026-10-13

---

## 一、两条数据线，三种成本档位

| 数据线 | 数据源 | 成本 | 现状 |
|---|---|---|---|
| TikTok 商品/评论 | **FastMoss OpenAPI**（首选） | **$0.01/次起**，按量付费 | 已实现 `crawlers/fastmoss.py` |
| TikTok 商品/评论 | TikTok Shop 官方 TTS API | 免费但需 Partner 审核 | 长期方案，门槛高（见 §4） |
| 国内货源 | **找家纺网直连**（默认） | **免费** | 已实现 `crawlers/zhaojiafang.py`（真实 API） |
| 国内货源 | 1688（用户可选） | 免费但需登录/风控 | 扩展点，默认不可用 |
| 离线兜底 | 本地样本 `data/samples/` | 免费 | 默认开启，任何环境可跑通 |

**一句话**：货源免费（找家纺网真实 API 已跑通）；TikTok 商品/评论按量付费（FastMoss 最便宜，
一个完整选品流程约 $0.05≈¥0.4）。

---

## 二、找家纺网货源（免费，已真实跑通）

### 2.1 说明
找家纺网（www.zhaojiafang.com）是南通叠石桥家纺产地的垂直货源平台，
提供公开搜索 API（前后端分离，数据 JSON 返回）：按关键词返回**店铺 + 主营 + 推荐商品**
（商品标题/价格/销量 + 店铺是否一件代发），无需登录、无需付费。

### 2.2 使用
```powershell
# 1. 切到真实货源源（只改 .env 一行）
# 把 .env 里 SUPPLIER_SOURCE=sample 改为：
SUPPLIER_SOURCE=jiafang

# 2. 验证真实连通（免费，真实调用找家纺 API）
python scripts\verify_data_source.py

# 3. 跑全流程（商品用样本、货源用真实找家纺）
python scripts\demo_pipeline.py
```

### 2.3 注意事项（合规）
- 频率礼貌：代码自带限速（默认 3 秒+抖动）与 UA 轮换，只做"关键词→结果"的正常浏览级请求
- 只取公开搜索接口的数据（店铺名/商品名/价格/代发标识），不碰会员/登录数据、不批量轰炸
- 若接口改版导致解析失败，跑一次 `verify_data_source.py` 看输出即可定位

---

## 三、FastMoss（TikTok 商品/评论真实数据，按量付费）

### 3.1 为什么必须用第三方数据平台（不能自己爬 TikTok）
TikTok 商品页/评论接口有三重反爬，普通请求必被封：
1. **JS 渲染**：商品/评论是异步加载，直接 GET 拿不到内容
2. **签名体系**：所有接口要 `X-Bogus` / `msToken` / `_signature` 动态签名，需逆向或 Playwright
3. **风控升级**：设备指纹 + 滑块验证 + IP 封禁；评论接口是加密的独立接口

FastMoss 是 TikTok Shop 数据引擎（500M+ 商品、300M+ 达人、1200+ 天历史），
把这些数据做成 45+ REST 端点按量卖 —— 花小钱买到**干净、合法、稳定**的数据，比自建爬虫划算得多。

### 3.2 注册 + 拿 Key + 充值（5 步，约 10 分钟）

1. **注册账号**：打开 https://openapi.fastmoss.com 或 https://developers.fastmoss.com → Sign up
   （邮箱注册即可，不需要企业资质）
2. **创建 Key**：登录后进 **Console（控制台）→ API Keys / client_secret** → Create，
   复制生成的 `client_secret`（这就是我们的 `THIRD_PARTY_PRODUCT_API_KEY`）
3. **申请试用（可选）**：官方首页有 **Apply Trial** 入口，MCP/CLI 有 3 天免费试用；
   REST 按量计费，充小额即可（见下）
4. **充值**：Console → Billing / Top-up，按量充（额度以 $ 计，充 $10 足够跑 1000+ 次调用）
   - 计费规则（官方原话）：每调用 $0.01 起；`pagesize>10` 按 `ceil(pagesize/10)` 倍数扣额度；
     **空结果不计费**
   - 会员套餐（可选）：MCP/CLI Basic $16/月、Pro $49/月、Max $109/月；
     平台会员 Ultimate $99/月（含排行榜等增值）
5. **配置 .env**：
   ```ini
   PRODUCT_SOURCE=fastmoss
   THIRD_PARTY_PRODUCT_API_BASE=https://openapi.fastmoss.com
   THIRD_PARTY_PRODUCT_API_KEY=粘贴你的client_secret
   FASTMOSS_REGION=JP        # TikTok 日本站
   ```

### 3.3 验证 + 成本估算
```powershell
# 验证真实连通（消耗约 $0.01）
python scripts\verify_data_source.py --fastmoss
```

| 场景 | 调用次数 | 费用 |
|---|---|---|
| 搜一个关键词（10 条） | 1 次 | ≈ $0.01 |
| 一个完整选品（搜索 2 词 + 3 个商品评论各 1 次） | 5 次 | ≈ $0.05（¥0.4） |
| 每天 20 次选品 | 100 次 | ≈ $1/天（¥7） |
| 一个月 20 天×20 次 | 2000 次 | ≈ $20（¥140） |

> 对比：Kalodata 等订阅制平台（¥几百/月起）只给 Web 看板不开放 API；
> FastMoss 按调用付费，**用多少花多少**，最适配"工具型项目"。

### 3.4 已实现的接口（官方文档核实）
- `POST /product/v1/search`：关键词/区域/价格区间/类目筛选 + 按 7 天销量/GMV 排序 → 商品列表
- `POST /product/v1/reviewList`：按 `product_id` 拉评论（评分降序，含内容/点赞/时间）
- `POST /product/v1/rank/topSelling`：热销榜（可用于选品方向，后续可加）

---

## 四、TikTok Shop 官方 TTS API（长期正规方案，门槛高）

- 文档：https://partner.tiktokshop.com/docv2
- 面向**开发者应用**：需 Partner Center 申请（选业务类目 → 提交 App Requirement Document →
  审核）→ 卖家 OAuth 授权后才可调
- 2026 年已更新日本市场 Products/Orders/Logistics/Customer service API
- 价值：能拿到**自己店铺**的订单/商品/物流数据（适合后续做"自动上架/订单处理"）
- 结论：不是"今天就能接"的路径；作为"未来扩展"方向即可，数据主体仍用 FastMoss

---

## 五、FastMoss 之外的方案对比（2026-10 调研）

除 FastMoss 外，能拿 **TikTok Shop 商品 + 评论** 的第三方数据服务（均为按量/订阅付费，
无需官方开发者账号）：

| 方案 | 商品 | 评论 | 价格（起步） | 门槛 | 本项目状态 |
| --- | --- | --- | --- | --- | --- |
| **TikHub** (tikhub.io) | ✅ 搜索/详情 | ✅ 商品评论 V2（product_id + 分页，官方区域含 JP） | 新号送 $0.05，**$0.001/次**，量大 30k+/天低至 $0.0005 | 注册即可，无需开发者账号 | ✅ **已实现**（`crawlers/tikhub.py`，`PRODUCT_SOURCE=tikhub`） |
| **SocialCrawl** (socialcrawl.dev) | ✅ 搜索/商品 | ✅ Product Reviews API（评分/正文/作者/验证购买/SKU，JP 支持） | 免费 **100 credits（无信用卡）**，之后 £15/2500 credits | 注册拿 Key | ✅ **已实现**（`crawlers/socialcrawl.py`，`PRODUCT_SOURCE=socialcrawl`） |
| **EchoTik** (shaxe.echotik.live) | ✅ 全量电商数据 | ✅ 评论/互动 | API 服务订阅，会员 **$13.9/月起** | 注册 | ⏳ 可接入（接口契约未在本项目实现） |
| **FastMoss**（当前默认实现） | ✅ | ✅ | $0.01/调用 起（pagesize>10 按倍率） | 注册+充值 | ✅ 已实现（`crawlers/fastmoss.py`，`PRODUCT_SOURCE=fastmoss`） |
| **Kalodata** (kalodata.com) | ✅ Web 看板 | ✅ Web 看板 | **$69.9/月** 起 | 登录墙 | ❌ 无公开 API 证据，不推荐做工程对接 |
| **镜海数据** (jhzyapi.com) | ✅ 27 个接口含 Shop 搜索/详情 | ✅ Shop 评论 | 按成功调用计费 | 注册 | ⏳ 可接入 |
| **八爪鱼 Data Hub** | 模板采集 | ✅ TikTok Shop 评论模板 | 按条计费 | 美区为主 | ⏳ 一次性导出，非 API 对接 |

**推荐路线（三个源都可切换）**：
1. **免费验证**：`PRODUCT_SOURCE=socialcrawl` —— 注册拿 100 免费 credits（无信用卡），
   `python scripts\verify_data_source.py --socialcrawl` 验证真实商品/评论链路
2. **日常批量**：`PRODUCT_SOURCE=tikhub` —— $0.001/次（比 FastMoss 便宜约 10 倍）；
   ⚠️ TikHub 搜索官方区域未列 JP，**日本站评论用 TikHub、搜索建议 socialcrawl/fastmoss**
3. **日本站主力**：`PRODUCT_SOURCE=fastmoss`（region=JP）或 socialcrawl（region=JP 官方支持）
4. 代码衔接：三个客户端同为 `ProductCrawler` 接口（search_products/fetch_reviews），
   工厂在 `crawlers/factory.py` 按 `PRODUCT_SOURCE` 一行切换，业务代码零改动。

---

## 六、常见问题

**Q：为什么默认还是 sample？**
A：保证任何环境（无网/无 Key）都能跑通全流程。切真实数据只改 `.env` 两行，`verify_data_source.py`
验证连通后再切。

**Q：找家纺网能拿到什么字段？**
A：店铺名、主营、地址、是否一件代发（store_daifa）、店铺销量、推荐商品（标题/价格/销量）。
精确起批价需登录商家页（不在公开 API 范围），找家纺特色就是代发。

**Q：FastMoss 会不会买到假数据？**
A：平台是 TikTok 生态数据供应商（官网可查 4.7M 用户），按调用计费、空结果退款，
数据来自其自有采集管道；相比自建爬虫，稳定性和合规性都更好。重要决策前可抽样核对
`fastmoss_url` 指向的详情页。

**Q：1688 还能用吗？**
A：能。把 `SUPPLIER_SOURCE=1688` 即可切换（当前为扩展点，需自行接入 Playwright/登录态；
代码结构已预留 `crawlers/supplier.py`）。默认主推找家纺网（家纺垂直，对床品卖家更对口）。

---

## 七、把真实数据跑通的最小步骤（复制粘贴）

```powershell
cd <项目根目录>
.\.venv\Scripts\activate

# ① 货源先切真实（免费，立即生效）
#    用记事本改 .env：SUPPLIER_SOURCE=jiafang

# ② 验证找家纺网真实连通
python scripts\verify_data_source.py

# ③ 商品也切真实（需先按 §3.2 拿 Key 充值）
#    改 .env：PRODUCT_SOURCE=fastmoss + THIRD_PARTY_PRODUCT_API_KEY=...
python scripts\verify_data_source.py --fastmoss

# ④ 全流程真实跑一遍
python scripts\demo_pipeline.py
```
