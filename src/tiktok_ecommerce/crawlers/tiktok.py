"""TikTok 商品/评论直连通道（RPA 扩展点，默认不启用）。

⚠️ 为什么默认不走直连（工程现实）：
- TikTok 全站 JS 渲染 + 请求签名（X-Bogus / msToken / _signature），requests 拿不到数据
- 强风控：设备指纹、滑块验证、IP 封禁（日本站还需日本住宅代理）、登录墙
- 评论走内部加密接口 + cursor 分页，缺签名/cookie 直接 403/空响应

合规获取数据的三条路径（本项目已实现前两条，切换 source 即可）：
1. source="sample"：本地样本/数据平台导出（离线、测试、演示）         —— 默认
2. source="api"：第三方数据平台 API（FastMoss/Kalodata/EchoTik）       —— 生产推荐
3. source="tiktok"：本通道，需自行补齐 Playwright 渲染 + 签名 + 代理    —— 仅小量补充

Playwright 落地位置（_render）：用 patchright/undetect + 住宅代理打开页面、
等待商品/评论节点、滚动加载后调用 _parse_review_block 解析。该通道脆弱且有
封号/合规风险，故不内置实现、不默认启用。
"""
from __future__ import annotations

from bs4 import BeautifulSoup

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.common.text import clean_html, normalize, remove_emoji, truncate
from tiktok_ecommerce.crawlers.base import ProductCrawler
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.models.product import Product, Review

logger = get_logger(__name__)

_DIRECT_NOT_SUPPORTED = (
    "TikTok 直连采集默认未启用：页面 JS 渲染 + 请求签名 + 风控，requests 无法直接获取。"
    "请改用 source='sample'（本地样本）或 source='api'（第三方数据平台 API）；"
    "确需直连请在本文件 _render() 接入 Playwright + 住宅代理（注意合规与频率）。"
)


class TikTokProductCrawler(ProductCrawler):
    """TikTok 直连采集器（RPA 扩展点）。"""

    def __init__(self, client: HttpClient, base_url: str = "https://www.tiktok.com"):
        self.client = client
        self.base_url = base_url

    def fetch_product(self, url: str) -> Product:
        raise CrawlerError(_DIRECT_NOT_SUPPORTED, detail=f"url={url}")

    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        raise CrawlerError(_DIRECT_NOT_SUPPORTED, detail=f"keyword={keyword}")

    def fetch_reviews(self, url: str, max_comments: int = 200) -> list[Review]:
        raise CrawlerError(_DIRECT_NOT_SUPPORTED, detail=f"url={url}")

    # ---------- RPA 扩展点 ----------
    def _render(self, url: str) -> str:
        """Playwright 渲染入口（按需自行实现，依赖可选：pip install playwright）。

        实现要点：
        1. 启动带指纹/代理的浏览器上下文，打开 url，等待商品标题节点
        2. 滚动评论区直到评论数达标或无更多（cursor 分页）
        3. 返回渲染后的 page.content()，交给 _parse_review_block / 商品解析
        """
        raise NotImplementedError("请接入 Playwright 后实现，详见模块文档字符串")

    # ---------- 解析工具（RPA 拿到渲染 HTML 后可直接复用，已可单测）----------
    @staticmethod
    def _parse_review_block(html: str, limit: int = 200) -> list[Review]:
        """从渲染后的 HTML 片段解析评论（CSS 选择器需按实际页面结构调整）。"""
        soup = BeautifulSoup(html, "lxml")
        reviews: list[Review] = []
        for block in soup.select("div[data-review]")[:limit]:
            text = normalize(remove_emoji(clean_html(block.get_text())))
            if text:
                reviews.append(Review(content=truncate(text, 500)))
        return reviews
