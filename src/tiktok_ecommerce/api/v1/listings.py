"""上架素材包接口：POST /api/v1/listings/package → 完整 ZIP（listing.json + 商品图）。

企业级要点：
- listing.json 只允许读取 output/listings 下的文件（防路径穿越）
- 图片从原始 URL 下载进包；失败图片跳过并记录，不阻塞打包
- ZIP 以 StreamingResponse 二进制流返回，文件名带时间戳
"""
from __future__ import annotations

import io
import json
import re
import urllib.request
import zipfile
from pathlib import Path

from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from tiktok_ecommerce.api.v1.auth import get_current_user
from tiktok_ecommerce.common.exceptions import ValidationError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.config import get_settings
from pydantic import BaseModel, Field

logger = get_logger(__name__)
router = APIRouter()

_SAFE_LISTINGS_DIR = "listings"


class ListingPackageRequest(BaseModel):
    """打包请求：本地 listing.json 路径（相对 output/）+ 要打包的图片 URL。"""

    listing_path: str = Field(..., min_length=1, max_length=500, description="listing.json 相对路径，如 listings/xxx/listing.json")
    image_urls: list[str] = Field(default_factory=list, max_length=20, description="要打包的商品图 URL")


def _resolve_listing_file(rel_path: str) -> Path:
    """校验并解析 listing.json 路径（仅允许 output/listings 下，防穿越）。"""
    p = Path(rel_path)
    parts = p.parts
    if not parts or parts[0] != _SAFE_LISTINGS_DIR:
        raise ValidationError("listing 路径必须在 output/listings 下")
    settings = get_settings()
    resolved = (settings.output_dir / p).resolve()
    if not str(resolved).startswith(str((settings.output_dir / _SAFE_LISTINGS_DIR).resolve())):
        raise ValidationError("listing 路径越界，已拒绝")
    if not resolved.exists() or not resolved.is_file():
        raise ValidationError(f"listing 文件不存在: {rel_path}")
    return resolved


def _safe_zip_name(url: str) -> str:
    """从 URL 提取安全的文件名（保留扩展名，去非法字符）。"""
    name = url.split("/")[-1].split("?")[0] or "img.jpg"
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name)
    if len(name) > 80:
        name = name[-80:]
    return name or "img.jpg"


def _is_private_url(url: str) -> bool:
    """SSRF 防护：拒绝指向内网/回环/链路本地/云元数据地址的图片 URL。"""
    from tiktok_ecommerce.common.net import is_private_url
    return is_private_url(url)


def _csv_safe(value: str) -> str:
    """CSV 公式注入防护：Excel 打开时 =/+/-/@ 前缀会被当公式执行。"""
    v = (value or "").strip()
    if v[:1] in {"=", "+", "-", "@"}:
        return "'" + v
    return v


# ---- 导出前预览（对标 Anthropic commerce-agents merchant 人工批准门控）----


@router.get("/listings/preview")
def preview_listing(
    listing_path: str,
    user=Depends(get_current_user),
) -> dict:
    """导出前预览：返回素材内容摘要，前端展示确认后再触发打包/导出。

    人工批准门控：写操作（打包/导出）前先让卖家看到要下载的内容，
    避免"导出错了才发现"。预览本身只读，不产生下载。
    """
    listing_file = _resolve_listing_file(listing_path)
    listing_json = json.loads(listing_file.read_text(encoding="utf-8"))
    logger.info("素材预览: %s user=%s", listing_path, user.id)
    return {
        "listing_path": listing_path,
        "title": listing_json.get("title", ""),
        "translated_title": listing_json.get("translated_title", ""),
        "keywords": (listing_json.get("keywords") or [])[:10],
        "hashtags": (listing_json.get("hashtags") or [])[:10],
        "description": (listing_json.get("description") or "")[:500],
        "specs_translated": listing_json.get("specs_translated") or {},
        "has_images": bool(listing_json.get("images")),
    }


@router.post("/listings/package")
def package_listing(
    req: ListingPackageRequest,
    user=Depends(get_current_user),
) -> StreamingResponse:
    """打包上架素材：listing.json + 商品图 → ZIP 流。"""
    listing_file = _resolve_listing_file(req.listing_path)
    listing_json = json.loads(listing_file.read_text(encoding="utf-8"))

    buf = io.BytesIO()
    skipped: list[str] = []
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("listing.json", json.dumps(listing_json, ensure_ascii=False, indent=2))
        for url in req.image_urls[:20]:
            if not url.startswith(("http://", "https://")):
                skipped.append(url)
                continue
            if _is_private_url(url):  # SSRF：拒绝内网/回环/云元数据地址
                skipped.append(url)
                continue
            try:
                with urllib.request.urlopen(url, timeout=15) as resp:
                    data = resp.read()
                zf.writestr(f"images/{_safe_zip_name(url)}", data)
            except Exception:
                skipped.append(url)

    buf.seek(0)
    stem = listing_file.stem  # listing.json → 目录名后缀无意义，用父目录名
    folder = listing_file.parent.name[:40] or "listing"
    from urllib.parse import quote
    # RFC 5987：中文/日文文件名 → filename* 编码，兼容下载
    filename = f"{folder}_素材包_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.zip"
    ascii_name = re.sub(r"[^\x20-\x7e]", "_", filename)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
    }
    logger.info("素材包打包: %s 图片=%d 跳过=%d user=%s",
                req.listing_path, len(req.image_urls), len(skipped), user.id)
    return StreamingResponse(
        iter([buf.getvalue()]),  # 必须是可迭代对象；直接传 bytes 会被逐字节迭代
        media_type="application/zip",
        headers=headers,
    )


# ---- TikTok Shop 批量上架 CSV（真实卖家中心可导入的模板） ----

_TIKTOK_CSV_HEADERS = [
    "商品名称", "商品描述", "商品类目", "关键词", "标签",
    "规格(名称=值；分号分隔)", "图片URL(逗号分隔)", "价格(JPY)", "库存",
    "备注",
]


@router.post("/listings/csv")
def export_listing_csv(
    req: ListingPackageRequest,
    user=Depends(get_current_user),
) -> StreamingResponse:
    """导出 TikTok Shop 批量上架 CSV（UTF-8 BOM，Excel 直接打开）。

    素材包字段 → TikTok 卖家中心批量上传模板列；价格/库存留空
    （定价建议见选品评估，库存由卖家自己定），避免编造数字。
    """
    import csv

    listing_file = _resolve_listing_file(req.listing_path)
    listing_json = json.loads(listing_file.read_text(encoding="utf-8"))

    title = listing_json.get("title", "") or listing_json.get("translated_title", "")
    description = listing_json.get("description", "")
    keywords = " ".join(listing_json.get("keywords") or [])
    hashtags = " ".join(listing_json.get("hashtags") or [])
    specs = "；".join(f"{k}={v}" for k, v in (listing_json.get("specs_translated") or {}).items())
    images = ",".join(req.image_urls[:20])
    remark = ("上架前请按 TikTok Shop 日本站类目/属性规范核对；"
              "定价参考选品评估中的市场价带（建议对标中位价）；"
              "库存按实际备货填写。")

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(_TIKTOK_CSV_HEADERS)
    writer.writerow([_csv_safe(title), _csv_safe(description), "", _csv_safe(keywords),
                     _csv_safe(hashtags), _csv_safe(specs), images, "", "", remark])

    data = buf.getvalue().encode("utf-8-sig")  # BOM：Excel 打开不乱码
    folder = listing_file.parent.name[:40] or "listing"
    from urllib.parse import quote
    filename = f"{folder}_tiktok上架_{__import__('datetime').datetime.now().strftime('%Y%m%d')}.csv"
    ascii_name = re.sub(r"[^\x20-\x7e]", "_", filename)
    headers = {
        "Content-Disposition": f"attachment; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(filename)}",
    }
    logger.info("上架 CSV 导出: %s user=%s", req.listing_path, user.id)
    return StreamingResponse(
        iter([data]),
        media_type="text/csv; charset=utf-8",
        headers=headers,
    )
