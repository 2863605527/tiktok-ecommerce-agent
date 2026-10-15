"""找家纺网（www.zhaojiafang.com）真实货源数据源 —— 生产默认。

为什么用找家纺网：
- 同为南通叠石桥家纺产地垂直货源平台（替代 91家纺网），
  "找家纺-就上找家纺网"，床品品类全、支持一件代发、商家实名
- 提供公开 API（前后端分离，数据 JSON 返回），无需登录、无需付费，
  比解析 HTML 更稳定

真实数据链路（2026-10 实测抓取验证）：
- 搜索接口：GET https://api-pl-mobile.zhaojiafang.com/api/store_search/store_list
    ?keyword=<关键词>&page=1&pageSize=10
- 响应结构：
    {ResponseStatus: 0(=成功) / 1(空), ResponseMsg, datas: {store_data: {
        data: [{
          store_id, store_name, store_zy(主营), store_address,
          store_daifa(1=一件代发), store_sales,
          recommend: [{ goods_id, goods_name, goods_price, goods_salenum, ... }]
        }]
    }}}
- 商品详情页：https://detail.zhaojiafang.com（SPA，数据同 API 体系）

数据真实性原则：货源信息 100% 来自真实 API，LLM 只做关键词精炼与打分，
绝不生成货源数据 —— 从源头杜绝幻觉。
"""
from __future__ import annotations

import re

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.crawlers.base import SupplierCrawler
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.models.supplier import SupplierOffer

logger = get_logger(__name__)

# 找家纺网真实域名（主站 / 搜索API / 详情站）
ZHAOJIAFANG_WEB_BASE = "https://www.zhaojiafang.com"
ZHAOJIAFANG_API_BASE = "https://api-pl-mobile.zhaojiafang.com"
# 商品详情页：detail 站（用户浏览器可访问；无 cookie 爬虫会被雷池 WAF 拦 468，
# 真实用户浏览器正常）——用户期望的落地页
ZHAOJIAFANG_DETAIL_BASE = "https://detail.zhaojiafang.com"

# 床上用品类目词表（中日英）——用于"以图搜款"的语义过滤：
# 视觉相似的货源（如蓬松毛绒）可能是完全不同的子类（床垫 vs 四件套），
# 类目不一致的货源排在同款后面，避免"床垫搜出兔毛绒四件套"。
_CATEGORY_TERMS: dict[str, tuple[str, ...]] = {
    "床笠": ("床笠", "床罩", "シーツ", "ボックスシーツ", "床笠套", "套床笠"),
    "床垫": ("床垫", "床褥", "マットレス", "床护垫", "床垫套", "垫子", "褥子"),
    "四件套": ("四件套", "三件套", "套件", "被套", "セット", "件套"),
    "被子": ("被套", "被子", "被单", "掛け布団", "被芯", "被罩"),
    "毛毯": ("毛毯", "盖毯", "ブランケット", "毯子", "空调毯"),
    "枕品": ("枕套", "枕芯", "枕头", "まくら", "抱枕", "枕"),
    "凉席": ("凉席", "凉感", "凉垫", "竹席"),
    "床裙": ("床裙", "床幔"),
}


def _query_categories(text: str) -> set[str]:
    """从一段文本（商品标题/关键词）中提取命中的床上用品类目。"""
    if not text:
        return set()
    return {cat for cat, terms in _CATEGORY_TERMS.items()
            if any(t in text for t in terms)}


def _semantic_same_category(query_text: str, title: str) -> bool:
    """货源标题与目标商品是否属于同一子类（类目词有交集）。"""
    return bool(_query_categories(query_text) & _query_categories(title))

_STORE_SEARCH_ENDPOINT = "/api/store_search/store_list"
_IMAGE_SEARCH_ENDPOINT = "/api/search/search_by_image"
# 官方"以图搜款"固定查询参数（F12 从站内图搜页抓取；token 见 Settings.jiafang_image_search_token）
_IMAGE_SEARCH_QUERY = {"SystemName": "pc", "storeid": 1}


def _clean_image_url(url: str) -> str:
    """清洗图片 URL 供官方图搜接口消费。

    实测（2026-10）：TikTok CDN 图带 `~tplv-...` 特殊后缀时，
    找家纺服务端解析崩溃（PHP checkStrPos array given，HTTP 500/103）；
    去掉 query 与 `~tplv` 后缀后接口正常接受（status=0）。
    站内 imgniu 图（含 imageMogr2 query）原样保留，服务端可处理。
    """
    if "imgniu.zhaojiafang.com" in url:
        return url
    url = re.sub(r"\?.*$", "", url)
    url = re.sub(r"~tplv.*$", "", url)
    return url


class ZhaojiafangSupplierCrawler(SupplierCrawler):
    """找家纺网货源采集器（真实 API，无需登录/付费）。

    Args:
        api_base: 搜索 API 域名（生产 api-pl-mobile.zhaojiafang.com）
        referer:  请求来源（search 站域名，合规标识）
    """

    def __init__(
        self,
        client: HttpClient,
        base_url: str = ZHAOJIAFANG_WEB_BASE,
        api_base: str = ZHAOJIAFANG_API_BASE,
        detail_base: str = ZHAOJIAFANG_DETAIL_BASE,
        image_search_token: str = "",
    ):
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.api_base = api_base.rstrip("/")
        self.detail_base = detail_base.rstrip("/")
        self._image_search_token = image_search_token

    # ---------- 采集 ----------

    def _goods_url(self, goods_id: object) -> str:
        """商品详情页链接（detail 站，用户期望的落地页；真实用户浏览器可访问）。"""
        gid = str(goods_id or "").strip()
        if not gid or gid == "0":
            return ""
        return f"{self.detail_base}/goods/{gid}"

    def search_offers(self, keywords: list[str], top_n: int = 10) -> list[SupplierOffer]:
        """按关键词在找家纺网搜索货源，返回结构化报价列表。

        实现：对每个关键词（最多 3 个控制请求量）调用店铺搜索 API →
        每个店铺取其推荐商品（recommend）作为货源条目 →
        按"商品标题+店铺"去重 → 命中任一关键词的条目优先排序。

        多词策略（修复：搜"牛奶绒床笠 四件套"不再只出床笠）：
        用户输入常含多个词（如「牛奶绒床笠 四件套」），旧实现第一个词
        命中即停止，导致后续词（四件套）从未被搜索、结果偏科。现在
        逐词搜索并聚合去重，最后按"标题命中关键词数"降序重排，
        命中目标词的货源（四件套）自然排在最前。

        关键词降级容错（企业级，实测驱动）：
        LLM 生成的货源关键词常为长句（如"牛奶绒床笠 加厚保暖 全包松紧"），
        找家纺 API 对长词返回空；本方法在空结果时自动按空格/顿号切分
        取前 2 词、前 1 词重试，保证真实货源能命中。
        """
        seen: set[str] = set()
        offers: list[SupplierOffer] = []
        kw_list = [k for k in keywords[:3] if k and k.strip()]
        for kw in kw_list:
            for candidate in _keyword_degrade(kw):
                batch = self._search_one(candidate)
                if not batch:
                    continue
                for offer in batch:
                    key = f"{offer.title}|{offer.supplier_name}"
                    if offer.title and key not in seen:
                        seen.add(key)
                        offers.append(offer)
                break  # 该关键词已命中，不再降级；继续下一个关键词（多词聚合）
            if len(offers) >= top_n * 3:
                break  # 已远超需求，提前结束避免过量请求

        # 目标词优先：用户输入常为"材质+品类"（如「牛奶绒床笠 四件套」），
        # 最后一个词通常是"要什么"（品类），排位规则：
        #   1) 标题命中全部关键词  2) 命中最后一个关键词（品类锚词）
        #   3) 命中关键词数多者  4) 保持发现顺序（稳定）
        # 注意：key 函数绝不能访问正在排序的列表（CPython sort 期间元素被搬移，
        # offers.index(off) 会 ValueError）→ 用 id → 原始序号的映射保证稳定排序。
        kw_set = {k for k in kw_list}
        if kw_set:
            orig_idx = {id(o): i for i, o in enumerate(offers)}
            last_kw = kw_list[-1]
            def _rank(off: SupplierOffer) -> tuple[int, int, int, int]:
                title = off.title or ""
                kw_hits = sum(1 for k in kw_set if k and k in title)
                hit_last = 1 if last_kw and last_kw in title else 0
                hit_all = 1 if kw_hits == len(kw_set) else 0
                return (-hit_all, -hit_last, -kw_hits, orig_idx.get(id(off), 0))
            offers.sort(key=_rank)
        logger.info("找家纺货源聚合 %d 条（多词去重后，关键词=%s）",
                    len(offers), kw_list)
        return offers[:top_n]

    def _search_one(self, keyword: str) -> list[SupplierOffer]:
        """单个关键词一轮搜索（空结果返回 []，失败返回 []，不抛错）。

        进程内 TTL 缓存（10 分钟）：同一关键词不重复打站，省请求、响应更快；
        换商品词自动 miss。缓存共享真实响应，不缓存失败。
        """
        import threading
        import time
        if not hasattr(type(self), "_kw_cache"):
            type(self)._kw_cache: dict[str, tuple[float, list]] = {}
            type(self)._kw_lock = threading.Lock()
        now = time.time()
        with type(self)._kw_lock:
            hit = type(self)._kw_cache.get(keyword)
            if hit and now - hit[0] < 600:
                return list(hit[1])  # 返回副本，调用方可随意改
            if len(type(self)._kw_cache) > 500:  # 防内存膨胀
                type(self)._kw_cache.clear()
        try:
            payload = self.client.get_json(
                f"{self.api_base}{_STORE_SEARCH_ENDPOINT}",
                params={"keyword": keyword, "page": 1, "pageSize": 10},
                headers={"Referer": f"{self.base_url}/"},
            )
        except Exception as e:  # 单个关键词失败不中断整体
            logger.warning("找家纺搜索 '%s' 失败: %s", keyword, e)
            return []
        offers = self._parse_store_payload(payload)
        with type(self)._kw_lock:
            type(self)._kw_cache[keyword] = (now, list(offers))
        return offers

    # ---------- 解析 ----------

    def _parse_store_payload(self, payload: dict) -> list[SupplierOffer]:
        """把找家纺搜索 API 响应解析为货源报价列表。

        兼容两种响应形态：
        - 成功：ResponseStatus==0，datas.store_data.data[]（店铺含 recommend[]）
        - 空/兜底：ResponseStatus==1 或 datas 缺失 → 返回空列表
        """
        if not isinstance(payload, dict):
            return []
        if payload.get("ResponseStatus") != 0:
            return []
        store_data = (payload.get("datas") or {}).get("store_data") or {}
        stores = store_data.get("data") or []
        offers: list[SupplierOffer] = []
        for store in stores:
            if not isinstance(store, dict):
                continue
            store_name = str(store.get("store_name") or "").strip()
            store_zy = str(store.get("store_zy") or "").strip()
            daifa = int(store.get("store_daifa") or 0)
            delivery = "1件代发" if daifa == 1 else ""
            supplier = store_name
            if store_zy and store_zy not in store_name:
                supplier = f"{store_name}（{store_zy}）" if store_name else store_zy

            recommends = store.get("recommend") or []
            for item in recommends:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("goods_name") or "").strip()
                price = str(item.get("goods_price") or "").strip()
                if not title:
                    continue
                images = []
                gimg = str(item.get("goods_image") or "").strip()
                if gimg.startswith("http"):
                    images.append(gimg)
                offers.append(SupplierOffer(
                    title=title,
                    price=f"¥{price}" if price else "",
                    min_order=delivery,
                    delivery=delivery,
                    supplier_name=supplier,
                    url=self._goods_url(item.get("goods_id")),
                    images=images,
                ))
        return offers

    def search_similar_by_image(
        self,
        goods_image_url: str,
        top_n: int = 10,
        token: str = "",
    ) -> list[SupplierOffer]:
        """找家纺官方"以图搜款"：站内图 → 阿里云视觉搜索 → 同款货源。

        接口（用户 F12 抓取，2026-10 实测直连可用，免费）：
        POST https://api-pl-mobile.zhaojiafang.com/api/search/search_by_image
            ?SystemName=pc&storeid=1&token=<token>
        body: {"encodeImageUrl": "<站内 imgniu 图>", "isMaterial": 0,
               "is_extend": null, "SystemName": "pc", "storeid": 1, "token": "<token>"}

        返回 goods_list[]，视觉相似度由服务端算好（ali_score 0~1，阿里云视觉分，
        0.99=高度相似），无需本地下载图片 —— 比本地感知哈希准得多。

        注意（诚实边界）：服务端只对 imgniu 站内图做特征分析；外站图（如
        TikTok CDN）返回空。因此本方法用于"站内图找同款货源"（拿本地视觉
        Top1 的货源图反查更多同款供应商比价）。
        """
        token = token or getattr(self, "_image_search_token", "")
        if not token:
            logger.warning("未配置找家纺图搜 token，跳过官方图搜")
            return []
        try:
            payload = self.client.get_json(
                f"{self.api_base}{_IMAGE_SEARCH_ENDPOINT}",
                params={**_IMAGE_SEARCH_QUERY, "token": token},
                headers={"Referer": f"{self.base_url}/"},
                method="POST",
                json_body={
                    "encodeImageUrl": _clean_image_url(goods_image_url),
                    "isMaterial": 0,
                    "is_extend": None,
                    "SystemName": "pc",
                    "storeid": 1,
                    "token": token,
                },
            )
        except Exception as e:
            logger.warning("找家纺官方图搜失败（降级本地视觉）: %s", e)
            return []
        return self._parse_image_search_payload(payload, top_n)

    def _parse_image_search_payload(self, payload: dict, top_n: int) -> list[SupplierOffer]:
        """把官方图搜响应 goods_list 解析为货源报价（ali_score 作视觉分）。"""
        if not isinstance(payload, dict) or payload.get("ResponseStatus") != 0:
            return []
        goods_list = ((payload.get("datas") or {}).get("goods_list") or [])
        offers: list[SupplierOffer] = []
        for item in goods_list:
            if not isinstance(item, dict):
                continue
            title = str(item.get("goods_name") or "").strip()
            if not title:
                continue
            store = item.get("storeinfo") or {}
            supplier = str(store.get("store_name") or "").strip()
            tags = item.get("tags") or []
            daifa = any((t.get("tagname") or "") == "代发" for t in tags if isinstance(t, dict))
            price = str(item.get("goods_price") or "").strip().replace("￥", "¥")
            images = []
            gimg = str(item.get("goods_image_url") or "").strip()
            if gimg.startswith("http"):
                images.append(gimg)
            ali_score = float(item.get("ali_score") or 0.0)
            offer = SupplierOffer(
                title=title,
                price=price,
                min_order="1件代发" if daifa else "",
                delivery="1件代发" if daifa else "",
                supplier_name=supplier,
                url=self._goods_url(item.get("goods_id")),
                images=images,
            )
            offer.match_score = round(ali_score, 3)
            offer.score_breakdown = {
                "visual": round(ali_score, 3),
                "visual_label": _visual_label(ali_score),
                "ali_score": round(ali_score, 3),
                "goods_salenum": int(item.get("goods_salenum") or 0),
                "source": "official_image_search",
            }
            offers.append(offer)
        offers.sort(key=lambda o: -o.match_score)
        logger.info("官方图搜返回 %d 条同款货源（ali_score 视觉排序）", len(offers))
        return offers[:top_n]

    def search_offers_by_image(
        self,
        query_image_url: str,
        keywords: list[str],
        top_n: int = 6,
        query_title: str = "",
    ) -> list[SupplierOffer]:
        """以图找货：关键词搜候选 → 下载双方图片 → 视觉相似度排序。

        实现（企业级图搜替代方案，找家纺无公开图搜 API）：
        1. 用关键词搜到候选货源（含 goods_image，降级容错已有）
        2. 下载 TikTok 商品图与每一条货源图
        3. 感知哈希 + 颜色直方图 + 主色 → 综合相似度
        4. 排序输出：视觉相似度高的同款货源排最前，match_score=视觉分
        5. 【语义过滤】类目词不一致的货源排在同款后面
           （真实案例：搜"ポケットマットレス 冬用 フランネル"（床垫），
            视觉蓬松毛绒相似的是"兔毛绒四件套"——子类不同不算同款）

        真实匹配逻辑在 image_processing/visual_match.py（本地、免费、可单测）。
        任一张图下载失败：该条视觉分记 0.5（中性），不影响整体返回。
        """
        from tiktok_ecommerce.image_processing.visual_match import (
            download_image,
            image_signature,
            rate_limit_sleep,
            signature_similarity,
        )

        offers = self.search_offers(keywords, top_n=max(top_n * 3, 10))
        if not offers:
            return []
        query_img = download_image(query_image_url)
        if query_img is None:
            logger.warning("TikTok 商品图下载失败，图搜退化为关键词排序: %s",
                           query_image_url[:120])
            return offers[:top_n]
        query_sig = image_signature(query_img)

        for offer in offers:
            visual = 0.5  # 中性分（无图/失败不惩罚）
            if offer.images:
                rate_limit_sleep()  # 合规限速
                src_img = download_image(offer.images[0])
                if src_img is not None:
                    visual = signature_similarity(query_sig, image_signature(src_img))
            offer.score_breakdown = dict(offer.score_breakdown or {})
            offer.score_breakdown["visual"] = round(visual, 3)
            offer.score_breakdown["visual_label"] = _visual_label(visual)
            # 融合：视觉为主（0.6）+ 关键词分打底（0.4）
            base = offer.match_score
            offer.match_score = round(0.6 * visual + 0.4 * base, 2)

        query_text = " ".join([query_title or "", *keywords])
        ranked = self._rank_semantic_first(query_text, offers)
        merged = self._augment_with_official_image_search(ranked[:top_n], query_text)
        logger.info("以图找货完成：%d 条候选 → Top %d（本地视觉 + 官方图搜增强 + 类目语义过滤）",
                    len(offers), len(merged))
        return merged

    def _rank_semantic_first(self, query_text: str,
                             offers: list[SupplierOffer]) -> list[SupplierOffer]:
        """同类目货源排最前，不同子类排后面（组内仍按视觉分排序）。"""
        return sorted(
            offers,
            key=lambda o: (_semantic_same_category(query_text, o.title), o.match_score),
            reverse=True,
        )

    def _augment_with_official_image_search(
        self, local_ranked: list[SupplierOffer], query_text: str = "", top_n: int = 6
    ) -> list[SupplierOffer]:
        """官方图搜增强：本地视觉 Top1 货源图为站内图时，
        用找家纺官方"以图搜款"反查更多同款供应商（ali_score 视觉分远准于本地哈希）。

        真实业务场景：先在 TikTok 商品图上做本地视觉匹配拿到一个"最像"的
        国内货源款，再让官方视觉引擎以这个站内款找全平台的同款比价。
        官方结果同样过"同类目优先"语义过滤（视觉像 ≠ 子类一致）。
        """
        if not local_ranked:
            return local_ranked
        top_offer = local_ranked[0]
        if not top_offer.images or "imgniu.zhaojiafang.com" not in top_offer.images[0]:
            # 本地 Top1 非站内图 → 官方接口服务端不处理，直接用本地结果
            return local_ranked[:top_n]
        official = self.search_similar_by_image(
            top_offer.images[0], top_n=max(top_n, 6),
            token=getattr(self, "_image_search_token", ""),
        )
        if not official:
            return local_ranked[:top_n]
        # 去重（官方结果可能含本地 Top1 自己），官方同款排最前（组内按 ali_score）
        local_keys = {f"{o.title}|{o.supplier_name}" for o in local_ranked}
        merged = [o for o in official if f"{o.title}|{o.supplier_name}" not in local_keys]
        if query_text:
            merged = self._rank_semantic_first(query_text, merged)
        merged = merged[: top_n // 2] + local_ranked[:top_n]
        return merged[:top_n]


def _visual_label(visual: float) -> str:
    """视觉相似度 → 用户可读标签（诚实标注区分度边界）。"""
    if visual >= 0.5:
        return "疑似同款"
    if visual >= 0.3:
        return "相似款"
    if visual >= 0.15:
        return "风格接近"
    return "仅关键词相关"


def _keyword_degrade(keyword: str) -> list[str]:
    """关键词降级序列：原词 → 前2段 → 前1段（按空格/逗号/顿号切分）。

    找家纺 API 对过长关键词返回空结果，用逐级截断保证命中。
    """
    kw = keyword.strip()
    if not kw:
        return []
    parts = [p.strip() for p in kw.replace(",", " ").replace("，", " ").replace("、", " ").split() if p.strip()]
    candidates = [kw]
    if len(parts) >= 3:
        candidates.append(" ".join(parts[:2]))
    if len(parts) >= 2:
        candidates.append(" ".join(parts[:1]))
    seen: set[str] = set()
    out: list[str] = []
    for c in candidates:
        if c not in seen:
            seen.add(c)
            out.append(c)
    return out
