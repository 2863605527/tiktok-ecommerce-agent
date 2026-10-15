"""以图找货核心：图片下载 + 感知哈希 + 颜色特征 + 相似度（本地、零依赖费用）。

为什么自己实现 pHash 而不是引 imagehash 库：
- 企业级可控：算法透明、可单测、无第三方依赖风险
- pHash 对"同款/相似款"识别有效：电商商品图即使背景不同，
  主体结构（床笠铺展、四件套叠放）的频域特征依然接近
- 结合颜色直方图 + 主色，能区分"同款不同色"（直方图差异）与"同款同色"（高度相似）

相似度 = 0.5×pHash汉明距离归一化 + 0.3×颜色直方图余弦 + 0.2×主色命中
（权重可调，见 _SIM_WEIGHTS）
"""
from __future__ import annotations

import io
import time
from typing import Any

from PIL import Image

from tiktok_ecommerce.common.logging import get_logger

logger = get_logger(__name__)

# 图片下载限制（保护内存/带宽）
_MAX_BYTES = 5 * 1024 * 1024   # 5MB
_DOWNLOAD_TIMEOUT = 15         # 秒
_THUMB_SIZE = (64, 64)         # pHash 缩略图尺寸
_HIST_BUCKETS = 16             # 颜色直方图每通道桶数
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"),
    "Referer": "https://www.zhaojiafang.com/",
}

# 相似度权重
_SIM_WEIGHTS = {"phash": 0.5, "histogram": 0.3, "dominant": 0.2}

# 主色名映射（HSV 色相度 → 中文描述，供用户理解）
# 分段判断：红/粉 0-15 & 330-360，橙 15-45，黄 45-65，绿 65-170，
# 青 170-200，蓝 200-250，紫 250-290，红紫 290-330


def _hue_name(hue: float) -> str:
    """色相（0-360）→ 中文色名（分段边界用 <=，避免 hue=0 落入橙桶）。"""
    if hue <= 15 or hue > 330:
        return "红/粉"
    if hue <= 45:
        return "橙"
    if hue <= 65:
        return "黄"
    if hue <= 170:
        return "绿"
    if hue <= 200:
        return "青"
    if hue <= 250:
        return "蓝"
    if hue <= 290:
        return "紫"
    return "红紫"


def download_image(url: str) -> Image.Image | None:
    """下载图片（带超时/大小限制），失败返回 None（不抛错，容错设计）。"""
    import urllib.request

    try:
        req = urllib.request.Request(url, headers=_HEADERS)
        with urllib.request.urlopen(req, timeout=_DOWNLOAD_TIMEOUT) as r:
            data = r.read(_MAX_BYTES + 1)
        if len(data) > _MAX_BYTES:
            logger.warning("图片过大，跳过: %s", url[:120])
            return None
        img = Image.open(io.BytesIO(data))
        img.load()
        return img.convert("RGB")
    except Exception as e:
        logger.debug("下载图片失败 %s: %s", url[:120], type(e).__name__)
        return None


def _downscale(img: Image.Image) -> Image.Image:
    """统一缩放到 64×64（pHash 与直方图共用）。"""
    return img.resize(_THUMB_SIZE, Image.LANCZOS)


def phash(img: Image.Image) -> int:
    """感知哈希（RGB 三通道 8×8 均值块比较，192 bit）。

    与灰度 pHash 相比：纯红/纯蓝在灰度下哈希相同（均值比较对常量图失效），
    分通道比较后 R/G/B 通道均值差异直接编码进哈希（2026-10 实测修正）。
    汉明距离越小越相似（0=完全相同，>16 基本不相似）。
    """
    small = img.resize((8, 8), Image.LANCZOS)  # 8×8 均值块
    h = 0
    bit = 0
    for channel in range(3):  # R, G, B
        pixels = [p[channel] for p in small.get_flattened_data()]
        mean = sum(pixels) / len(pixels)
        for p in pixels:
            if p >= mean:
                h |= 1 << bit
            bit += 1
    return h


def hamming(a: int, b: int) -> int:
    """两个哈希的汉明距离（位差异计数，适用于 64/192 bit）。"""
    x = a ^ b
    n = 0
    while x:
        x &= x - 1
        n += 1
    return n


def color_histogram(img: Image.Image) -> list[float]:
    """归一化 RGB 颜色直方图（16×16×16 单一 3D 桶）。

    每个像素的 (r,g,b) 归一到唯一桶：bucket = (r//16)*256 + (g//16)*16 + (b//16)。
    （不能用三通道分开叠加——会把"纯红"和"纯蓝"混进同一桶造成假相似，2026-10 实测修正）
    """
    small = _downscale(img)
    buckets = [0.0] * (_HIST_BUCKETS ** 3)
    for r, g, b in small.get_flattened_data():
        idx = (r // 16) * 256 + (g // 16) * 16 + (b // 16)
        buckets[idx] += 1.0
    total = sum(buckets) or 1.0
    return [x / total for x in buckets]


def histogram_similarity(a: list[float], b: list[float]) -> float:
    """颜色直方图余弦相似度（0~1）。"""
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(y * y for y in b) ** 0.5
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


def dominant_color(img: Image.Image) -> str:
    """主色（HSV 色相）→ 中文色名，供视觉特征提示。

    修正（2026-10 实测）：红色在 HSV 中 H≈0，不能把 h_total==0 当"中性色"；
    按"彩色像素占比"判定中性色，否则按彩色像素平均色相分桶。
    """
    small = _downscale(img).convert("HSV")
    pixels = list(small.get_flattened_data())
    if not pixels:
        return "中性色"
    colored = [(h, s, v) for h, s, v in pixels if s > 40 and v > 40]
    if not colored:
        return "中性色"
    hue = sum(h for h, _, _ in colored) / len(colored) / 255.0 * 360.0
    return _hue_name(hue)


def _crop_center(img: Image.Image, ratio: float = 0.72) -> Image.Image:
    """裁剪中心区域（电商商品图主体居中，裁掉背景/文字/模特干扰）。

    ratio=0.72：保留中心 72% 面积。图搜实测（2026-10）：TikTok 场景图
    与货源白底图背景差异大，中心裁剪能显著提升同款命中率。
    """
    w, h = img.size
    nw, nh = int(w * ratio), int(h * ratio)
    x0, y0 = (w - nw) // 2, (h - nh) // 2
    return img.crop((x0, y0, x0 + nw, y0 + nh))


def image_signature(img: Image.Image) -> dict[str, Any]:
    """图片特征签名（pHash + 直方图 + 主色，先中心裁剪去背景干扰）。"""
    core = _crop_center(img)
    return {
        "phash": phash(core),
        "histogram": color_histogram(core),
        "dominant": dominant_color(core),
    }


def signature_similarity(a: dict[str, Any], b: dict[str, Any]) -> float:
    """两个图片特征签名的综合相似度（0~1）。"""
    ph = 1.0 - hamming(a["phash"], b["phash"]) / 64.0
    hist = histogram_similarity(a["histogram"], b["histogram"])
    dom = 1.0 if a["dominant"] == b["dominant"] else 0.0
    score = (
        _SIM_WEIGHTS["phash"] * ph
        + _SIM_WEIGHTS["histogram"] * hist
        + _SIM_WEIGHTS["dominant"] * dom
    )
    return round(max(0.0, min(1.0, score)), 3)


def similarity_from_urls(url_a: str, url_b: str) -> float | None:
    """两个图片 URL 的相似度（任一下载失败返回 None）。"""
    ia = download_image(url_a)
    ib = download_image(url_b)
    if ia is None or ib is None:
        return None
    return signature_similarity(image_signature(ia), image_signature(ib))


def rate_limit_sleep(seconds: float = 0.3) -> None:
    """图搜间限速（避免打爆货源站，企业级合规）。"""
    time.sleep(seconds)
