"""图内文字替换：擦除中文 → 原位写日文。

用途：白底化后的商品图上还残留中文（品牌名/卖点/规格），
日本站直接上图观感差、可能被平台判违规。本模块：
1. 按 OCR 返回的 bbox 坐标，用周围底色填充擦掉中文；
2. 在原位置用匹配字号、居中对齐写上日文翻译。

依赖 Pillow（已随项目安装），字体用 Windows 自带 Yu Gothic。
"""
from __future__ import annotations

import logging
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from tiktok_ecommerce.image_processing.ocr import TextBlock

logger = logging.getLogger(__name__)

# Windows 自带日文字体（Yu Gothic Medium）
_JAPANESE_FONT = r"C:\Windows\Fonts\YuGothM.ttc"


def _bbox_to_rect(bbox: list) -> tuple[int, int, int, int] | None:
    """把四点坐标 [[x1,y1],...] 转成外接矩形 (left, top, right, bottom)。"""
    if not bbox or len(bbox) < 4:
        return None
    try:
        xs = [float(p[0]) for p in bbox]
        ys = [float(p[1]) for p in bbox]
        return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))
    except (TypeError, ValueError, IndexError):
        return None


def _sample_bg_color(img: Image.Image, rect: tuple[int, int, int, int]) -> tuple[int, int, int]:
    """采样矩形周围的平均背景色（用于擦掉中文）。

    取矩形外扩 4px 的一圈像素，避开文字本身。
    """
    left, top, right, bottom = rect
    w, h = img.size
    margin = 4
    samples: list[tuple[int, int, int]] = []
    # 上下左右各取一条边采样
    regions = [
        (max(0, left - margin), max(0, top - margin), min(w, right + margin), top),  # 上
        (max(0, left - margin), bottom, min(w, right + margin), min(h, bottom + margin)),  # 下
        (max(0, left - margin), top, left, bottom),  # 左
        (right, top, min(w, right + margin), bottom),  # 右
    ]
    px = img.convert("RGB").load()
    for x1, y1, x2, y2 in regions:
        if x2 <= x1 or y2 <= y1:
            continue
        for x in range(x1, x2, 2):
            for y in range(y1, y2, 2):
                if 0 <= x < w and 0 <= y < h:
                    samples.append(px[x, y])
    if not samples:
        return (255, 255, 255)  # 默认白色
    r = sum(s[0] for s in samples) // len(samples)
    g = sum(s[1] for s in samples) // len(samples)
    b = sum(s[2] for s in samples) // len(samples)
    return (r, g, b)


def _load_font(size: int) -> ImageFont.FreeTypeFont:
    """加载日文字体，按指定字号。字体文件缺失时回退默认。"""
    try:
        return ImageFont.truetype(_JAPANESE_FONT, size=size, index=0)
    except Exception:
        try:
            return ImageFont.truetype(r"C:\Windows\Fonts\msgothic.ttc", size=size, index=0)
        except Exception:
            return ImageFont.load_default()


def replace_text_on_image(
    image_path: Path,
    blocks: list[TextBlock],
    out_path: Path,
) -> Path | None:
    """在图片上擦除中文并原位写日文。

    Args:
        image_path: 处理后的白底图路径（OCR 在这张图上跑过，坐标对齐）。
        blocks: OCR + 翻译结果，含 bbox 和 dst 译文。
        out_path: 输出文件路径。

    Returns:
        输出路径（成功）或 None（失败/无文字块）。
    """
    if not blocks:
        return None
    try:
        img = Image.open(image_path).convert("RGB")
    except Exception as e:
        logger.warning("打开图片失败用于文字替换: %s", e)
        return None

    draw = ImageDraw.Draw(img)
    replaced = 0

    for blk in blocks:
        rect = _bbox_to_rect(blk.bbox)
        if rect is None:
            continue
        if not blk.dst or not blk.dst.strip():
            continue  # 没有译文就跳过

        left, top, right, bottom = rect
        bw, bh = right - left, bottom - top
        if bw < 8 or bh < 8:
            continue

        # 1) 用周围背景色填充，擦掉原文
        bg = _sample_bg_color(img, rect)
        draw.rectangle([left, top, right, bottom], fill=bg)

        # 2) 在原位写译文：字号按 bbox 高度估算，居中
        font_size = max(10, int(bh * 0.72))
        font = _load_font(font_size)
        dst_text = blk.dst.strip()

        # 计算文字尺寸以便居中
        bbox_text = draw.textbbox((0, 0), dst_text, font=font)
        tw = bbox_text[2] - bbox_text[0]
        th = bbox_text[3] - bbox_text[1]
        tx = left + (bw - tw) // 2 - bbox_text[0]
        ty = top + (bh - th) // 2 - bbox_text[1]

        # 文字颜色：黑色（和原图文字一致）
        draw.text((tx, ty), dst_text, fill=(30, 30, 30), font=font)
        replaced += 1

    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, quality=90)
    logger.info("图内文字替换完成: %d/%d 块 → %s", replaced, len(blocks), out_path.name)
    return out_path
