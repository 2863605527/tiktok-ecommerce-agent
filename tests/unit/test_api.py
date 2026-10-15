"""第九步 API 冒烟测试：健康检查、品类列表、选品接口（依赖替换为 Fake，全离线）。

鉴权说明：选品/聊天接口已加 JWT 鉴权，测试用临时 SQLite 用户库 +
   真实注册拿 token（不污染项目 data/app.db）。
"""
from __future__ import annotations

import pathlib
import tempfile

from fastapi.testclient import TestClient

from tiktok_ecommerce.api.app import create_app
from tiktok_ecommerce.api.v1.auth import get_user_store
from tiktok_ecommerce.api.v1.selection import resolve_pipeline
from tiktok_ecommerce.auth.store import UserStore
from tiktok_ecommerce.models.report import SelectionReport
from tiktok_ecommerce.models.supplier import ListingPackage, SupplierOffer


class FakePipeline:
    """测试用流水线：返回固定结果，不触发 LLM/向量库。"""

    def run(self, **kwargs) -> dict:
        return {
            "products": [{"id": "p1", "title": "ボックスシーツ"}],
            "report": SelectionReport(
                summary="纯棉床笠适合日本站", pros=["触感好"], cons=["缩水"],
                market_hot="高", competition="中", risks=[], suggestion="建议售卖",
                keywords=["床笠"], insights=[],
            ),
            "offers": [SupplierOffer(title="日式床笠 工厂直供", price="¥18.50",
                                     min_order="2件", delivery="48小时", supplier_name="南通厂")],
            "listing": ListingPackage(title="テスト商品", keywords=["ボックスシーツ"],
                                      description="説明", translated_title="Test"),
            "listing_path": "output/listings/test/listing.json",
            "error": None,
        }


_TMP_DB = pathlib.Path(tempfile.mkdtemp()) / "test_api.db"
app = create_app()
app.dependency_overrides[resolve_pipeline] = lambda: FakePipeline()
app.dependency_overrides[get_user_store] = lambda: UserStore(_TMP_DB)
client = TestClient(app)

_ACCESS_TOKEN: str | None = None


def _auth_token() -> str:
    """注册临时测试用户并返回 token（只注册一次）。"""
    global _ACCESS_TOKEN
    if _ACCESS_TOKEN:
        return _ACCESS_TOKEN
    r = client.post("/api/v1/auth/register", json={
        "username": "api_tester", "email": "api_tester@x.com", "password": "Passw0rd1"})
    assert r.status_code == 201, r.text
    _ACCESS_TOKEN = r.json()["access_token"]
    return _ACCESS_TOKEN


def _headers() -> dict:
    return {"Authorization": f"Bearer {_auth_token()}"}


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"


def test_categories_include_bedding():
    r = client.get("/api/v1/categories")
    assert r.status_code == 200
    names = [c["name"] for c in r.json()]
    assert "bedding" in names  # 床上用品（主推品类）已注册


def test_selection_endpoint_full_flow():
    r = client.post("/api/v1/selections", json={
        "product": "ボックスシーツ 綿100%",
        "region": "JP",
        "category": "bedding",
        "language": "ja",
        "stages": ["crawler", "analyzer", "sourcing", "listing"],
    }, headers=_headers())
    assert r.status_code == 200
    data = r.json()
    assert data["products"]
    assert data["report"]["summary"]
    assert data["offers"][0]["title"].startswith("日式")
    assert data["listing"]["title"] == "テスト商品"
    assert data["listing_path"].endswith(".json")


def test_selection_endpoint_validation():
    """product 为空 → 422 校验错误（先过鉴权，再被 Pydantic 拦下）。"""
    r = client.post("/api/v1/selections", json={"product": "", "region": "JP"},
                    headers=_headers())
    assert r.status_code == 422


def test_runtime_config_endpoint():
    """运行配置接口：返回数据源状态且密钥已脱敏。"""
    r = client.get("/api/v1/config")
    assert r.status_code == 200
    data = r.json()
    # 字段存在且类型正确
    assert "product_source" in data
    assert "supplier_source" in data
    assert "rag_backend" in data
    assert "has_fastmoss_key" in data
    assert "fastmoss_key_masked" in data
    assert "jiafang_base_url" in data
    # 脱敏规则：masked 中不含完整密钥、含掩码字符
    if data["fastmoss_key_masked"]:
        assert "****" in data["fastmoss_key_masked"]
