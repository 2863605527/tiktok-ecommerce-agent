"""国内货源平台直连通道（1688 等，默认不启用）。

数据真实性原则：货源信息 100% 来自真实网页/API，
LLM 只负责特征提取与打分，绝不生成货源数据 —— 从源头杜绝幻觉。

⚠️ 为什么默认不走直连：
- 1688 搜索页同样重度 JS 渲染 + 登录墙 + 滑块风控，requests 拿到的是空壳/跳转
- 生产环境建议：source="api" 对接 1688 开放平台/阿里巴巴采购 API（需企业 AppKey），
  或 source="sample" 使用导出的货源样本；直连仅建议用 Playwright 做小量补充。
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.crawlers.base import SupplierCrawler
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.models.supplier import SupplierOffer

logger = get_logger(__name__)

_DIRECT_NOT_SUPPORTED = (
    "1688 直连采集默认未启用：JS 渲染 + 登录墙 + 风控。"
    "请改用 source='sample'（货源样本）或 source='api'（1688 开放平台/采购 API）；"
    "确需直连请用 Playwright 小量采集并控制频率。"
)


class ChinaSupplierCrawler(SupplierCrawler):
    """1688 货源直连采集器（RPA/开放平台扩展点）。"""

    def __init__(self, client: HttpClient, base_url: str = "https://www.1688.com"):
        self.client = client
        self.base_url = base_url

    def search_offers(self, keywords: list[str], top_n: int = 10) -> list[SupplierOffer]:
        raise CrawlerError(_DIRECT_NOT_SUPPORTED, detail=f"keywords={keywords[:3]}")

    @staticmethod
    def _parse_search_result(html: str, keyword: str) -> list[SupplierOffer]:
        """解析搜索结果页（RPA 拿到渲染 HTML 后复用，选择器按实际页面调整）。"""
        soup = BeautifulSoup(html, "lxml")
        offers: list[SupplierOffer] = []
        for card in soup.select("div.sm-offer-item, div[offer-id]"):
            title_el = card.select_one(".title, .offer-title")
            price_el = card.select_one(".price, .offer-price")
            if not title_el:
                continue
            link = title_el if getattr(title_el, "name", None) == "a" else title_el.find("a")
            offers.append(SupplierOffer(
                title=title_el.get_text(strip=True),
                price=price_el.get_text(strip=True) if price_el else "",
                url=link.get("href", "") if link else "",
            ))
        return offers
