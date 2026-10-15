"""第七步 上架素材演示：商品 → LLM 日语文案 + 规格日语化 → JSON+CSV 素材包。

运行（项目根目录，需真实 LLM Key）：
    .venv\\Scripts\\python scripts\\demo_listing.py
产物在 output/listings/<商品名>/ 下：listing.json（完整素材）+ listing.csv（可导入上架工具）。
语言默认日语，可用 --language en 切换（Web/CLI 可选）。
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiktok_ecommerce.agents.listing_agent import ListingAgent  # noqa: E402
from tiktok_ecommerce.categories.registry import get_category  # noqa: E402
from tiktok_ecommerce.common.llm import create_llm  # noqa: E402
from tiktok_ecommerce.config import get_settings  # noqa: E402
from tiktok_ecommerce.crawlers.factory import get_product_crawler  # noqa: E402
from tiktok_ecommerce.image_processing.processor import ImageProcessor  # noqa: E402


def main() -> int:
    s = get_settings()
    category = get_category(s.pipeline.default_category)
    language = sys.argv[1] if len(sys.argv) > 1 else "ja"
    print("=" * 72)
    print(f"第七步 上架素材 | 语言 = {language} | 品类 = {category.display_name}")
    print("=" * 72)

    # 1. 取一个样本商品（真实场景来自采集/分析结果）
    crawler = get_product_crawler(s, category=s.pipeline.default_category)
    product = crawler.search_products("ボックスシーツ 綿100%", limit=1)[0]
    print(f"商品: {product.title}")
    print(f"规格: {product.specs}\n")

    # 2. 生成上架素材
    agent = ListingAgent(
        ImageProcessor(
            width=s.pipeline.image_width,
            height=s.pipeline.image_height,
            quality=s.pipeline.image_quality,
        ),
        llm=create_llm(s),
        output_dir=s.output_dir / "listings",
        category=category,
        language=language,
    )
    out = agent.run({"products": [product], "region": "JP", "language": language})
    listing = out["listing"]
    if not listing:
        print("素材生成失败：", out.get("error"))
        return 1

    print("【日文标题】", listing.title)
    print("【关键词】", ", ".join(listing.keywords))
    print("【描述】", listing.description[:120], "...")
    print("【副语言标题】", listing.translated_title)
    print("【标签】", " ".join(listing.hashtags))
    if listing.specs_translated:
        print("\n【规格日语化】（规则层翻译，零成本）")
        for k, v in listing.specs_translated.items():
            print(f"   {k}: {v}")
    print("\n素材包已保存:")
    print(f"   JSON: {out['listing_path']}")
    print(f"   CSV : {Path(str(out['listing_path'])).with_name('listing.csv')}")
    print("=" * 72)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
