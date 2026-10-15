"""③ 货源匹配 Agent：提取商品特征 → 搜索货源 → 多维打分 → 对比清单。

数据真实性：货源信息 100% 来自爬虫真实网页（家纺垂直站/1688/样本），
LLM 只做关键词精炼，绝不生成货源数据 → 从源头杜绝幻觉。

运行时货源平台切换（2026-10 新增）：用户聊天说"去 1688 找货源 / 换回找家纺网"时，
通过 state.supplier_source 动态切换货源源（1688 | jiafang | sample | api）。
SourcingAgent 持有 supplier_factory（按源名创建真实 crawler），不依赖固定注入实例。

打分设计（可解释、可演示）：
- 六个维度各 0~1，加权求和（title_hit 0.4 / price 0.15 / min_order 0.15 /
  delivery 0.15 / jp_match 0.10 / brand 0.05）
- score_breakdown 保留每维分数，可逐维讲解
- jp_match 专为日本站设计：标题含日文/中文商品词（ボックスシーツ、綿100%等）加分
"""
from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from langchain_core.language_models import BaseChatModel

from tiktok_ecommerce.agents.base import BaseAgent
from tiktok_ecommerce.categories.base import CategoryProfile
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.crawlers.base import SupplierCrawler
from tiktok_ecommerce.models.report import SelectionReport
from tiktok_ecommerce.models.supplier import SupplierOffer

logger = get_logger(__name__)

KEYWORD_PROMPT = """你是跨境电商采购员，专精日本站家纺（床上用品）。根据下面的商品分析报告，提炼 3-5 个用于在国内货源平台（默认家纺垂直站，可选1688）搜索的关键词。
要求：
- 词要具体（品类+材质/功能+规格），能直接搜到同款或相似货源
- **必须输出中文关键词**（如 床笠 全棉 60支 / 四件套 磨毛 日式 / 法兰绒床笠 加厚），
  禁止输出日文假名/日文汉字（国内货源站搜日文搜不到）
- 保留报告中的核心规格（尺寸、材质）
报告：{report}
只输出 JSON 数组：["关键词1", "关键词2", "关键词3"]，不要多余文字。"""

# 日文货源关键词 → 中文（国内货源站检索用；长词优先替换）
_JP_TO_ZH: dict[str, str] = {
    "ボックスシーツ": "床笠", "ベッドシーツ": "床单", "シーツ": "床单",
    "マットレスカバー": "床笠", "マットレス": "床垫", "ベッド": "床",
    "フランネル": "法兰绒", "ミルクフランネル": "牛奶法兰绒", "ミルク": "牛奶绒",
    "裏起毛": "加厚绒毛", "起毛": "磨毛", "厚手": "加厚",
    "冬用": "冬季 保暖", "あったか": "保暖", "抗菌": "抗菌", "防ダニ": "防螨",
    "綿100%": "全棉", "オーガニックコットン": "有机棉", "天丝": "天丝",
    "掛け布団カバー": "被套", "枕カバー": "枕套", "布団": "被子",
    "四件套": "四件套", "4点セット": "四件套",
    "接触冷感": "夏凉", "洗える": "可水洗", "寝具": "床品",
    "シングル": "单人", "セミダブル": "小双人", "ダブル": "双人",
    "クイーン": "加大", "キング": "特大", "秋冬": "秋冬",
    "カバー": "套", "色": "色", "サイズ": "尺寸",
}

# 日文假名范围（\u3040-\u30ff）
_JP_KANA_RE = re.compile(r"[\u3040-\u30ff]")


def _to_chinese_keyword(keyword: str) -> str | None:
    """把日文货源关键词翻译为中文（规则层，零成本）。

    - 无日文假名 → 原样返回（已是中文/英文）
    - 有日文假名 → 按映射表长词优先替换；替换后仍有假名残留 → 返回 None（丢弃，
      由降级/其他关键词接管，绝不把搜不到的词硬塞给中文货源站）
    """
    if not _JP_KANA_RE.search(keyword):
        return keyword
    out = keyword
    for jp, zh in sorted(_JP_TO_ZH.items(), key=lambda kv: -len(kv[0])):
        out = out.replace(jp, zh)
    if _JP_KANA_RE.search(out):
        return None
    return out.strip(" ，。、") or None

# 打分为 1.0 的"可信供应商"背书词（标题出现即加满 brand 分）
_BRAND_WORDS = ("工厂", "一件代发", "跨境专供", "出口品质", "源厂", "直供")
# 发货时效映射（关键词 → 分数）
_DELIVERY_SCORES = [
    (("24",), 0.9),
    (("48",), 0.75),
    (("72", "3天", "三天"), 0.6),
    (("7天", "七天", "5-7"), 0.3),
]
# 起批宽松度（低起批 → 高分，适合小卖家试销）
_MIN_ORDER_SCORES = [
    (("1件", "1套", "1个", "一件代发"), 0.9),
    (("2件", "2套"), 0.7),
    (("5件", "5套"), 0.5),
]


def _has_cjk(text: str) -> bool:
    """是否含中日韩字符（日文假名/汉字 → 判定为日本站相关词）。"""
    return any("\u4e00" <= ch <= "\u9fff" or "\u3040" <= ch <= "\u30ff" for ch in text)


def _first_product_image(products: list) -> str | None:
    """取第一个带图的商品图片 URL（供以图找货）。"""
    for p in products:
        images = getattr(p, "images", None) or []
        if images and isinstance(images[0], str) and images[0].startswith("http"):
            return images[0]
    return None


def _first_product_title(products: list) -> str:
    """取第一个商品标题（供货源类目语义过滤：床垫 vs 四件套）。"""
    for p in products:
        title = getattr(p, "title", "") or ""
        if title:
            return str(title)
    return ""


def _merge_by_url(pre_offers: list[SupplierOffer], extra: list[SupplierOffer]) -> list[SupplierOffer]:
    """按 URL 合并两次搜索结果（预搜索 + 精炼补搜），重复的保留先出现的。"""
    seen: set[str] = set()
    merged: list[SupplierOffer] = []
    for offer in list(pre_offers) + list(extra):
        key = offer.url or offer.title
        if key in seen:
            continue
        seen.add(key)
        merged.append(offer)
    return merged


class SourcingAgent(BaseAgent):
    """货源匹配 Agent。"""

    name = "sourcing_agent"
    description = "根据选品报告搜索国内货源并多维打分对比（家纺垂直站默认，1688可选）"

    def __init__(self, crawler: SupplierCrawler, llm: BaseChatModel, top_n: int = 10,
                 category: CategoryProfile | None = None,
                 supplier_factory: Callable[[str], SupplierCrawler] | None = None):
        self.crawler = crawler
        self.llm = llm
        self.top_n = top_n
        self.category = category or CategoryProfile()
        # 运行时切换货源源（"去1688找货源"→ supplier_factory("1688")）；
        # 未提供工厂时始终用注入的默认 crawler
        self.supplier_factory = supplier_factory

    def _resolve_crawler(self, state: dict[str, Any]) -> SupplierCrawler:
        """按 state.supplier_source 解析货源源（无指定 → 默认注入 crawler）。"""
        src = (state.get("supplier_source") or "").strip().lower()
        if src and self.supplier_factory:
            logger.info("[%s] 切换货源源 → %s", self.name, src)
            return self.supplier_factory(src)
        return self.crawler

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        report: SelectionReport | None = state.get("report")
        if not report or not report.keywords:
            return {"offers": [], "sourcing_note": "缺少关键词，跳过货源匹配"}

        logger.info("[%s] 开始匹配货源", self.name)
        region = state.get("region", "JP")
        crawler = self._resolve_crawler(state)
        # 1) 品类模板生成搜索词（床上用品命中率更高），报告关键词兜底
        base_keywords = self.category.build_search_keywords(report.keywords, region)
        # 2) LLM 精炼（失败自动回退规则词，不影响主流程）
        keywords = self._refine_keywords(report, base_keywords)
        # 2.5) 日文关键词 → 中文（找家纺为中文站，日文词搜不到；无法翻译的丢弃）
        keywords = [k for k in (_to_chinese_keyword(x) for x in keywords) if k] or base_keywords
        # 3) 搜索货源（数据源由工厂注入：sample/jiafang/1688/api）
        #    优先"以图找货"：采集的商品带图 → 视觉相似度排序（同款货源排前）
        query_image = _first_product_image(state.get("products") or [])
        query_title = _first_product_title(state.get("products") or [])
        offers, used_keywords = self._search_with_fallback(
            query_image, query_title, keywords, base_keywords, crawler=crawler)
        # 4) 多维打分（日语规格词加分，服务日本站；visual 分融合见 _score）
        offers = self._score(offers, used_keywords)
        logger.info("[%s] 匹配到 %d 条货源", self.name, len(offers))
        return {"offers": offers, "sourcing_keywords": keywords}

    # ---------- 并行编排专用（Supervisor Phase2/3：不依赖报告先预搜，报告产出后再精炼合并） ----------
    def pre_search(self, products: list, region: str = "JP",
                   supplier_source: str | None = None) -> tuple[list[SupplierOffer], list[str]]:
        """Supervisor Phase2 并行用：不等选品报告，直接用商品标题→中文关键词 + 品类模板词
        先搜索货源（真实网络请求，耗时；与 RAG 评论分析互不依赖 → 可并行）。

        数据真实性不变：货源 100% 来自爬虫真实网页；LLM 精炼放到 refine_merge 阶段。
        返回 (初选货源, 预搜索关键词)。
        """
        crawler = self._resolve_crawler({"supplier_source": supplier_source})
        query_image = _first_product_image(products)
        query_title = _first_product_title(products)
        title_keywords = self._title_to_chinese(query_title)
        base_keywords = self.category.build_search_keywords(title_keywords, region)
        offers, used = self._search_with_fallback(
            query_image, query_title, base_keywords, base_keywords, crawler=crawler)
        logger.info("[%s] 预搜索完成: %d 条（关键词 %s）", self.name, len(offers), used[:3])
        return offers, used

    def refine_merge(self, report: SelectionReport | None, pre_offers: list[SupplierOffer],
                     pre_keywords: list[str], products: list, region: str = "JP",
                     supplier_source: str | None = None,
                     ) -> list[SupplierOffer]:
        """Supervisor Phase3 用：选品报告产出后，LLM 精炼关键词，与预搜索词不同则补搜一次，
        按 URL 合并去重后统一六维打分。

        - 报告为空（采集无评论/资料不足）：对预搜索结果按预搜索词打分，绝不编造关键词
        - 关键词相同：不再重复搜索（省一次网络请求），直接打分
        """
        if not report or not report.keywords:
            logger.info("[%s] 报告无关键词，直接对预搜索 %d 条货源打分", self.name, len(pre_offers))
            return self._score(pre_offers, pre_keywords)
        crawler = self._resolve_crawler({"supplier_source": supplier_source})
        base_keywords = self.category.build_search_keywords(report.keywords, region)
        refined = self._refine_keywords(report, base_keywords)
        refined = [k for k in (_to_chinese_keyword(x) for x in refined) if k] or base_keywords
        if set(refined) == set(pre_keywords):
            return self._score(pre_offers, refined)
        query_image = _first_product_image(products)
        query_title = _first_product_title(products)
        extra, used = self._search_with_fallback(
            query_image, query_title, refined, base_keywords, crawler=crawler)
        merged = _merge_by_url(pre_offers, extra)
        logger.info("[%s] 精炼补搜 %d 条，合并后 %d 条", self.name, len(extra), len(merged))
        return self._score(merged, used)

    def _title_to_chinese(self, title: str) -> list[str]:
        """商品标题拆词 → 中文货源关键词（长词优先翻译；残留日文假名的片段丢弃）。"""
        if not title:
            return []
        out: list[str] = []
        for part in re.split(r"[・\s,，、/（）()]", title):
            kw = _to_chinese_keyword(part.strip())
            if kw and kw not in out:
                out.append(kw)
        return out[:3]

    def _search_with_fallback(self, query_image: str | None, query_title: str,
                              keywords: list[str], fallback: list[str],
                              crawler: SupplierCrawler | None = None,
                              ) -> tuple[list[SupplierOffer], list[str]]:
        """搜索货源；LLM 精炼词无货时用品类模板兜底词自动重试（真实站点类目覆盖差异大）。

        真实案例（2026-10）：找家纺对"法兰绒床笠"无货（0 条），对"牛奶绒床笠"有货；
        只依赖 LLM 词会漏掉真实货源 → 必须两级关键词重试。
        返回 (offers, 实际命中的关键词)。
        """
        target = crawler or self.crawler

        def _search(kws: list[str]) -> list[SupplierOffer]:
            if query_image and hasattr(target, "search_offers_by_image"):
                return target.search_offers_by_image(
                    query_image, kws, top_n=self.top_n, query_title=query_title)
            return target.search_offers(kws, top_n=self.top_n)

        offers = _search(keywords)
        if offers or not fallback:
            return offers, keywords
        logger.warning("[%s] 关键词无货，降级用品类兜底词重试: %s",
                       self.name, fallback[:3])
        return _search(fallback), fallback

    def _refine_keywords(self, report: SelectionReport, fallback: list[str]) -> list[str]:
        """LLM 精炼关键词；任何异常回退规则关键词，绝不让 LLM 卡住主流程。"""
        try:
            resp = self.llm.invoke(KEYWORD_PROMPT.format(report=report.to_markdown()))
            from tiktok_ecommerce.common.text import extract_json
            data = extract_json(resp.content)
            refined = [str(x).strip() for x in data if str(x).strip()]
            if refined:
                return refined[:5]
            raise ValueError("空数组")
        except Exception as e:
            logger.warning("[%s] LLM 精炼关键词失败，回退规则词: %s", self.name, str(e)[:80])
        return fallback[:5]

    @staticmethod
    def _score(offers: list[SupplierOffer], keywords: list[str]) -> list[SupplierOffer]:
        """六维规则打分：title_hit / price / min_order / delivery / jp_match / brand。"""
        jp_keywords = [k for k in keywords if _has_cjk(k)]

        def _title_hit(offer: SupplierOffer) -> float:
            title = offer.title.lower()
            hits = [k for k in keywords if k.lower() in title]
            return round(min(len(hits) / max(len(keywords), 1), 1.0), 2)

        def _price(offer: SupplierOffer) -> float:
            v = offer.price_value
            if v <= 0:
                return 0.2
            if v <= 200:
                return 0.9
            if v <= 500:
                return 0.6
            return 0.3

        def _min_order(offer: SupplierOffer) -> float:
            for keys, score in _MIN_ORDER_SCORES:
                if any(k in offer.min_order for k in keys):
                    return score
            if offer.min_order:
                return 0.4
            return 0.3

        def _delivery(offer: SupplierOffer) -> float:
            for keys, score in _DELIVERY_SCORES:
                if any(k in offer.delivery for k in keys):
                    return score
            if offer.delivery:
                return 0.4
            return 0.3

        def _jp_match(offer: SupplierOffer) -> float:
            if not jp_keywords:
                return 0.5  # 无日语词时给中性分，不惩罚
            hits = [k for k in jp_keywords if k.lower() in offer.title.lower()]
            return round(min(len(hits) / max(len(jp_keywords), 1), 1.0), 2)

        def _brand(offer: SupplierOffer) -> float:
            return 1.0 if any(w in offer.title or w in offer.supplier_name for w in _BRAND_WORDS) else 0.3

        weights = {"title_hit": 0.40, "price": 0.15, "min_order": 0.15,
                   "delivery": 0.15, "jp_match": 0.10, "brand": 0.05}
        for offer in offers:
            parts = {
                "title_hit": _title_hit(offer),
                "price": _price(offer),
                "min_order": _min_order(offer),
                "delivery": _delivery(offer),
                "jp_match": _jp_match(offer),
                "brand": _brand(offer),
            }
            total = sum(weights[k] * v for k, v in parts.items())
            # 以图找货融合：图搜算出的 visual 分保留，与关键词分 6:4 融合
            prev = offer.score_breakdown or {}
            visual = prev.get("visual")
            if isinstance(visual, (int, float)):
                if prev.get("source") == "official_image_search":
                    # 官方视觉引擎（阿里云以图搜款）相似度是权威：不做六维稀释，
                    # 保持 ali_score 原值排最前；字段标签原样保留（前端展示来源）
                    total = float(visual)
                    for k in ("visual_label", "ali_score", "source"):
                        if k in prev:
                            parts[k] = prev[k]
                else:
                    total = 0.6 * float(visual) + 0.4 * total
                    parts["visual"] = round(float(visual), 3)
                    for k in ("visual_label", "ali_score", "source"):
                        if k in prev:
                            parts[k] = prev[k]
            offer.match_score = round(total, 2)
            offer.score_breakdown = parts
        return sorted(offers, key=lambda x: -x.match_score)
