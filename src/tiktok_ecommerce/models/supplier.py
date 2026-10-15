"""货源与上架素材模型。"""
from pydantic import BaseModel, Field

from tiktok_ecommerce.common.text import parse_price


class SupplierOffer(BaseModel):
    """一条国内货源（数据必须来自真实网页，禁止 LLM 编造）。"""

    title: str = Field(..., min_length=1)
    price: str = Field("", description="供货价，如 ¥12.50")
    min_order: str = Field("", description="起订量，如 2 件")
    delivery: str = Field("", description="发货时效，如 48小时发货")
    supplier_name: str = Field("", description="供应商")
    url: str = ""
    images: list[str] = Field(
        default_factory=list,
        description="货源商品图 URL（如找家纺 goods_image，用于以图对比）",
    )
    match_score: float = Field(0.0, ge=0, le=1, description="与商品特征的匹配分数")
    score_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="打分明细（title_hit/price/min_order/delivery/jp_match/brand/"
                    "visual），可解释每个维度",
    )

    @property
    def price_value(self) -> float:
        """供货价数值（用于比价/利润测算，解析失败为 0.0）。"""
        return parse_price(self.price)


class ListingPackage(BaseModel):
    """④ 上架素材包（文案 + 规格翻译 + 图片清单）。

    日本站主推：title/keywords/description 默认日语；
    translated_title 为副语言（默认英语）标题；
    specs_translated 为规格日语化（如 size 1.8m → ダブル(140×200)），
    上架时 SKU/规格直接可用。
    """

    title: str = Field("", description="主语言标题（默认日语）")
    keywords: list[str] = Field(default_factory=list, description="主语言搜索关键词（默认日语）")
    description: str = Field("", description="主语言商品描述（默认日语）")
    translated_title: str = Field("", description="副语言标题（默认英语，供多语言店铺参考）")
    hashtags: list[str] = Field(default_factory=list)
    specs_translated: dict[str, str] = Field(
        default_factory=dict,
        description="规格日语化结果，如 {size: セミダブル(120x200cm), material: 綿100%}",
    )
    images: list[str] = Field(default_factory=list, description="处理后的图片路径列表")

    def to_csv_row(self) -> dict:
        """转成可直接导入上架工具/表格的一行（键为中文表头）。"""
        return {
            "商品标题": self.title,
            "关键词": " ".join(self.keywords),
            "商品描述": self.description,
            "副语言标题": self.translated_title,
            "标签": " ".join(self.hashtags),
            "规格(日语)": "；".join(f"{k}={v}" for k, v in self.specs_translated.items()),
        }
