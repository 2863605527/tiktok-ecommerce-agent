"""离线采集层演示：不依赖 API Key / Milvus，用本地样本跑通「商品采集 + 货源匹配打分」。

运行（项目根目录）：
    .venv\\Scripts\\python scripts\\demo_crawlers.py

用途：
- 验证第三步「可插拔采集层」是否正常（默认 source=sample）
- 演示数据入口：日本站床品竞品/评论 → 1688 货源打分（全程离线、可复现）
"""
from __future__ import annotations

import sys
from pathlib import Path

# 允许脱离 pip install 直接运行脚本
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from tiktok_ecommerce.agents.sourcing_agent import SourcingAgent  # noqa: E402
from tiktok_ecommerce.config import get_settings  # noqa: E402
from tiktok_ecommerce.crawlers.factory import (  # noqa: E402
    get_product_crawler,
    get_supplier_crawler,
)


def main() -> int:
    settings = get_settings()
    query = "ボックスシーツ 綿100%"

    print("=" * 64)
    print(f"商品数据源 = {settings.crawler.product_source} | 关键词: {query}")
    print("=" * 64)
    product_crawler = get_product_crawler(settings)
    products = product_crawler.search_products(query, limit=3)
    print(f"采集到 {len(products)} 个竞品\n")

    for i, p in enumerate(products, 1):
        print(f"[{i}] {p.title}")
        print(f"    价格 {p.price} | 销量 {p.sales} | 评论 {len(p.reviews)} 条")
        if p.specs:
            specs = " / ".join(f"{k}:{v}" for k, v in list(p.specs.items())[:4])
            print(f"    规格 {specs}")
        good = next((r for r in p.reviews if r.rating >= 4), None)
        bad = next((r for r in p.reviews if r.rating <= 2), None)
        if good:
            print(f"    好评({good.rating}): {good.content}")
        if bad:
            print(f"    差评({bad.rating}): {bad.content}")
        print()

    print("=" * 64)
    print("家纺货源匹配（91家纺风格样本，按关键词命中打分；1688 可在配置切换）")
    print("=" * 64)
    sourcing_keywords = ["纯棉", "床笠", "日式", "四件套", "跨境"]
    supplier_crawler = get_supplier_crawler(settings)
    offers = supplier_crawler.search_offers(sourcing_keywords, top_n=10)
    offers = SourcingAgent._score(offers, sourcing_keywords)
    for i, o in enumerate(offers, 1):
        print(f"[{i}] 匹配度 {o.match_score:.2f} | {o.price} | {o.title}")
        print(f"      {o.supplier_name} | {o.min_order} | {o.delivery}")

    print("\n演示完成。切换真实数据：在 .env 设置 PRODUCT_SOURCE=api 并填入第三方平台 Key。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
