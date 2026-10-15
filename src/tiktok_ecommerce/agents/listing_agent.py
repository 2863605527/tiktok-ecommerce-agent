"""④ 上架素材 Agent：生成上架文案（默认日语，可切换语言）+ 规格日语化 + 图片处理 → 素材包。

日本站主推：标题/关键词/描述默认用日语生成（贴近日本买家搜索习惯），
通过 language 参数可切换英语/西语等，给项目扩展空间。

规格日语化（解决"翻译太慢"痛点）：
- 规则层零成本：尺寸/材质/品类词中日映射（SIZE_MAP / SPEC_MAP），离线可测
- 规则未命中保留原值（不编造）；LLM 翻译为后续扩展点
产物：listing.json（完整素材）+ listing.csv（可直接导入上架工具/表格）。
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path
from typing import Any

from langchain_core.language_models import BaseChatModel

from tiktok_ecommerce.agents.base import BaseAgent
from tiktok_ecommerce.categories.base import CategoryProfile
from tiktok_ecommerce.common.exceptions import AgentError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.i18n.languages import (
    DEFAULT_LANGUAGE,
    SECONDARY_LANGUAGE,
    get_language,
    language_label,
)
from tiktok_ecommerce.image_processing.processor import ImageProcessor
from tiktok_ecommerce.models.product import Product
from tiktok_ecommerce.models.report import SelectionReport
from tiktok_ecommerce.models.supplier import ListingPackage

logger = get_logger(__name__)

LISTING_PROMPT = """你是TikTok Shop资深运营（日本站主推）。根据以下商品信息生成上架素材。

【商品】标题: {title} | 价格: {price} | 描述: {description}
【分析】总结: {summary} | 卖点: {pros}
【目标市场】{region}

{category_block}

【上架语言】主语言：{main_lang}（主语言生成全部文案）

【要求】
1. 标题：用{main_lang}生成，含核心卖点+场景+规格，30-50 字符
2. 关键词：10 个用{main_lang}搜索的买家搜索词（如日语：天然素材、接触冷感、防ダニ等类目习惯词）
3. 描述：3 段{main_lang}描述（卖点、规格、售后），口语化自然
4. translated_title：额外输出一份{alt_lang}标题（供多语言店铺参考）
5. 必须遵守【品类上架要求】中的规则
6. 输出严格 JSON：
{{
  "title": "{main_lang}标题",
  "keywords": ["{main_lang}关键词1", ...],
  "description": "{main_lang}描述",
  "translated_title": "{alt_lang}标题",
  "hashtags": ["#tag1", "#tag2", ...]
}}"""

# ---- 规格日语化规则层（零成本、离线、可测试）----
# 日本床尺寸：シングル100×200 / セミダブル120×200 / ダブル140×200 / クイーン170×210 / キング180×210
SIZE_MAP: dict[str, str] = {
    "1.2": "シングル(100×200)", "120": "シングル(100×200)", "120x200": "シングル(100×200)",
    "1.5": "セミダブル(120×200)", "150": "セミダブル(120×200)", "150x200": "セミダブル(120×200)",
    "1.8": "ダブル(140×200)", "180": "ダブル(140×200)", "180x200": "ダブル(140×200)",
    "2.0": "クイーン(170×210)", "200x220": "キング(180×210)",
}

SPEC_MAP: dict[str, str] = {
    # 品类词
    "床笠": "ボックスシーツ", "床单": "シーツ", "四件套": "4点セット",
    "被套": "掛け布団カバー", "枕套": "枕カバー",
    # 材质
    "纯棉": "綿100%", "全棉": "綿100%", "天丝": "テンセル", "磨毛": "起毛",
    "法兰绒": "フランネル", "水洗棉": "水洗い綿", "竹纤维": "竹繊維",
    "长绒棉": "長綿", "有机棉": "オーガニックコットン",
    # 功能
    "夏凉": "接触冷感", "空调被": "ひんやり", "防螨": "防ダニ",
    "抗菌": "抗菌", "可水洗": "洗える",
    # 颜色（通用色）
    "白色": "ホワイト", "灰色": "グレー", "粉色": "ピンク", "米白": "アイボリー",
    "浅蓝": "ライトブルー", "浅灰": "ライトグレー",
}

_JAPANESE_RE = re.compile(r"[\u3040-\u30ff\u4e00-\u9fff]")


class ListingAgent(BaseAgent):
    """上架素材生成 Agent。"""

    name = "listing_agent"
    description = "生成上架文案（默认日语）并做规格日语化与图片处理，输出素材包"

    def __init__(
        self,
        image_processor: ImageProcessor,
        llm: BaseChatModel,
        output_dir: Path,
        category: CategoryProfile | None = None,
        language: str = DEFAULT_LANGUAGE,
    ):
        self.image_processor = image_processor
        self.llm = llm
        self.output_dir = output_dir
        self.category = category or CategoryProfile()
        self.language = get_language(language)

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        products: list[Product] = state.get("products", [])
        if not products:
            return {"listing": None, "error": "没有商品信息"}

        product = products[0]
        report: SelectionReport | None = state.get("report")
        region = state.get("region", "JP")
        # 语言：state 优先（Web/CLI 传入），未传用构造默认（日语）
        language = get_language(state.get("language") or self.language)
        logger.info("[%s] 生成上架素材: %s（语言=%s）", self.name, product.title, language)

        listing = self._generate_copy(product, report, region, language)
        # 规格日语化（规则层，解决翻译慢痛点）
        listing.specs_translated = self._translate_specs(product)
        listing.images = self._process_images(product.title, state.get("image_dir"))

        path = self._save(product.title, listing)
        return {"listing": listing, "listing_path": str(path)}

    def _generate_copy(
        self, product: Product, report: SelectionReport | None, region: str,
        language: str,
    ) -> ListingPackage:
        main_lang = language_label(language)
        alt_lang = language_label(SECONDARY_LANGUAGE)
        prompt = LISTING_PROMPT.format(
            title=product.title,
            price=product.price,
            description=product.description or "暂无",
            summary=(report.summary if report else "") or "暂无",
            pros=", ".join(report.pros) if report else "",
            region=region,
            category_block=self.category.listing_prompt_block(region),
            main_lang=main_lang,
            alt_lang=alt_lang,
        )
        try:
            resp = self.llm.invoke(prompt)
            return ListingPackage(**self._parse_json(resp.content))
        except Exception as e:
            raise AgentError("素材生成失败", detail=str(e)) from e

    # ---------- 规格日语化 ----------
    def _translate_specs(self, product: Product) -> dict[str, str]:
        """把商品规格值翻译成日语（规则层）；未命中保留原值，绝不编造。"""
        translated: dict[str, str] = {}
        for key, value in product.specs.items():
            if not value:
                continue
            translated[key] = self._translate_value(value)
        if translated:
            logger.info("[%s] 规格日语化 %d 项", self.name, len(translated))
        return translated

    @classmethod
    def _translate_value(cls, value: str) -> str:
        """单个规格值的日语化：尺寸优先，其次逐词映射，未命中保留原值。"""
        v = value.strip()
        low = v.lower()
        # 1) 尺寸：命中日本床尺寸即输出日式规格
        for key, jp in SIZE_MAP.items():
            if key in low or low == key:
                return jp
        # 2) 材质/品类/颜色：逐词替换
        result = v
        for zh, jp in SPEC_MAP.items():
            if zh in result:
                result = result.replace(zh, jp)
        # 3) 已是日文则原样返回；规则未命中保留原值（不编造）
        return result if _JAPANESE_RE.search(result) or result != v else v

    def _process_images(self, product_title: str, src_dir: str | None) -> list[str]:
        """处理图片（本地目录；真实场景可替换为商品图 URL 下载扩展点）。"""
        if not src_dir or not Path(src_dir).is_dir():
            logger.info("未提供图片目录，跳过图片处理")
            return []
        dst = self.output_dir / self._safe_name(product_title) / "images"
        return self.image_processor.process_batch(Path(src_dir), dst)

    # ---------- 保存 ----------
    def _save(self, product_title: str, listing: ListingPackage) -> Path:
        folder = self.output_dir / self._safe_name(product_title)
        folder.mkdir(parents=True, exist_ok=True)
        json_path = folder / "listing.json"
        json_path.write_text(listing.model_dump_json(indent=2), encoding="utf-8")

        # CSV（utf-8-sig：Excel 直接打开不乱码，可导入上架工具）
        csv_path = folder / "listing.csv"
        with csv_path.open("w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(listing.to_csv_row().keys()))
            writer.writeheader()
            writer.writerow(listing.to_csv_row())

        logger.info("素材包已保存: %s（含 CSV）", json_path)
        return json_path

    @staticmethod
    def _parse_json(text: str) -> dict:
        from tiktok_ecommerce.common.text import extract_json
        data = extract_json(text)
        if not isinstance(data, dict):
            raise ValueError("素材输出应为 JSON 对象")
        return data

    @staticmethod
    def _safe_name(name: str) -> str:
        safe = re.sub(r"[^\w\-]", "", name)[:40]
        return safe or "product"
