"""真实数据源连通性验证脚本（企业级数据健康检查）。

用法（项目根目录、激活 venv）：
    python scripts\\verify_data_source.py                 # 免费项：找家纺网 + 样本
    python scripts\\verify_data_source.py --fastmoss      # 加测 FastMoss（$0.01/次，需 Key）
    python scripts\\verify_data_source.py --socialcrawl   # 加测 SocialCrawl（1 credit/次，免费100额度）
    python scripts\\verify_data_source.py --tikhub        # 加测 TikHub（$0.001/次，需 Key）

检查项：
  [1] 找家纺网直连：调用 api-pl-mobile.zhaojiafang.com 搜索 API → 真实货源（免费）
  [2] FastMoss（可选）：POST /product/v1/search（需充值配额）
  [3] SocialCrawl（可选）：GET /v1/tiktokshop/search（需 SOCIALCRAWL_API_KEY）
  [4] TikHub（可选）：GET /api/v1/tiktok/shop/web/fetch_search_products_list_v2（需 TIKHUB_API_KEY）
  [5] 本地样本就绪：data/samples 关键文件存在（离线兜底）

输出：逐项 PASS/FAIL + 下一步操作指引。
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tiktok_ecommerce.config import get_settings
from tiktok_ecommerce.crawlers.factory import build_http_client, get_supplier_crawler
from tiktok_ecommerce.crawlers.fastmoss import FASTMOSS_API_BASE, FastMossProductCrawler
from tiktok_ecommerce.crawlers.socialcrawl import SOCIALCRAWL_API_BASE, SocialCrawlProductCrawler
from tiktok_ecommerce.crawlers.tikhub import TIKHUB_API_BASE, TikHubProductCrawler

PASS, FAIL = "[PASS]", "[FAIL]"


def check_jiafang(settings, idx: int, total: int) -> bool:
    """真实调用找家纺网搜索 API 并解析货源。"""
    print(f"\n[{idx}/{total}] 找家纺网直连（免费，真实 API）...")
    client = build_http_client(settings)
    crawler = get_supplier_crawler(settings, source="jiafang", client=client)
    try:
        offers = crawler.search_offers(["床笠 四件套"], top_n=5)
    except Exception as e:
        print(f"{FAIL} 找家纺网抓取失败: {e}")
        return False
    if not offers:
        print(f"{FAIL} 找家纺网返回 0 条（可能接口改版或关键词无结果）")
        return False
    print(f"{PASS} 抓到 {len(offers)} 条真实货源，样例：")
    for o in offers[:3]:
        print(f"    · {o.title[:40]} | {o.price} | {o.supplier_name[:24]} | {o.min_order}")
    return True


def check_fastmoss(settings, region: str, idx: int, total: int) -> bool:
    """调用 FastMoss 商品搜索接口（消耗约 $0.01 配额，需已注册充值）。"""
    key = settings.crawler.third_party_product_api_key
    if not key:
        print(f"\n[{idx}/{total}] FastMoss OpenAPI（region={region}）...")
        print(f"{FAIL} 未配置 THIRD_PARTY_PRODUCT_API_KEY，跳过 FastMoss")
        print("      申请方式: 见 docs/HOW_TO_GET_DATA.md（注册→Console 创建 client_secret）")
        return False
    print(f"\n[{idx}/{total}] FastMoss OpenAPI（region={region}，消耗约 $0.01 配额）...")
    client = build_http_client(settings)
    crawler = FastMossProductCrawler(
        client, api_key=key, region=region,
        api_base=settings.crawler.third_party_product_api_base or FASTMOSS_API_BASE,
    )
    try:
        products = crawler.search_products("ボックスシーツ", limit=3)
    except Exception as e:
        print(f"{FAIL} FastMoss 调用失败: {e}")
        print("      常见原因：配额不足 / Key 无效 / 网络。Key 在 Console 创建，充值在开发者中心")
        return False
    if not products:
        print(f"{FAIL} FastMoss 返回 0 条（该关键词当日无数据，不计费）")
        return False
    print(f"{PASS} FastMoss 连通，返回 {len(products)} 条真实商品：")
    for p in products[:3]:
        print(f"    · {p.title[:40]} | {p.price} | 销量 {p.sales}")
    return True


def check_socialcrawl(settings, region: str, idx: int, total: int) -> bool:
    """调用 SocialCrawl 商品搜索接口（1 credit/次，新账号 100 credits 免费）。"""
    key = settings.crawler.socialcrawl_api_key
    if not key:
        print(f"\n[{idx}/{total}] SocialCrawl（region={region}）...")
        print(f"{FAIL} 未配置 SOCIALCRAWL_API_KEY，跳过 SocialCrawl")
        print("      申请方式: socialcrawl.dev 注册（送 100 credits，无信用卡）→ Dashboard 生成 x-api-key")
        return False
    print(f"\n[{idx}/{total}] SocialCrawl TikTok Shop（region={region}，消耗 1 credit）...")
    client = build_http_client(settings)
    crawler = SocialCrawlProductCrawler(
        client, api_key=key, region=region,
        api_base=settings.crawler.socialcrawl_base_url or SOCIALCRAWL_API_BASE,
    )
    try:
        products = crawler.search_products("ボックスシーツ", limit=3)
    except Exception as e:
        print(f"{FAIL} SocialCrawl 调用失败: {e}")
        print("      常见原因：Key 无效 / 区域不支持 / 该词无结果（失败自动退款）")
        return False
    if not products:
        print(f"{FAIL} SocialCrawl 返回 0 条（该关键词无结果，不计费）")
        return False
    print(f"{PASS} SocialCrawl 连通，返回 {len(products)} 条真实商品：")
    for p in products[:3]:
        print(f"    · {p.title[:40]} | {p.price} {p.currency}")
    return True


def check_tikhub(settings, region: str, idx: int, total: int) -> bool:
    """调用 TikHub 商品搜索接口（$0.001/次，新号送 $0.05）。"""
    key = settings.crawler.tikhub_api_key
    if not key:
        print(f"\n[{idx}/{total}] TikHub（region={region}）...")
        print(f"{FAIL} 未配置 TIKHUB_API_KEY，跳过 TikHub")
        print("      申请方式: user.tikhub.io/dashboard/api 生成 Bearer Token（新号送 $0.05）")
        return False
    print(f"\n[{idx}/{total}] TikHub TikTok Shop（region={region}，消耗约 $0.001）...")
    client = build_http_client(settings)
    crawler = TikHubProductCrawler(
        client, api_key=key, region=region,
        api_base=settings.crawler.tikhub_base_url or TIKHUB_API_BASE,
    )
    try:
        products = crawler.search_products("ボックスシーツ", limit=3)
    except Exception as e:
        print(f"{FAIL} TikHub 调用失败: {e}")
        print("      常见原因：Key 无效 / 搜索区域官方未列 JP（日本站搜索建议 socialcrawl/fastmoss）")
        return False
    if not products:
        print(f"{FAIL} TikHub 返回 0 条（该关键词无结果）")
        return False
    print(f"{PASS} TikHub 连通，返回 {len(products)} 条真实商品：")
    for p in products[:3]:
        print(f"    · {p.title[:40]} | {p.price} {p.currency} | 销量 {p.sales}")
    return True


def check_samples(settings, idx: int, total: int) -> bool:
    """本地样本兜底检查。"""
    print(f"\n[{idx}/{total}] 本地样本就绪（离线兜底）...")
    ok = True
    for name in ("products_jp_bedding.json", "suppliers_jiafang_bedding.json"):
        p = settings.crawler.sample_dir / name
        if not p.exists():
            print(f"{FAIL} 缺少样本 {name}")
            ok = False
    if ok:
        print(f"{PASS} 样本齐全，PRODUCT_SOURCE/SUPPLIER_SOURCE=sample 可离线跑全流程")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(description="真实数据源连通性验证")
    parser.add_argument("--fastmoss", action="store_true", help="同时验证 FastMoss（$0.01/次）")
    parser.add_argument("--socialcrawl", action="store_true", help="同时验证 SocialCrawl（1 credit/次，免费100额度）")
    parser.add_argument("--tikhub", action="store_true", help="同时验证 TikHub（$0.001/次）")
    args = parser.parse_args()

    settings = get_settings()
    region = settings.crawler.fastmoss_region

    # 动态计算检查项编号
    checks = []
    checks.append(lambda idx, total: check_jiafang(settings, idx, total))
    if args.fastmoss:
        checks.append(lambda idx, total: check_fastmoss(settings, region, idx, total))
    if args.socialcrawl:
        checks.append(lambda idx, total: check_socialcrawl(settings, region, idx, total))
    if args.tikhub:
        checks.append(lambda idx, total: check_tikhub(settings, region, idx, total))
    checks.append(lambda idx, total: check_samples(settings, idx, total))

    total = len(checks)
    print("=" * 60)
    print("tiktok-ecommerce-agent · 真实数据源验证")
    print("=" * 60)

    results = [fn(i, total) for i, fn in enumerate(checks, start=1)]

    print("\n" + "=" * 60)
    if all(results):
        print("结果: 全部通过 ✔ 真实数据链路已就绪")
        print("下一步: 在 .env 设置 PRODUCT_SOURCE=socialcrawl（免费验证）/ fastmoss / tikhub，")
        print("       SUPPLIER_SOURCE=jiafang（找家纺网）后跑 demo_pipeline")
    else:
        print("结果: 存在未通过项，按上方 FAIL 提示处理后重跑")
    print("=" * 60)
    return 0 if all(results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
