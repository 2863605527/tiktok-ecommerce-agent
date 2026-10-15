"""本地样本数据源（离线可跑 / 单元测试 / 演示兜底）。

为什么需要它（工程与合规考量）：
- TikTok/1688 直连反爬强、不稳定，开发调试和 CI 不能依赖外网
- 冷启动阶段可先用从数据平台导出的 JSON / 人工整理的样本跑通全链路
- 与真实数据源实现同一套接口，切换数据源时代码零改动

样本位置：data/samples/*.json（字段与 Product/Review/SupplierOffer 对齐）。
"""
from __future__ import annotations

import json
from pathlib import Path

from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.crawlers.base import ProductCrawler, SupplierCrawler
from tiktok_ecommerce.models.product import Product, Review
from tiktok_ecommerce.models.supplier import SupplierOffer

logger = get_logger(__name__)


def _load_json(path: Path) -> list[dict]:
    if not path.is_file():
        raise FileNotFoundError(f"样本文件不存在: {path}")
    with path.open("r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        raise ValueError(f"样本文件应为 JSON 数组: {path}")
    return data


def _build_product(item: dict) -> Product:
    reviews = [
        Review(
            content=r.get("content", ""),
            rating=float(r.get("rating", 0) or 0),
            helpful_count=int(r.get("helpful_count", 0) or 0),
            author=r.get("author"),
        )
        for r in item.get("reviews", [])
        if r.get("content")
    ]
    return Product(
        id=str(item.get("id", "")),
        title=item.get("title", ""),
        price=str(item.get("price", "")),
        currency=item.get("currency", "JPY"),
        url=item.get("url", ""),
        description=item.get("description", ""),
        sales=int(item.get("sales", 0) or 0),
        category=item.get("category", ""),
        specs=item.get("specs", {}) or {},
        tags=item.get("tags", []) or [],
        reviews=reviews,
    )


class FileProductCrawler(ProductCrawler):
    """从本地 JSON 样本读取竞品商品与评论。"""

    def __init__(self, sample_path: str | Path):
        self.sample_path = Path(sample_path)
        self._products: list[Product] | None = None

    def _load(self) -> list[Product]:
        if self._products is None:
            items = _load_json(self.sample_path)
            self._products = [_build_product(i) for i in items]
            logger.info("加载本地商品样本 %d 个: %s", len(self._products), self.sample_path.name)
        return self._products

    def fetch_product(self, url: str) -> Product:
        """按链接（或商品 ID）取单个商品。"""
        for p in self._load():
            if p.url == url or (url and p.id and p.id in url):
                return p
        raise ValueError(f"样本中未找到商品: {url}")

    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        """按关键词做简单相关性排序（命中标题/标签/规格词越多越靠前）。

        样本模式下 0 命中也返回全部（标注日志），保证离线演示可跑通；
        真实数据源（API/直连）不会做此兜底。
        """
        products = self._load()
        if not keyword:
            return products[:limit]

        terms = [t for t in keyword.replace("　", " ").replace("/", " ").split() if t]

        def hit_count(p: Product) -> int:
            haystack = " ".join(
                [p.title, p.description, " ".join(p.tags), " ".join(p.specs.values())]
            )
            return sum(1 for t in terms if t in haystack)

        scored = sorted(products, key=lambda p: -hit_count(p))
        matched = [p for p in scored if hit_count(p) > 0]
        if not matched:
            logger.warning("样本中无关键词命中（%s），样本模式返回全部供演示", keyword)
            return products[:limit]
        return matched[:limit]


class FileSupplierCrawler(SupplierCrawler):
    """从本地 JSON 样本读取国内货源报价。"""

    def __init__(self, sample_path: str | Path):
        self.sample_path = Path(sample_path)
        self._offers: list[SupplierOffer] | None = None

    def _load(self) -> list[SupplierOffer]:
        if self._offers is None:
            items = _load_json(self.sample_path)
            self._offers = [
                SupplierOffer(
                    title=o.get("title", ""),
                    price=str(o.get("price", "")),
                    min_order=o.get("min_order", ""),
                    delivery=o.get("delivery", ""),
                    supplier_name=o.get("supplier_name", ""),
                    url=o.get("url", ""),
                )
                for o in items
                if o.get("title")
            ]
            logger.info("加载本地货源样本 %d 条: %s", len(self._offers), self.sample_path.name)
        return self._offers

    def search_offers(self, keywords: list[str], top_n: int = 10) -> list[SupplierOffer]:
        """样本模式直接返回全部货源（相关性打分由 SourcingAgent 统一完成）。"""
        offers = self._load()
        logger.info("样本货源返回 %d 条（关键词: %s）", len(offers), keywords[:3])
        return offers[:top_n]
