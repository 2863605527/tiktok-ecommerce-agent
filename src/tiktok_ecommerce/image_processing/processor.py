"""商品图片处理器：等比缩放 + 居中裁剪 + 体积压缩 + 白底/比例适配 + AI 优化（可选）。"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from PIL import Image, UnidentifiedImageError

from tiktok_ecommerce.common.exceptions import ValidationError
from tiktok_ecommerce.common.logging import get_logger

logger = get_logger(__name__)

SUPPORTED_EXTS = {".jpg", ".jpeg", ".png", ".webp"}

# TikTok 商品图推荐比例（宽:高）
RATIO_PRESETS = {
    "1:1": 1.0,
    "3:4": 3 / 4,
    "4:3": 4 / 3,
    "9:16": 9 / 16,
    "16:9": 16 / 9,
}

# rembg 抠图模型（u2net 通用商品抠图；首次调用自动下载 ~170MB 到 ~/.u2net）
AI_BG_MODELS = ("u2net", "isnet-general-use")


class ImageProcessor:
    """图片处理工具。"""

    def __init__(self, width: int = 800, height: int = 800, quality: int = 85):
        self.width = width
        self.height = height
        self.quality = quality

    def resize_to_fit(self, src: Path, dst: Path) -> Path:
        """等比缩放 + 居中裁剪到目标尺寸。"""
        try:
            with Image.open(src) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                ratio = max(self.width / img.width, self.height / img.height)
                img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.LANCZOS)
                left = (img.width - self.width) // 2
                top = (img.height - self.height) // 2
                img = img.crop((left, top, left + self.width, top + self.height))
                img.save(dst, "JPEG", quality=self.quality)
        except UnidentifiedImageError as e:
            raise ValidationError(f"无法识别图片: {src}") from e
        except OSError as e:
            raise ValidationError(f"图片处理失败: {src}", detail=str(e)) from e
        logger.info("图片处理: %s -> %s", src, dst)
        return dst

    def compress(self, src: Path, dst: Path, max_kb: int = 500) -> Path:
        """渐进压缩直到体积达标。"""
        quality = self.quality
        while quality > 20:
            with Image.open(src) as img:
                img = img.convert("RGB")
                img.save(dst, "JPEG", quality=quality)
            if dst.stat().st_size / 1024 <= max_kb:
                break
            quality -= 10
        return dst

    def process_batch(self, src_dir: Path, dst_dir: Path) -> list[str]:
        """批量处理目录内所有支持格式图片，返回产物路径列表。"""
        dst_dir.mkdir(parents=True, exist_ok=True)
        results: list[str] = []
        for f in src_dir.iterdir():
            if f.suffix.lower() in SUPPORTED_EXTS:
                out = dst_dir / f"{f.stem}.jpg"
                self.resize_to_fit(f, out)
                results.append(str(out))
        logger.info("批量处理完成，共 %d 张", len(results))
        return results

    def to_ratio(self, src: Path, dst: Path, ratio: str = "1:1",
                 bg: tuple[int, int, int] = (255, 255, 255)) -> Path:
        """按目标宽高比白边填充居中（不改主体比例，上架图规范）。

        真实上架场景：TikTok 主图要求 1:1 / 3:4 / 9:16 等固定比例，
        直接裁剪会截掉商品主体 → 白边填充居中，主体完整保留。
        """
        target = RATIO_PRESETS.get(ratio)
        if target is None:
            raise ValidationError(f"不支持的比例: {ratio}（可选 {list(RATIO_PRESETS)}）")
        try:
            with Image.open(src) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                w, h = img.size
                cur = w / h
                if cur > target:
                    # 图偏宽 → 上下补白边
                    new_h = int(w / target)
                    canvas = Image.new("RGB", (w, new_h), bg)
                    canvas.paste(img, (0, (new_h - h) // 2))
                else:
                    # 图偏高 → 左右补白边
                    new_w = int(h * target)
                    canvas = Image.new("RGB", (new_w, h), bg)
                    canvas.paste(img, ((new_w - w) // 2, 0))
                canvas.save(dst, "JPEG", quality=self.quality)
        except UnidentifiedImageError as e:
            raise ValidationError(f"无法识别图片: {src}") from e
        except OSError as e:
            raise ValidationError(f"图片处理失败: {src}", detail=str(e)) from e
        logger.info("图片比例适配: %s -> %s (%s)", src, dst, ratio)
        return dst

    def to_white_background(self, src: Path, dst: Path,
                            threshold: int = 245) -> Path:
        """背景去底色成纯白（保留商品主体）——快速启发式（兜底方案）。

        国内货源图常见浅灰/米黄底 → 日本站上架观感差。
        本方法为像素级阈值：先按四角采样估计背景色，再统一为纯白；
        对干净白/浅灰/米色底有效，对渐变/复杂阴影效果有限。
        要"真正抠出商品主体"（阴影/渐变/复杂背景都能去），用 to_white_background_ai。
        """
        try:
            with Image.open(src) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                bg_color = _estimate_background_color(img)
                if bg_color is None:
                    # 兜底：单阈值
                    bg_color = (threshold, threshold, threshold)
                px = img.load()
                w, h = img.size
                r0, g0, b0 = bg_color
                for y in range(h):
                    for x in range(w):
                        r, g, b = px[x, y]
                        if (abs(r - r0) <= 18 and abs(g - g0) <= 18
                                and abs(b - b0) <= 18):
                            px[x, y] = (255, 255, 255)
                img.save(dst, "JPEG", quality=self.quality)
        except UnidentifiedImageError as e:
            raise ValidationError(f"无法识别图片: {src}") from e
        except OSError as e:
            raise ValidationError(f"图片处理失败: {src}", detail=str(e)) from e
        logger.info("图片白底化(启发式): %s -> %s", src, dst)
        return dst

    def to_white_background_ai(self, src: Path, dst: Path,
                               model: str = "u2net") -> Path:
        """AI 抠图去底成纯白（rembg U2-Net，本地离线免费）。

        对浅灰/米色/渐变/阴影背景都有效，是 TikTok 上架主图的正确做法。
        首次调用会下载模型（约 170MB 到 ~/.u2net），之后离线可用；
        机器不支持/模型下载失败时抛 ValidationError，调用方回退启发式。
        """
        try:
            from rembg import remove, new_session
        except ImportError as e:
            raise ValidationError(
                "AI 抠图不可用：缺少 rembg（pip install rembg onnxruntime）",
                detail=str(e),
            ) from e
        try:
            with Image.open(src) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")
                session = new_session(_pick_ai_model(model))
                cutout = remove(img, session=session, post_process_mask=True)
                canvas = Image.new("RGB", cutout.size, (255, 255, 255))
                if cutout.mode == "RGBA":
                    canvas.paste(cutout, mask=cutout.split()[-1])
                else:
                    canvas.paste(cutout)
                canvas.save(dst, "JPEG", quality=self.quality)
        except ValidationError:
            raise
        except Exception as e:
            raise ValidationError(
                f"AI 抠图失败（{model}）：{e}。首次使用需联网下载模型到 ~/.u2net，"
                f"或改用快速启发式去底。",
            ) from e
        logger.info("图片白底化(AI抠图): %s -> %s (%s)", src, dst, model)
        return dst

    def process_image_pipeline(
        self,
        src: Path,
        out_dir: Path,
        *,
        ratio: str = "1:1",
        white_bg: bool = True,
        bg_mode: str = "ai",
        ai_model: str = "u2net",
    ) -> tuple[Path, str]:
        """完整规格化管线：长边缩放 → 比例白边 → （白底，ai|heuristic）。

        Returns:
            (最终产物路径, 实际使用的 bg_mode: "ai"|"heuristic"|"none")
        """
        fitted = out_dir / f"{src.stem}_fit.jpg"
        ratioed = out_dir / f"{src.stem}_{ratio.replace(':', 'x')}.jpg"
        self.resize_to_fit(src, fitted)
        self.to_ratio(fitted, ratioed, ratio=ratio)
        if not white_bg:
            return ratioed, "none"
        if bg_mode == "ai":
            white = out_dir / f"{src.stem}_{ratio.replace(':', 'x')}_white.jpg"
            try:
                self.to_white_background_ai(ratioed, white, model=ai_model)
                return white, "ai"
            except ValidationError as e:
                logger.warning("AI 抠图失败，回退启发式去底: %s", e)
                self.to_white_background(ratioed, white)
                return white, "heuristic"
        white = out_dir / f"{src.stem}_{ratio.replace(':', 'x')}_white.jpg"
        self.to_white_background(ratioed, white)
        return white, "heuristic"


def _estimate_background_color(img: Image.Image,
                               margin: int = 8) -> Optional[tuple[int, int, int]]:
    """用四角区域众数估计背景色（商品一般居中，角上多为背景）。"""
    w, h = img.size
    corners = [
        img.crop((0, 0, margin, margin)),
        img.crop((w - margin, 0, w, margin)),
        img.crop((0, h - margin, margin, h)),
        img.crop((w - margin, h - margin, w, h)),
    ]
    from collections import Counter
    cnt: Counter[tuple[int, int, int]] = Counter()
    for c in corners:
        # Pillow 10+: getdata 弃用，用 get_flattened_data；旧版本回退兼容
        getter = getattr(c, "get_flattened_data", None) or c.getdata
        for p in getter():
            cnt[tuple(p)] += 1
    if not cnt:
        return None
    (color, _), = cnt.most_common(1)
    return color


def _pick_ai_model(preferred: str) -> str:
    """模型自适应：校验本地模型文件完整性（防残缺下载），不可用则自动降级。

    - u2net.onnx 约 176MB、u2netp.onnx 约 4.5MB；文件过小视为残缺（下载中断）
    - 首选 preferred；本地没有/损坏时依次尝试 u2netp → 原样返回
    """
    import os
    d = os.path.expanduser("~/.u2net")
    expected = {"u2net": 150 * 1024 * 1024, "u2netp": 4 * 1024 * 1024}

    def usable(name: str) -> bool:
        f = os.path.join(d, f"{name}.onnx")
        try:
            return os.path.exists(f) and os.path.getsize(f) >= expected.get(name, 0)
        except OSError:
            return False

    if preferred in ("u2net", "u2netp") and usable(preferred):
        return preferred
    if preferred == "u2net":
        if usable("u2netp"):
            logger.warning("u2net.onnx 缺失或残缺，自动降级使用 u2netp（可在 ~/.u2net 放置完整 u2net.onnx 恢复高精度）")
            return "u2netp"
        if os.path.exists(os.path.join(d, "u2net.onnx")):
            logger.warning("u2net.onnx 文件残缺（可能是下载中断），请删除后重下或改用 u2netp")
    return preferred
