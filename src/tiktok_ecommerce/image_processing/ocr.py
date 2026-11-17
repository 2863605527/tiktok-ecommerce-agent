"""图上文字识别（OCR）+ 多语种翻译服务。

真实上架场景：国内货源图常带中文（品牌名/促销语/规格标注），
直接上图到海外站点观感差、平台可能拒审。本服务：
1. 本地 OCR（RapidOCR-ONNX 首选 / PaddleOCR 兜底，离线免费）识别图上文字；
2. DeepSeek（现有对话 LLM）逐条翻译，支持多方向：
   中→日 / 中→英 / 英→中 / 日→中；
3. 输出「图上文字清单 + 译文 + 上架建议」。

- OCR 懒加载：引擎不可用时自动降级为"仅提示"，不影响图片规格化主流程。
- 翻译可靠性：信号量限制 LLM 并发（批量处理时限流会导致翻译失败）+ 3 次重试退避。
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.language_models import BaseLanguageModel

from tiktok_ecommerce.common.exceptions import ValidationError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.image_processing.ocr_backend import OcrBackend

logger = get_logger(__name__)

# 上架建议（按图上文字类型给提示）
_ADVICE_NO_TEXT = "图上未识别到文字，可直接用于上架（建议核对图片清晰度与比例）。"
_ADVICE_HAS_TEXT = (
    "图上识别到文字：海外站直接上图可能观感差或被平台判为违规，"
    "建议使用译文替换图内文字（或用无字版主图）。下方已给出逐条翻译，"
    "可直接作为配图文案/详情页说明。"
)

# 支持的翻译方向：中→日 / 中→英 / 英→中 / 日→中
TRANS_PAIRS: dict[str, tuple[str, str]] = {
    "zh2ja": ("zh", "ja"),
    "zh2en": ("zh", "en"),
    "en2zh": ("en", "zh"),
    "ja2zh": ("ja", "zh"),
}

_LANG_NAMES = {"zh": "中文", "ja": "日文", "en": "英文"}

# 批量并发时限制同时调用 LLM 的数量：并发过高会触发 DeepSeek 限流，
# 表现为"批量里只有个别图翻译成功"。同时最多 2 路，其余排队。
_LLM_GATE = threading.Semaphore(2)


def lang_label(code: str) -> str:
    """语言代码 → 中文名（未知代码原样返回）。"""
    return _LANG_NAMES.get(code, code)


def parse_trans_pair(pair: str) -> tuple[str, str]:
    """解析翻译方向标识（如 zh2ja）为 (源语言, 目标语言)，非法值抛 ValidationError。"""
    if pair not in TRANS_PAIRS:
        raise ValidationError(f"不支持的翻译方向: {pair}（可选 {list(TRANS_PAIRS)}）")
    return TRANS_PAIRS[pair]


@dataclass
class TextBlock:
    """单个文字块：原文 + 译文 + 在图上的坐标。"""
    src: str
    dst: str
    bbox: list  # [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]


@dataclass
class ImageTextInfo:
    """一张商品图的 OCR + 翻译结果。"""

    src_texts: list[str] = field(default_factory=list)
    translations: list[dict[str, str]] = field(default_factory=list)  # [{src, dst}]
    blocks: list[TextBlock] = field(default_factory=list)  # 带坐标的文字块（用于原位替换）
    has_text: bool = False
    advice: str = _ADVICE_NO_TEXT
    ocr_backend: str = "none"


class ImageTextService:
    """图片文字识别 + 翻译。"""

    def __init__(self, llm: BaseLanguageModel):
        self._llm = llm
        self._ocr = OcrBackend()

    # ---- OCR（本地，懒加载） ----
    def ocr_texts(self, image_path: Path) -> list[str]:
        """识别图上文字（中文/日文/英文，取决于 OCR 引擎能力）。返回去重后的文字行；OCR 不可用时返回空。"""
        return self._ocr.texts(image_path)

    # ---- 翻译（DeepSeek，批量一次调用，带重试 + 并发闸门） ----
    def translate_texts(self, texts: list[str], source: str = "zh", target: str = "ja") -> list[dict[str, str]]:
        """把图上文字逐条翻译（source → target）。翻译失败时重试，最终回退原样并标注。"""
        if not texts:
            return []
        src_name, tgt_name = lang_label(source), lang_label(target)
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
        prompt = (
            f"你是跨境电商翻译专家。把下面商品图上的{src_name}文字逐条翻译成地道、简洁的{tgt_name}"
            "（用于跨境电商平台商品图/详情页文案，面向当地买家），保留原文的促销语气与数字，"
            "只输出 JSON，格式："
            '{"items":[{"src":"原文","dst":"译文"}]}\n'
            f"文字列表：\n{numbered}"
        )
        last_err: Exception | None = None
        for attempt in range(3):
            try:
                # 信号量：批量并发处理时限制 LLM 并发，避免限流导致翻译静默失败
                with _LLM_GATE:
                    raw = self._llm.invoke(prompt)
                content = raw.content if hasattr(raw, "content") else str(raw)
                import json  # noqa: PLC0415
                # 提取 JSON（模型可能带 ```json 围栏）
                start, end = content.find("{"), content.rfind("}")
                data = json.loads(content[start:end + 1])
                items = data.get("items", [])
                out = [{"src": it.get("src") or it.get("zh", ""),
                        "dst": it.get("dst") or it.get("ja", "")}
                       for it in items if (it.get("src") or it.get("zh"))]
                if out:
                    return out
                last_err = RuntimeError("翻译返回为空")
            except Exception as e:  # noqa: BLE001
                last_err = e
            # 指数退避后重试（1.2s / 2.4s）
            time.sleep(1.2 * (attempt + 1))
        logger.warning("翻译失败（%s），回退原样", last_err)
        return [{"src": t, "dst": ""} for t in texts]

    def translate_to_japanese(self, texts: list[str]) -> list[dict[str, str]]:
        """兼容旧接口：中→日翻译，返回 [{zh, ja}]。"""
        return [{"zh": it["src"], "ja": it["dst"]}
                for it in self.translate_texts(texts, "zh", "ja")]

    # ---- 汇总 ----
    def analyze(self, image_path: Path, source: str = "zh", target: str = "ja") -> ImageTextInfo:
        """完整分析：OCR → 翻译（source → target）→ 上架建议。"""
        blocks_raw = self._ocr.texts_with_boxes(image_path)
        if not blocks_raw:
            return ImageTextInfo(ocr_backend=self._ocr.backend_name)
        texts = [t for t, _ in blocks_raw]
        translations = self.translate_texts(texts, source, target)
        # 把翻译和坐标按顺序对齐
        trans_map = {item["src"]: item["dst"] for item in translations}
        blocks = [
            TextBlock(src=zh, dst=trans_map.get(zh, ""), bbox=box)
            for zh, box in blocks_raw
        ]
        return ImageTextInfo(
            src_texts=texts,
            translations=translations,
            blocks=blocks,
            has_text=True,
            advice=_ADVICE_HAS_TEXT,
            ocr_backend=self._ocr.backend_name,
        )
