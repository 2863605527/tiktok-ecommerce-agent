"""流水线集成冒烟测试（用 Fake 组件跑通全流程，无需真实依赖）。"""
import pytest

from tiktok_ecommerce.agents.analyzer_agent import AnalyzerAgent
from tiktok_ecommerce.agents.crawler_agent import CrawlerAgent
from tiktok_ecommerce.agents.listing_agent import ListingAgent
from tiktok_ecommerce.agents.sourcing_agent import SourcingAgent
from tiktok_ecommerce.image_processing.processor import ImageProcessor
from tiktok_ecommerce.models.supplier import SupplierOffer
from tiktok_ecommerce.pipelines.selection import SelectionPipeline
from tiktok_ecommerce.rag.retriever import Retriever


class FakeCrawler:
    def search_products(self, keyword, limit=5):
        from tiktok_ecommerce.models.product import Product, Review

        return [
            Product(title=keyword, price="9.99", description="demo",
                    reviews=[Review(content="good value")])
        ]

    def fetch_product(self, url):
        from tiktok_ecommerce.models.product import Product

        return Product(title="demo", price="", url=url)


class FakeSupplier:
    def search_offers(self, keywords, top_n=10):
        return [SupplierOffer(title="demo supplier", price="¥5", min_order="2件")]


@pytest.mark.integration
def test_pipeline_full_flow(fake_store, fake_llm):
    embedding = lambda t: [0.1] * 8  # noqa: E731

    pipeline = SelectionPipeline(
        crawler_agent=CrawlerAgent(FakeCrawler(), fake_store, embedding),
        analyzer_agent=AnalyzerAgent(Retriever(fake_store, embedding, top_k=2), fake_llm),
        sourcing_agent=SourcingAgent(FakeSupplier(), fake_llm, top_n=5),
        listing_agent=ListingAgent(ImageProcessor(width=10, height=10), fake_llm,
                                   output_dir=__import__("pathlib").Path("output/listings")),
    )
    result = pipeline.run(query="earbuds", region="US")
    assert result.get("report") is not None
    assert result.get("offers")  # 至少 1 条货源
    assert result.get("listing") is not None
