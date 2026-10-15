"""图片优化工作台 API：商品图规格化（白底/比例/压缩）+ 图上文字识别 + 日文翻译。

企业级要点：
- 全部需登录（JWT 鉴权）
- 图片下载 + 处理产物落盘 output/images/（gitignore）
- OCR 用本地 RapidOCR（免费离线），翻译用现有 DeepSeek（不新增费用）
- 白底化双通道：AI 智能抠图（rembg U2-Net，本地离线）默认 + 快速启发式兜底
- 批量处理：POST /process/batch 并发处理 1~20 张，单张失败不阻塞整体
- 失败的降级路径保持可用：OCR 不可用时返回规格化图 + 提示，不阻塞
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Literal

import requests
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from tiktok_ecommerce.api.v1.auth import get_current_user
from tiktok_ecommerce.common.exceptions import ValidationError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.common.llm import create_llm
from tiktok_ecommerce.config import get_settings
from tiktok_ecommerce.image_processing.ocr import ImageTextService
from tiktok_ecommerce.image_processing.processor import ImageProcessor, RATIO_PRESETS

logger = get_logger(__name__)

router = APIRouter(prefix="/images", tags=["images"])

BgMode = Literal["ai", "heuristic"]


class ImageProcessRequest(BaseModel):
    image_url: str = Field(..., min_length=8, description="商品图 URL（TikTok 竞品图/找家纺货源图）")
    ratio: str = Field("1:1", description="目标比例：1:1 / 3:4 / 4:3 / 9:16 / 16:9")
    white_bg: bool = Field(True, description="是否背景白底化")
    bg_mode: BgMode = Field("ai", description="白底方式：ai=AI智能抠图(rembg，对灰/渐变/阴影有效) / heuristic=快速阈值去底")
    max_side: int = Field(1000, ge=200, le=2048, description="长边上限")


class ImageProcessBatchRequest(BaseModel):
    image_urls: list[str] = Field(..., min_length=1, max_length=20,
                                  description="商品图 URL 列表（1~20 张）")
    ratio: str = Field("1:1", description="目标比例")
    white_bg: bool = Field(True, description="是否背景白底化")
    bg_mode: BgMode = Field("ai", description="白底方式")
    max_side: int = Field(1000, ge=200, le=2048, description="长边上限")


def _download_image(url: str, dst_dir: Path) -> Path:
    """下载图片到本地（带 UA，支持 imgniu/TikTok CDN）。

    SSRF 防护：先过 is_private_url（拒绝内网/回环/云元数据地址），
    防止攻击者让后端代拉 http://127.0.0.1:* 等内网资源。
    文件名用 hash+时间戳+随机串，避免同 URL 并发/重复处理互相覆盖。
    """
    from tiktok_ecommerce.common.net import is_private_url
    if is_private_url(url):
        raise ValidationError("图片地址不受支持（内网/本机地址）")
    dst_dir.mkdir(parents=True, exist_ok=True)
    import time
    import uuid
    name = f"input_{abs(hash(url)) & 0xFFFFFF}_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}.jpg"
    dst = dst_dir / name
    resp = requests.get(url, timeout=30, headers={
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    })
    resp.raise_for_status()
    if len(resp.content) < 1024:
        raise ValidationError("图片下载失败：内容为空或非图片")
    dst.write_bytes(resp.content)
    return dst


def _process_one(image_url: str, ratio: str, white_bg: bool, bg_mode: str,
                 max_side: int) -> dict:
    """处理单张商品图（供单图/批量共用）：下载 → 规格化 → OCR → 翻译 → 建议。"""
    if ratio not in RATIO_PRESETS:
        raise ValidationError(f"不支持的比例: {ratio}（可选 {list(RATIO_PRESETS)}）")

    s = get_settings()
    base = s.output_dir / "images"
    in_dir, out_dir = base / "input", base / "processed"
    in_dir.mkdir(parents=True, exist_ok=True)
    out_dir.mkdir(parents=True, exist_ok=True)

    # 1) 下载原图
    try:
        src = _download_image(image_url, in_dir)
    except requests.RequestException as e:
        raise ValidationError(f"图片下载失败: {image_url[:60]}…（{e}）") from e

    # 2) 规格化：长边缩放 → 比例白边 → 白底（ai 抠图优先，启发式兜底）
    proc = ImageProcessor(width=max_side, height=max_side, quality=88)
    final, bg_used = proc.process_image_pipeline(
        src, out_dir, ratio=ratio, white_bg=white_bg, bg_mode=bg_mode)

    # 3) OCR + 翻译（OCR 不可用时自动降级）
    llm = create_llm(s)
    svc = ImageTextService(llm)
    info = svc.analyze(src)

    return {
        "original_url": image_url,
        "processed_path": str(final),
        "processed_name": final.name,
        "ratio": ratio,
        "white_bg": white_bg,
        "bg_used": bg_used,
        "ocr_backend": info.ocr_backend,
        "has_text": info.has_text,
        "texts": info.zh_texts[:20],
        "translations": info.translations[:20],
        "advice": info.advice,
    }


@router.post("/process")
def process_image(req: ImageProcessRequest, user=Depends(get_current_user)) -> dict:
    """处理一张商品图：下载 → 规格化（白底/比例/压缩）→ OCR → 日文翻译 → 上架建议。"""
    return _process_one(req.image_url, req.ratio, req.white_bg, req.bg_mode,
                        req.max_side)


@router.post("/process/batch")
def process_image_batch(req: ImageProcessBatchRequest,
                        user=Depends(get_current_user)) -> dict:
    """批量处理商品图（1~20 张，并发 4）：单张失败不阻塞整体，逐项返回状态。

    返回 {ok, failed, items: [{image_url, ...产物字段 或 {error}}]}
    """
    if req.ratio not in RATIO_PRESETS:
        raise ValidationError(f"不支持的比例: {req.ratio}（可选 {list(RATIO_PRESETS)}）")
    items: list[dict] = []
    ok = failed = 0
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {
            pool.submit(_process_one, url, req.ratio, req.white_bg, req.bg_mode,
                        req.max_side): url
            for url in req.image_urls
        }
        for fut in as_completed(futures):
            url = futures[fut]
            try:
                r = fut.result()
                items.append(r)
                ok += 1
            except Exception as e:
                items.append({"image_url": url, "error": str(e)})
                failed += 1
                logger.warning("批量图片处理失败: %s（%s）", url[:60], e)
    # 按原顺序返回
    order = {url: i for i, url in enumerate(req.image_urls)}
    items.sort(key=lambda x: order.get(x.get("image_url"), 0))
    return {"ok": ok, "failed": failed, "items": items}
