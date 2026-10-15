"""选品结果库 + 素材 ZIP 打包 API 测试。"""
from __future__ import annotations

import json
import sys
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from tiktok_ecommerce.storage.selection_store import SelectionStore  # noqa: E402


@pytest.fixture()
def store(tmp_path):
    return SelectionStore(tmp_path / "test.db")


def test_save_and_list(store):
    rec = store.save(user_id=1, product="ボックスシーツ 冬用", region="JP",
                     category="bedding", language="ja",
                     result={"products": [], "offers": []})
    assert rec.id >= 1
    assert rec.status == "ok"
    items = store.list_for_user(1)
    assert len(items) == 1
    assert items[0].product == "ボックスシーツ 冬用"
    assert items[0].result["offers"] == []
    # 用户隔离
    assert store.list_for_user(2) == []


def test_save_error_status(store):
    rec = store.save(user_id=1, product="x", region="JP", category="bedding",
                     language="ja", result={"error": "boom"}, status="error")
    assert rec.status == "error"
    assert rec.result["error"] == "boom"


def test_delete_own_only(store):
    store.save(user_id=1, product="A", region="JP", category="bedding", language="ja", result={})
    store.save(user_id=2, product="B", region="JP", category="bedding", language="ja", result={})
    items1 = store.list_for_user(1)
    store.delete(items1[0].id, user_id=1)
    assert store.list_for_user(1) == []
    assert len(store.list_for_user(2)) == 1
    # 无权删除他人记录
    from tiktok_ecommerce.common.exceptions import UnauthorizedError
    with pytest.raises(UnauthorizedError):
        store.delete(store.list_for_user(2)[0].id, user_id=1)


def test_get_raises_not_found(store):
    from tiktok_ecommerce.common.exceptions import NotFoundError
    with pytest.raises(NotFoundError):
        store.get(999, user_id=1)


def test_order_desc(store):
    store.save(user_id=1, product="p1", region="JP", category="bedding", language="ja", result={})
    store.save(user_id=1, product="p2", region="JP", category="bedding", language="ja", result={})
    items = store.list_for_user(1)
    assert items[0].product == "p2" and items[1].product == "p1"


# ---- API 层（依赖覆盖 FakeUser） ----

@pytest.fixture()
def client(tmp_path, monkeypatch):
    from tiktok_ecommerce.api.app import create_app
    from tiktok_ecommerce.config import Settings

    class _FakeUser:
        id = 1
        username = "tester"

    class _Overrides:
        def __init__(self):
            self.store = SelectionStore(tmp_path / "api.db")

        def fake_user(self):
            return _FakeUser()

        def fake_store(self):
            return self.store

    app = create_app()
    ov = _Overrides()
    app.dependency_overrides[
        __import__("tiktok_ecommerce.api.v1.selection", fromlist=["get_current_user"]).get_current_user
    ] = ov.fake_user
    app.dependency_overrides[
        __import__("tiktok_ecommerce.api.v1.selection", fromlist=["get_selection_store"]).get_selection_store
    ] = ov.fake_store
    app.dependency_overrides[
        __import__("tiktok_ecommerce.api.v1.listings", fromlist=["get_current_user"]).get_current_user
    ] = ov.fake_user
    return TestClient(app), ov


def test_history_api_save_list_delete(client):
    c, ov = client
    r = c.post("/api/v1/selections/history", json={
        "product": "牛奶绒床笠", "region": "JP", "category": "bedding",
        "language": "ja", "result": {"offers": [{"title": "x"}]}, "status": "ok",
    })
    assert r.status_code == 200
    rid = r.json()["id"]

    r = c.get("/api/v1/selections/history")
    assert r.status_code == 200
    assert len(r.json()) == 1
    assert r.json()[0]["result"]["offers"][0]["title"] == "x"

    r = c.delete(f"/api/v1/selections/history/{rid}")
    assert r.status_code == 200 and r.json()["ok"] is True
    assert c.get("/api/v1/selections/history").json() == []


def test_listing_package_zip(client, tmp_path, monkeypatch):
    """打包：listing.json + 图片 → ZIP；路径穿越被拒绝。"""
    c, ov = client
    # 造一个真实 listing.json
    from tiktok_ecommerce.config import get_settings
    out = get_settings().output_dir / "listings" / "テスト商品"
    out.mkdir(parents=True, exist_ok=True)
    (out / "listing.json").write_text(
        json.dumps({"title": "テスト", "keywords": ["ふわふわ"]}, ensure_ascii=False),
        encoding="utf-8",
    )
    rel = f"listings/テスト商品/listing.json"
    r = c.post("/api/v1/listings/package", json={"listing_path": rel, "image_urls": []})
    assert r.status_code == 200
    assert r.headers["content-type"] == "application/zip"
    zf = zipfile.ZipFile(__import__("io").BytesIO(r.content))
    assert "listing.json" in zf.namelist()
    assert json.loads(zf.read("listing.json"))["title"] == "テスト"

    # 路径穿越被拒绝
    r2 = c.post("/api/v1/listings/package",
                json={"listing_path": "../../.env", "image_urls": []})
    assert r2.status_code in (400, 422)

    # 不存在的路径
    r3 = c.post("/api/v1/listings/package",
                json={"listing_path": "listings/不存在/listing.json", "image_urls": []})
    assert r3.status_code in (400, 422)
