"""CLI 入口（click）：run-selection / serve 等命令。

用法：
    pip install -e ".[dev]"
    tiktok-agent run-selection --product "wireless earbuds" --region "US"
    tiktok-agent serve --port 8000
"""
from __future__ import annotations

import sys

import click
import uvicorn

from tiktok_ecommerce.common.logging import get_logger, setup_logging
from tiktok_ecommerce.config import get_settings

logger = get_logger(__name__)


@click.group()
def cli() -> None:
    """TikTok 跨境选品与上架全链路多 Agent 系统。"""
    settings = get_settings()
    setup_logging(settings.log_level)
    settings.ensure_dirs()


@cli.command("run-selection")
@click.option("--product", required=True, help="商品关键词或链接")
@click.option("--region", default="US", help="目标市场，如 US/UK/JP")
@click.option("--category", default="bedding", help="品类：bedding/electronics/apparel（默认床上用品）")
@click.option("--language", default="ja", help="上架文案语言：ja（默认日语）/en/es/fr/de/ko")
@click.option("--stages", default=None, help="流程阶段，逗号分隔：crawler,analyzer,sourcing,listing（默认全部）")
@click.option("--image-dir", default=None, help="商品图片目录（可选）")
def run_selection(product: str, region: str, category: str, language: str,
                  stages: str | None, image_dir: str | None) -> None:
    """运行选品流水线（可按品类 / 语言 / 阶段裁剪）。"""
    from tiktok_ecommerce.api.deps import get_pipeline
    from tiktok_ecommerce.services.report_service import ReportService

    settings = get_settings()
    enabled = tuple(s.strip() for s in stages.split(",")) if stages else None
    pipeline = get_pipeline(settings, category_name=category, enabled_stages=enabled)
    result = pipeline.run(query=product, region=region, image_dir=image_dir,
                          category=category, language=language)

    # 落盘报告
    report_service = ReportService(settings.output_dir)
    path = report_service.save(result, product)

    # 控制台摘要
    click.echo("\n========== 运行结果 ==========")
    if result.get("report"):
        click.echo("\n【选品评估】")
        click.echo(str(result["report"]))
    if result.get("offers"):
        click.echo("\n【货源对比】")
        for o in result["offers"]:
            click.echo(f"  [{o.match_score}] {o.title} | {o.price} | {o.min_order} | {o.delivery}")
    if result.get("listing_path"):
        click.echo(f"\n【素材包】{result['listing_path']}")
    click.echo(f"\n【报告】{path}")
    click.echo("=================================")


@cli.command("serve")
@click.option("--host", default="0.0.0.0", help="监听地址")
@click.option("--port", default=8000, help="监听端口")
def serve(host: str, port: int) -> None:
    """启动 FastAPI 服务。"""
    uvicorn.run(
        "tiktok_ecommerce.api.app:create_app",
        factory=True,
        host=host,
        port=port,
        reload=False,
    )


if __name__ == "__main__":
    sys.exit(cli())
