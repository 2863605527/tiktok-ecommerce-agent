"""OCR 适配层：RapidOCR(ONNX) 优先，PaddleOCR 兜底，都不可用则降级。

真实部署选择：
- RapidOCR(rapidocr_onnxruntime)：PaddleOCR 模型转 ONNX，CPU 兼容性最好，
  纯 pip 安装无 Paddle 运行时依赖，Windows/Python3.13 稳定 → 默认推荐
- PaddleOCR：官方套件，部分 CPU 上 PP-OCRv6 推理报 onednn 错误 → 兜底
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


class OcrBackend:
    """统一 OCR 接口（懒加载，失败自动降级）。"""

    def __init__(self) -> None:
        self._engine = None  # None=未加载 False=不可用
        self.backend_name = "none"

    def _ensure(self) -> None:
        if self._engine is not None:
            return
        # 1) RapidOCR（ONNX，首选：CPU 兼容最好）
        try:
            from rapidocr_onnxruntime import RapidOCR  # noqa: PLC0415
            self._engine = RapidOCR()
            self.backend_name = "rapidocr"
            logger.info("OCR 引擎加载：RapidOCR(ONNX)")
            return
        except Exception as e:  # noqa: BLE001
            logger.info("RapidOCR 不可用（%s），尝试 PaddleOCR", e)
        # 2) PaddleOCR（兜底）
        try:
            from paddleocr import PaddleOCR  # noqa: PLC0415
            self._engine = PaddleOCR(lang="ch")
            self.backend_name = "paddle"
            logger.info("OCR 引擎加载：PaddleOCR")
            return
        except Exception as e:  # noqa: BLE001
            logger.warning("OCR 引擎全部不可用（%s），图片文字识别关闭", e)
            self._engine = False

    def texts(self, image_path) -> list[str]:
        """识别中文文字，返回去重保序列表。"""
        return [t for t, _ in self.texts_with_boxes(image_path)]

    def texts_with_boxes(self, image_path) -> list[tuple[str, list]]:
        """识别中文文字，返回 [(text, bbox), ...]，bbox 为四点坐标 [[x1,y1],...]。"""
        self._ensure()
        if not self._engine:
            return []
        found: list[tuple[str, list]] = []
        try:
            if self.backend_name == "rapidocr":
                result, _ = self._engine(str(image_path))
                for r in (result or []):
                    if len(r) >= 2 and str(r[1]).strip():
                        found.append((str(r[1]).strip(), r[0]))
            else:
                # PaddleOCR 兜底（无 bbox 时返回空坐标）
                try:
                    res = self._engine.predict(str(image_path))
                    if res and isinstance(res, (list, tuple)):
                        for page in res:
                            if isinstance(page, dict):
                                texts = page.get("rec_texts") or page.get("rec_text") or []
                                boxes = page.get("rec_polys") or page.get("rec_boxes") or []
                                for i, t in enumerate(texts):
                                    if str(t).strip():
                                        box = boxes[i] if i < len(boxes) else []
                                        found.append((str(t).strip(), box))
                except (TypeError, ValueError):
                    result = self._engine.ocr(str(image_path), cls=True)
                    for page in result or []:
                        if not page:
                            continue
                        for item in page:
                            if item and len(item) >= 2:
                                text = (item[1][0] if isinstance(item[1], (list, tuple))
                                        else "").strip()
                                if text:
                                    found.append((text, item[0] if len(item) > 2 else []))
        except Exception as e:  # noqa: BLE001
            logger.warning("OCR 推理失败（%s），跳过文字识别", e)
            return []
        seen: set[str] = set()
        out: list[tuple[str, list]] = []
        for t, box in found:
            if t and t not in seen:
                seen.add(t)
                out.append((t, box))
        return out
