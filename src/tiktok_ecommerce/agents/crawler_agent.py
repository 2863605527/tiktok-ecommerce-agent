"""① 采集 Agent：采集竞品 → 清洗 → 品类过滤 → 写入向量库（构建 RAG 知识库）。

品类过滤（2026-10 新增）：用户未指定品类时默认只保留本品类商品（如床上用品），
避免泛问（如"日本冬天有什么好卖"）搜到电暖夹克等非家纺商品。
过滤依据品类配置的 category_markers（标题命中任一即通过）；过滤后为空时如实返回，
并把过滤说明写进 state，绝不伪造商品（数据真实性原则）。
"""
from __future__ import annotations

from collections.abc import Callable
from typing import Any

from tiktok_ecommerce.agents.base import BaseAgent
from tiktok_ecommerce.categories.base import CategoryProfile
from tiktok_ecommerce.common.chunking import split_documents
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.crawlers.base import ProductCrawler
from tiktok_ecommerce.models.product import Product
from tiktok_ecommerce.rag.base import VectorStore

logger = get_logger(__name__)


class CrawlerAgent(BaseAgent):
    """采集 Agent。"""

    name = "crawler_agent"
    description = "采集 TikTok 竞品商品与评论，按品类过滤后清洗切片写入向量知识库"

    def __init__(
        self,
        crawler: ProductCrawler,
        vector_store: VectorStore,
        embedding_fn: Callable[[str], list[float]],
        max_products: int = 3,
        chunk_size: int = 300,
        chunk_overlap: int = 30,
        category: CategoryProfile | None = None,
    ):
        self.crawler = crawler
        self.vector_store = vector_store
        self.embedding_fn = embedding_fn
        self.max_products = max_products
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.category = category or CategoryProfile()

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        query = state["query"]
        region = state.get("region", "JP")
        logger.info("[%s] 开始采集: %s (%s)", self.name, query, region)

        # 1. 搜索竞品列表（数据源由工厂按配置注入：sample / api / direct）
        products = self.crawler.search_products(query, limit=self.max_products)
        if not products:
            # 数据真实性原则：采集不到就如实返回空并告警，绝不伪造商品
            logger.warning("[%s] 未采集到商品，请检查数据源配置或关键词: %s", self.name, query)
            return {"products": [], "region": region}

        # 1.5 品类过滤：用户未指定品类时只保留本品类商品（床上用品默认）
        kept, dropped = self._filter_by_category(products)
        if dropped:
            logger.info("[%s] 品类过滤: 保留 %d / 剔除 %d（非%s示例: %s）",
                        self.name, len(kept), len(dropped),
                        self.category.display_name, dropped[0].title[:30])
        if not kept:
            # 数据真实性原则：过滤后为空 → 如实返回空并附说明，绝不把非家纺当结果
            note = (f"搜到的 {len(products)} 个商品都不是{self.category.display_name}"
                    f"（如「{dropped[0].title[:40]}」），已按品类过滤。"
                    f"建议明确家纺品名再问，例如：帮我分析 ボックスシーツ 冬用 能不能卖")
            logger.warning("[%s] %s", self.name, note)
            return {"products": [], "region": region, "filtered_note": note}

        # 2. Top1 竞品补拉真实评论（SocialCrawl 支持 1 credit/页；其他数据源无此能力自动跳过）
        #    → 生命周期判断/评论洞察/RAG 检索全部基于真实评论，不靠猜测
        top = kept[0]
        fetcher = getattr(self.crawler, "fetch_reviews", None)
        if fetcher and not top.reviews and top.id:
            try:
                top.reviews = fetcher(top.id, max_comments=10)
                logger.info("[%s] Top1 竞品补拉评论 %d 条（product_id=%s）",
                            self.name, len(top.reviews), top.id)
            except Exception as e:
                logger.warning("[%s] Top1 评论拉取失败，跳过（不阻断选品）: %s", self.name, e)

        # 3. 逐商品入库（评论 + 描述 → 向量库）
        for p in kept:
            self._ingest(p)

        return {"products": kept, "region": region,
                "filtered_note": f"已按{self.category.display_name}品类过滤（保留 {len(kept)} 条）"}

    def _filter_by_category(self, products: list[Product]) -> tuple[list[Product], list[Product]]:
        """按品类判定词过滤：命中任一即保留；无判定词的品类不过滤。"""
        kept, dropped = [], []
        for p in products:
            title = getattr(p, "title", "") or ""
            if self.category.matches_category(title):
                kept.append(p)
            else:
                dropped.append(p)
        return kept, dropped

    def _ingest(self, product: Product) -> None:
        pairs = product.to_embedding_texts()
        if not pairs:
            return
        texts = [t for t, _ in pairs]
        metadatas = [m for _, m in pairs]
        # 长文本切片（短评论保持整块），切片继承元数据并标注 chunk_index
        texts, metadatas = split_documents(
            texts, metadatas, self.chunk_size, self.chunk_overlap
        )
        if not texts:
            return
        self.vector_store.insert(texts, metadatas, embedding_fn=self.embedding_fn)
        logger.info("已入库 %d 个切片（商品: %s）", len(texts), product.title)
