"""商品与评论模型。"""
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from tiktok_ecommerce.common.text import parse_price


def _utcnow() -> datetime:
    """时区感知的 UTC 当前时间（Python 3.12+ 弃用 naive utcnow）。"""
    return datetime.now(timezone.utc)


class Review(BaseModel):
    """一条用户评论。"""

    content: str = Field(..., min_length=1, max_length=1000, description="评论文本")
    rating: float = Field(0.0, ge=0, le=5, description="评分（0-5）")
    helpful_count: int = Field(0, ge=0, description="点赞/有用数")
    author: str | None = Field(None, description="评论者（脱敏后）")
    created_at: datetime | None = Field(None, description="评论时间")
    raw: str | None = Field(None, description="原始文本（调试用）")


class Product(BaseModel):
    """TikTok 商品。"""

    id: str = Field("", description="商品 ID（平台唯一标识，可为空字符串）")
    title: str = Field(..., min_length=1, max_length=500)
    price: str = Field("", description="价格原始字符串，如 9.99 / ¥1,200 / 1,200円")
    currency: str = Field("USD", max_length=10)
    url: str = Field("", description="商品链接")
    description: str = Field("", max_length=5000)
    sales: int = Field(0, ge=0, description="销量（部分数据源不返回，如 SocialCrawl JP 搜索卡，此时为 0 表示未披露）")
    rating: float | None = Field(None, ge=0, le=5, description="商品评分（热度代理指标，可为空）")
    reviews_count: int | None = Field(None, ge=0, description="评论数（热度代理指标，可为空）")
    seller: str = Field("", max_length=200, description="店铺/卖家名")
    brand: str = Field("", max_length=200, description="品牌")
    availability: str = Field("", max_length=50, description="库存状态（如 in_stock/out_of_stock）")
    category: str = Field("", max_length=100)
    specs: dict[str, str] = Field(
        default_factory=dict,
        description='规格参数，床上用品如 {"size": "1.8m", "material": "纯棉", "color": "ホワイト"}',
    )
    tags: list[str] = Field(default_factory=list)
    images: list[str] = Field(
        default_factory=list,
        description="商品图 URL 列表（如 SocialCrawl image_urls，用于以图找货）",
    )
    reviews: list[Review] = Field(default_factory=list)
    collected_at: datetime = Field(default_factory=_utcnow)

    @property
    def price_value(self) -> float:
        """价格数值（解析失败为 0.0，调用方据此判脏数据）。"""
        return parse_price(self.price)

    def review_texts(self) -> list[str]:
        """返回清洗后的评论文本列表（供 RAG 入库）。"""
        return [r.content.strip() for r in self.reviews if r.content.strip()]

    def to_embedding_texts(self) -> list[tuple[str, dict[str, Any]]]:
        """生成入库文本 + 元数据对。

        Returns:
            list[(text, metadata)]：评论和描述都会生成
        """
        pairs: list[tuple[str, dict[str, Any]]] = []
        for r in self.reviews:
            if r.content.strip():
                pairs.append((
                    r.content.strip(),
                    {"source": "tiktok", "product_id": self.id, "title": self.title,
                     "source_type": "review", "type": "review",
                     "rating": r.rating, "url": self.url},
                ))
        if self.description.strip():
            pairs.append((
                self.description.strip(),
                {"source": "tiktok", "product_id": self.id, "title": self.title,
                 "source_type": "description", "type": "description",
                 "url": self.url},
            ))
        return pairs
