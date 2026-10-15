"""采集器接口抽象。

企业级要点：面向接口编程 —— 上层 Agent 只依赖本接口，
替换数据源（TikTok → 其他平台）时不影响 Agent 与流水线。
"""
from abc import ABC, abstractmethod

from tiktok_ecommerce.models.product import Product
from tiktok_ecommerce.models.supplier import SupplierOffer


class ProductCrawler(ABC):
    """商品/评论采集器接口。"""

    @abstractmethod
    def fetch_product(self, url: str) -> Product:
        """按商品链接采集一个商品（含评论）。"""

    @abstractmethod
    def search_products(self, keyword: str, limit: int = 5) -> list[Product]:
        """按关键词搜索竞品商品列表。"""


class SupplierCrawler(ABC):
    """货源平台采集器接口。"""

    @abstractmethod
    def search_offers(self, keywords: list[str], top_n: int = 10) -> list[SupplierOffer]:
        """按关键词搜索货源，返回结构化报价列表。"""
