"""报告服务：把流水线结果落盘为 Markdown/JSON。"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

from tiktok_ecommerce.common.logging import get_logger

logger = get_logger(__name__)


class ReportService:
    """结果落盘服务。"""

    def __init__(self, output_dir: Path):
        self.reports_dir = output_dir / "reports"
        self.reports_dir.mkdir(parents=True, exist_ok=True)

    def save(self, result: dict[str, Any], product_title: str) -> Path:
        """保存 JSON + Markdown 双格式，返回 JSON 路径。"""
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe = "".join(c for c in product_title if c.isalnum() or c in "-_")[:40] or "product"

        json_path = self.reports_dir / f"{safe}_{stamp}.json"
        json_path.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str),
                             encoding="utf-8")

        md_path = self.reports_dir / f"{safe}_{stamp}.md"
        md_path.write_text(self._to_markdown(result), encoding="utf-8")

        logger.info("报告已保存: %s", json_path)
        return json_path

    @staticmethod
    def _to_markdown(result: dict[str, Any]) -> str:
        lines = ["# 选品全链路报告", f"- 生成时间: {datetime.now().isoformat()}"]
        report = result.get("report")
        if report:
            lines += ["", "## 选品评估", str(report)]
        offers = result.get("offers")
        if offers:
            lines += ["", "## 货源对比"]
            for o in offers:
                lines.append(
                    f"- [{o.match_score}] {o.title} | {o.price} | {o.min_order} | {o.delivery}"
                )
        if result.get("listing_path"):
            lines += ["", f"## 上架素材包\n{result['listing_path']}"]
        return "\n".join(lines)
