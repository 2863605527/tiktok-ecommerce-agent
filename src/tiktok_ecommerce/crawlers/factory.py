"""采集器工厂：按配置创建数据源（可插拔架构的入口）。

切换数据源无需改业务代码，只改 .env：
    PRODUCT_SOURCE=sample | fastmoss | socialcrawl | tikhub | direct
    SUPPLIER_SOURCE=sample | jiafang | 1688 | api

- sample     ：本地 JSON 样本（默认，离线可跑/可测/演示稳）
- fastmoss   ：FastMoss OpenAPI（TikTok 商品/评论，$0.01/次起，region 含 JP）
- socialcrawl：SocialCrawl（新账号 100 credits 免费，1 credit/次，搜索/评论含 JP，
                适合先免费验证真实数据链路；.env 填 SOCIALCRAWL_API_KEY）
- tikhub     ：TikHub（$0.001/次起，评论含 JP、搜索官方未列 JP；
                适合日常批量；.env 填 TIKHUB_API_KEY）
- jiafang    ：找家纺网直连（www.zhaojiafang.com 真实 API，免费，默认货源平台）
- 1688       ：综合批发平台直连（用户可选，默认不可用需自行接入）
- direct     ：TikTok 直连 RPA（默认抛错，需自行接入 Playwright + 代理）
"""
from __future__ import annotations

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.config import Settings
from tiktok_ecommerce.crawlers.base import ProductCrawler, SupplierCrawler
from tiktok_ecommerce.crawlers.fastmoss import FASTMOSS_API_BASE, FastMossProductCrawler
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.crawlers.local_sample import FileProductCrawler, FileSupplierCrawler
from tiktok_ecommerce.crawlers.socialcrawl import SOCIALCRAWL_API_BASE, SocialCrawlProductCrawler
from tiktok_ecommerce.crawlers.supplier import ChinaSupplierCrawler
from tiktok_ecommerce.crawlers.third_party import ThirdPartySupplierCrawler
from tiktok_ecommerce.crawlers.tikhub import TIKHUB_API_BASE, TikHubProductCrawler
from tiktok_ecommerce.crawlers.tiktok import TikTokProductCrawler
from tiktok_ecommerce.crawlers.zhaojiafang import ZhaojiafangSupplierCrawler

logger = get_logger(__name__)

# 直连类数据源别名
_DIRECT_SOURCES = {"direct", "tiktok", "rpa"}
# 货源平台：家纺垂直站（默认找家纺网）/ 综合批发平台 1688
_JIAFANG_SOURCES = {"jiafang", "zhaojiafang", "direct"}
_1688_SOURCES = {"1688", "alibaba"}


def build_http_client(settings: Settings) -> HttpClient:
    """按配置构造统一 HTTP 客户端（代理可选；UA 默认走轮换池）。"""
    return HttpClient(
        timeout=settings.crawler.timeout,
        min_interval=settings.crawler.request_interval,
        max_retries=settings.crawler.max_retries,
        proxy=settings.crawler.proxy_url or None,
    )


def get_product_crawler(
    settings: Settings,
    *,
    source: str | None = None,
    category: str = "bedding",
    client: HttpClient | None = None,
) -> ProductCrawler:
    """创建商品/评论采集器。"""
    src = (source or settings.crawler.product_source or "sample").lower()
    sample = settings.crawler.sample_dir / f"products_jp_{category}.json"

    if src == "sample":
        logger.info("商品数据源=本地样本: %s", sample.name)
        return FileProductCrawler(sample)

    if src in {"fastmoss", "api"}:
        key = settings.crawler.third_party_product_api_key
        if not key:
            raise CrawlerError(
                "商品数据源为 fastmoss，但未配置 FastMoss API Key",
                detail="请在 .env 设置 THIRD_PARTY_PRODUCT_API_KEY "
                       "（申请方式见 docs/HOW_TO_GET_DATA.md，注册后 Console 创建 client_secret）",
            )
        logger.info("商品数据源=FastMoss OpenAPI（region=%s）", settings.crawler.fastmoss_region)
        return FastMossProductCrawler(
            client or build_http_client(settings),
            api_key=key,
            region=settings.crawler.fastmoss_region,
            api_base=settings.crawler.third_party_product_api_base
            or FASTMOSS_API_BASE,
        )

    if src == "socialcrawl":
        key = settings.crawler.socialcrawl_api_key
        if not key:
            raise CrawlerError(
                "商品数据源为 socialcrawl，但未配置 SocialCrawl API Key",
                detail="请在 .env 设置 SOCIALCRAWL_API_KEY "
                       "（socialcrawl.dev 注册即送 100 credits，无信用卡）",
            )
        logger.info("商品数据源=SocialCrawl（region=%s, 免费额度验证）", settings.crawler.fastmoss_region)
        return SocialCrawlProductCrawler(
            client or build_http_client(settings),
            api_key=key,
            region=settings.crawler.fastmoss_region,
            api_base=settings.crawler.socialcrawl_base_url or SOCIALCRAWL_API_BASE,
        )

    if src == "tikhub":
        key = settings.crawler.tikhub_api_key
        if not key:
            raise CrawlerError(
                "商品数据源为 tikhub，但未配置 TikHub API Key",
                detail="请在 .env 设置 TIKHUB_API_KEY "
                       "（user.tikhub.io/dashboard/api 生成，新号送 $0.05 体验额度）",
            )
        logger.info("商品数据源=TikHub（region=%s, 批量付费源）", settings.crawler.fastmoss_region)
        return TikHubProductCrawler(
            client or build_http_client(settings),
            api_key=key,
            region=settings.crawler.fastmoss_region,
            api_base=settings.crawler.tikhub_base_url or TIKHUB_API_BASE,
        )

    if src in _DIRECT_SOURCES:
        logger.warning("商品数据源=直连 RPA（默认不可用，需自行接入 Playwright）")
        return TikTokProductCrawler(
            client or build_http_client(settings),
            base_url=settings.crawler.tiktok_base_url,
        )

    raise CrawlerError(f"未知商品数据源: {src}", detail="可选: sample | fastmoss | socialcrawl | tikhub | direct")


def get_supplier_crawler(
    settings: Settings,
    *,
    source: str | None = None,
    category: str = "bedding",
    client: HttpClient | None = None,
) -> SupplierCrawler:
    """创建国内货源采集器。

    source 取值：
      sample  ：本地家纺货源样本（默认，91家纺风格，离线可跑）
      jiafang ：家纺垂直站直连（91家纺等，RPA 扩展点，默认不可用）
      1688    ：综合批发平台直连（用户可选，RPA 扩展点，默认不可用）
      api     ：第三方/开放平台 HTTP API（生产）
    """
    src = (source or settings.crawler.supplier_source or "sample").lower()
    sample = settings.crawler.sample_dir / f"suppliers_jiafang_{category}.json"

    if src == "sample":
        logger.info("货源数据源=本地家纺样本: %s", sample.name)
        return FileSupplierCrawler(sample)

    if src == "api":
        base = settings.crawler.third_party_supplier_api_base
        key = settings.crawler.third_party_supplier_api_key
        if not base or not key:
            raise CrawlerError(
                "货源数据源为 api，但未配置货源平台地址/密钥",
                detail="请在 .env 设置 THIRD_PARTY_SUPPLIER_API_BASE 与 THIRD_PARTY_SUPPLIER_API_KEY",
            )
        logger.info("货源数据源=第三方/开放平台 API: %s", base)
        return ThirdPartySupplierCrawler(client or build_http_client(settings), base, key)

    if src in _JIAFANG_SOURCES:
        logger.info("货源数据源=找家纺网直连（真实 API，免费）")
        return ZhaojiafangSupplierCrawler(
            client or build_http_client(settings),
            base_url=settings.crawler.jiafang_base_url,
            api_base=settings.crawler.jiafang_api_base_url,
            detail_base=settings.crawler.jiafang_detail_base_url,
            image_search_token=settings.crawler.jiafang_image_search_token,
        )

    if src in _1688_SOURCES:
        logger.warning("货源数据源=1688 直连 RPA（默认不可用，需登录态/Playwright）")
        return ChinaSupplierCrawler(
            client or build_http_client(settings),
            base_url=settings.crawler.supplier_base_url,
        )

    raise CrawlerError(
        f"未知货源数据源: {src}", detail="可选: sample | jiafang | 1688 | api"
    )
