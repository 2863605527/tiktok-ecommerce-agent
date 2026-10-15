"""API 依赖注入：组装流水线实例（懒加载单例）。"""
from __future__ import annotations

from tiktok_ecommerce.agents.analyzer_agent import AnalyzerAgent
from tiktok_ecommerce.agents.crawler_agent import CrawlerAgent
from tiktok_ecommerce.agents.listing_agent import ListingAgent
from tiktok_ecommerce.agents.sourcing_agent import SourcingAgent
from tiktok_ecommerce.categories.registry import get_category
from tiktok_ecommerce.common.llm import create_embedding_fn, create_llm
from tiktok_ecommerce.config import Settings, get_settings
from tiktok_ecommerce.crawlers.factory import get_product_crawler, get_supplier_crawler
from tiktok_ecommerce.image_processing.processor import ImageProcessor
from tiktok_ecommerce.pipelines.selection import SelectionPipeline
from tiktok_ecommerce.rag.factory import get_vector_store
from tiktok_ecommerce.rag.retriever import Retriever


# 手动缓存：key = (category_name, enabled_stages)
# 不用 lru_cache：Settings 对象不可哈希，无法作为 lru_cache 参数
_pipeline_cache: dict[tuple[str, tuple[str, ...] | None], SelectionPipeline] = {}


def get_pipeline(
    settings: Settings | None = None,
    category_name: str = "bedding",
    enabled_stages: tuple[str, ...] | None = None,
) -> SelectionPipeline:
    """构建选品流水线单例（按品类注入领域知识，按阶段裁剪）。

    settings 仅在首次构建时生效（.env 变更需重启进程）；
    缓存键为 (category_name, enabled_stages)，不同品类/阶段组合各自独立。
    """
    key = (category_name, enabled_stages)
    if key in _pipeline_cache:
        return _pipeline_cache[key]

    settings = settings or get_settings()
    category = get_category(category_name)

    llm = create_llm(settings)
    embedding_fn = create_embedding_fn(settings)

    # 检索后端走工厂：RAG_BACKEND = milvus | ragflow | memory
    store = get_vector_store(settings)
    retriever = Retriever(
        store, embedding_fn,
        top_k=settings.milvus.top_k,
        score_threshold=settings.milvus.score_threshold,
    )

    # 采集层走工厂：按 .env 的 PRODUCT_SOURCE / SUPPLIER_SOURCE 切换数据源
    product_crawler = get_product_crawler(settings, category=category_name)
    supplier_crawler = get_supplier_crawler(settings, category=category_name)
    # 运行时货源平台切换工厂（聊天说"去1688找货源"→ get_supplier_crawler(source="1688")）
    supplier_factory = lambda src: get_supplier_crawler(settings, source=src, category=category_name)  # noqa: E731

    pipeline = SelectionPipeline(
        crawler_agent=CrawlerAgent(
            product_crawler, store, embedding_fn,
            chunk_size=settings.pipeline.chunk_size,
            chunk_overlap=settings.pipeline.chunk_overlap,
            category=category,
        ),
        analyzer_agent=AnalyzerAgent(retriever, llm=llm, category=category),
        sourcing_agent=SourcingAgent(supplier_crawler, llm=llm,
                                     top_n=settings.pipeline.sourcing_top_n,
                                     category=category,
                                     supplier_factory=supplier_factory),
        listing_agent=ListingAgent(
            ImageProcessor(
                width=settings.pipeline.image_width,
                height=settings.pipeline.image_height,
                quality=settings.pipeline.image_quality,
            ),
            llm=llm,
            output_dir=settings.output_dir / "listings",
            category=category,
        ),
        enabled_stages=list(enabled_stages) if enabled_stages else None,
    )
    _pipeline_cache[key] = pipeline
    return pipeline
