"""图片优化 API 测试：鉴权、参数校验、处理链路（下载→规格化→OCR降级）。

说明：
- 用 FastAPI TestClient + 临时用户库；
- 图片下载用真实可访问的图片 URL（本地 HTTP 服务器提供固定像素图，避免外网依赖）；
- OCR 走降级路径（不依赖 PaddleOCR 已安装），断言规格化产物存在。
"""
from __future__ import annotations

import pathlib
import tempfile
import threading

import pytest
from fastapi.testclient import TestClient
from http.server import BaseHTTPRequestHandler, HTTPServer

from tiktok_ecommerce.api.app import create_app
from tiktok_ecommerce.api.v1.auth import get_user_store
from tiktok_ecommerce.api.v1.selection import resolve_pipeline
from tiktok_ecommerce.auth.store import UserStore

# ---- 本地小图服务器：200x200 白色 PNG，供"下载图片"真实走通 ----
_IMG_BYTES: bytes | None = None


def _make_img() -> bytes:
    global _IMG_BYTES
    if _IMG_BYTES:
        return _IMG_BYTES
    from io import BytesIO
    from PIL import Image
    buf = BytesIO()
    # JPEG 200x200 纯色也有 2-3KB，能通过下载大小校验
    Image.new("RGB", (200, 200), (250, 250, 250)).save(buf, "JPEG", quality=90)
    _IMG_BYTES = buf.getvalue()
    return _IMG_BYTES


class _ImgHandler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        data = _make_img()
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):  # noqa: ARG002
        pass


@pytest.fixture(scope="module")
def img_server():
    srv = HTTPServer(("127.0.0.1", 0), _ImgHandler)
    port = srv.server_address[1]
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield f"http://127.0.0.1:{port}/img.png"
    srv.shutdown()


_TMP_DB = pathlib.Path(tempfile.mkdtemp()) / "test_images.db"
app = create_app()
app.dependency_overrides[resolve_pipeline] = lambda: FakePipelineStub()
app.dependency_overrides[get_user_store] = lambda: UserStore(_TMP_DB)
client = TestClient(app)


class FakePipelineStub:
    def run(self, **kwargs) -> dict:  # noqa: ARG002
        return {}


_TOKEN: str | None = None


def _token() -> str:
    global _TOKEN
    if _TOKEN:
        return _TOKEN
    r = client.post("/api/v1/auth/register", json={
        "username": "img_tester", "email": "img_tester@x.com", "password": "Passw0rd1"})
    assert r.status_code == 201, r.text
    _TOKEN = r.json()["access_token"]
    return _TOKEN


def _headers() -> dict:
    return {"Authorization": f"Bearer {_token()}"}


def test_requires_auth(img_server):
    r = client.post("/api/v1/images/process", json={"image_url": img_server})
    assert r.status_code == 401


def test_invalid_ratio(img_server):
    r = client.post("/api/v1/images/process", headers=_headers(),
                    json={"image_url": img_server, "ratio": "7:9"})
    assert r.status_code == 400


def test_process_real_image(img_server):
    r = client.post("/api/v1/images/process", headers=_headers(),
                    json={"image_url": img_server, "ratio": "1:1",
                          "white_bg": True, "bg_mode": "heuristic"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ratio"] == "1:1"
    assert d["white_bg"] is True
    assert d["bg_used"] in ("ai", "heuristic")  # 测试图浅灰底 → 启发式即可成白
    assert d["processed_path"]
    assert pathlib.Path(d["processed_path"]).exists()
    # OCR 不强制成功（可降级），但返回结构必须完整
    assert "ocr_backend" in d
    assert "advice" in d


def test_process_batch(img_server):
    r = client.post("/api/v1/images/process/batch", headers=_headers(),
                    json={"image_urls": [img_server, img_server],
                          "ratio": "1:1", "white_bg": True,
                          "bg_mode": "heuristic"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] == 2
    assert d["failed"] == 0
    assert len(d["items"]) == 2
    assert d["items"][0]["processed_path"]
    assert d["items"][0]["original_url"] == img_server


def test_process_batch_one_bad(img_server):
    r = client.post("/api/v1/images/process/batch", headers=_headers(),
                    json={"image_urls": [img_server, "http://127.0.0.1:1/x.jpg"],
                          "ratio": "1:1", "bg_mode": "heuristic"})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["ok"] == 1
    assert d["failed"] == 1
    err = [i for i in d["items"] if "error" in i]
    assert len(err) == 1
    assert "error" in err[0]


def test_missing_url():
    r = client.post("/api/v1/images/process", headers=_headers(), json={})
    assert r.status_code == 422


def test_bad_url():
    r = client.post("/api/v1/images/process", headers=_headers(),
                    json={"image_url": "not-a-url"})
    assert r.status_code == 400
