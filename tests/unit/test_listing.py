"""第七步 上架素材 Agent 单元测试：规格日语化、LLM 文案、JSON+CSV 保存、图片处理。"""
from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest
from PIL import Image

from tiktok_ecommerce.agents.listing_agent import ListingAgent
from tiktok_ecommerce.categories.bedding import BeddingProfile
from tiktok_ecommerce.image_processing.processor import ImageProcessor
from tiktok_ecommerce.models.product import Product, Review
from tiktok_ecommerce.models.report import SelectionReport
from tiktok_ecommerce.models.supplier import ListingPackage
from tests.conftest import FakeLLM


def _product() -> Product:
    return Product(
        id="7300000000001",
        title="ボックスシーツ 綿100% セミダブル",
        price="2,980円",
        currency="JPY",
        sales=12800,
        description="オーガニックコットン100%のボックスシーツ。",
        category="bedding",
        specs={"size": "1.8m", "material": "纯棉", "color": "白色", "feature": "防螨可水洗"},
        reviews=[Review(content="肌触りが良い。", rating=5.0)],
    )


LISTING_PAYLOAD = (
    '{"title": "オーガニックコットン ボックスシーツ セミダブル 全周ゴム 洗える",'
    ' "keywords": ["ボックスシーツ", "オーガニックコットン", "接触冷感"],'
    ' "description": "肌にやさしい綿100%のボックスシーツです。",'
    ' "translated_title": "Organic Cotton Fitted Sheet Semi-Double",'
    ' "hashtags": ["#ボックスシーツ", "#オーガニックコットン"]}'
)


def _agent(tmp_path: Path, llm: FakeLLM) -> ListingAgent:
    return ListingAgent(
        ImageProcessor(width=100, height=100, quality=80),
        llm=llm,
        output_dir=tmp_path,
        category=BeddingProfile(),
    )


class TestSpecTranslation:
    def test_size_material_color_mapping(self):
        result = ListingAgent._translate_value("1.8m")
        assert result == "ダブル(140×200)"
        assert ListingAgent._translate_value("纯棉") == "綿100%"
        assert ListingAgent._translate_value("白色") == "ホワイト"
        assert ListingAgent._translate_value("防螨可水洗") == "防ダニ洗える"

    def test_unknown_value_kept_unchanged(self):
        """规则未命中的规格值保留原值（不编造）。"""
        assert ListingAgent._translate_value("JIS規格") == "JIS規格"
        assert ListingAgent._translate_value("pima cotton") == "pima cotton"

    def test_translate_product_specs(self):
        specs = _agent(Path("."), FakeLLM(LISTING_PAYLOAD))._translate_specs(_product())
        assert specs["size"] == "ダブル(140×200)"
        assert specs["material"] == "綿100%"
        assert specs["color"] == "ホワイト"


class TestGenerateAndSave:
    def test_generate_copy_parses_listing(self, tmp_path):
        agent = _agent(tmp_path, FakeLLM(LISTING_PAYLOAD))
        listing = agent._generate_copy(_product(), SelectionReport(), "JP", "ja")
        assert isinstance(listing, ListingPackage)
        assert listing.title.startswith("オーガニックコットン")
        assert "ボックスシーツ" in listing.keywords

    def test_save_creates_json_and_csv(self, tmp_path):
        agent = _agent(tmp_path, FakeLLM(LISTING_PAYLOAD))
        listing = ListingPackage(**json.loads(LISTING_PAYLOAD))
        listing.specs_translated = {"size": "ダブル(140×200)", "material": "綿100%"}
        path = agent._save("テスト商品", listing)

        assert (tmp_path / "listing.json").is_file() or path.is_file()
        csv_path = Path(str(path).replace("listing.json", "listing.csv"))
        assert csv_path.is_file()
        with csv_path.open(encoding="utf-8-sig", newline="") as f:
            rows = list(csv.DictReader(f))
        assert rows and "商品标题" in rows[0]
        assert "ダブル(140×200)" in rows[0]["规格(日语)"]

    def test_run_full_flow(self, tmp_path):
        agent = _agent(tmp_path, FakeLLM(LISTING_PAYLOAD))
        out = agent.run({"products": [_product()], "region": "JP", "language": "ja"})
        listing = out["listing"]
        assert listing.specs_translated["material"] == "綿100%"
        assert out["listing_path"] and Path(out["listing_path"]).is_file()

    def test_run_no_products(self, tmp_path):
        agent = _agent(tmp_path, FakeLLM(LISTING_PAYLOAD))
        out = agent.run({})
        assert out["listing"] is None and "error" in out


class TestImages:
    def test_process_images_from_dir(self, tmp_path):
        src = tmp_path / "imgs"
        src.mkdir()
        img = Image.new("RGB", (200, 100), (255, 0, 0))
        img.save(src / "main.png")
        agent = _agent(tmp_path, FakeLLM(LISTING_PAYLOAD))
        paths = agent._process_images("商品A", str(src))
        assert len(paths) == 1 and Path(paths[0]).is_file()

    def test_missing_image_dir_returns_empty(self, tmp_path):
        agent = _agent(tmp_path, FakeLLM(LISTING_PAYLOAD))
        assert agent._process_images("商品A", None) == []
