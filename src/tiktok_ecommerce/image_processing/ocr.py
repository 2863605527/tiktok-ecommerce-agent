"""图上文字识别（OCR）+ 日文翻译服务。

真实上架场景：国内货源图常带中文（品牌名/促销语/规格标注），
日本站直接上图观感差、平台可能拒审。本服务：
1. 本地 OCR（RapidOCR-ONNX 首选 / PaddleOCR 兜底，离线免费）识别图上文字；
2. DeepSeek（现有对话 LLM）逐条翻译成日文；
3. 输出「图上文字清单 + 日文翻译 + 上架建议」。

- OCR 懒加载：引擎不可用时自动降级为"仅提示"，不影响图片规格化主流程。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from langchain_core.language_models import BaseLanguageModel

from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.image_processing.ocr_backend import OcrBackend

logger = get_logger(__name__)

# 上架建议（按图上文字类型给提示）
_ADVICE_NO_TEXT = "图上未识别到文字，可直接用于上架（建议核对图片清晰度与比例）。"
_ADVICE_HAS_TEXT = (
    "图上识别到中文/水印文字：日本站直接上图可能观感差或被平台判为违规，"
    "建议使用翻译文案替换图内文字（或用无字版主图）。下方已给出逐条日文翻译，"
    "可直接作为配图文案/详情页说明。"
)


@dataclass
class ImageTextInfo:
    """一张商品图的 OCR + 翻译结果。"""

    zh_texts: list[str] = field(default_factory=list)
    translations: list[dict[str, str]] = field(default_factory=list)  # [{zh, ja}]
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
        """识别图上文字（中文）。返回去重后的文字行；OCR 不可用时返回空。"""
        return self._ocr.texts(image_path)

    # ---- 翻译（DeepSeek，批量一次调用） ----
    def translate_to_japanese(self, texts: list[str]) -> list[dict[str, str]]:
        """把中文文字逐条翻译成日文。翻译失败时回退原样并标注。"""
        if not texts:
            return []
        numbered = "\n".join(f"{i+1}. {t}" for i, t in enumerate(texts))
        prompt = (
            "你是跨境电商日语翻译。把下面商品图上的中文文字逐条翻译成地道日文"
            "（面向 TikTok 日本站买家），只输出 JSON，格式："
            '{"items":[{"zh":"原文","ja":"日文翻译"}]}\n'
            f"文字列表：\n{numbered}"
        )
        try:
            raw = self._llm.invoke(prompt)
            content = raw.content if hasattr(raw, "content") else str(raw)
            import json  # noqa: PLC0415
            # 提取 JSON（模型可能带 ```json 围栏）
            start, end = content.find("{"), content.rfind("}")
            data = json.loads(content[start:end + 1])
            items = data.get("items", [])
            return [{"zh": it.get("zh", ""), "ja": it.get("ja", "")}
                    for it in items if it.get("zh")]
        except Exception as e:  # noqa: BLE001
            logger.warning("翻译失败（%s），回退原样", e)
            return [{"zh": t, "ja": ""} for t in texts]

    # ---- 汇总 ----
    def analyze(self, image_path: Path) -> ImageTextInfo:
        """完整分析：OCR → 翻译 → 上架建议。"""
        texts = self.ocr_texts(image_path)
        if not texts:
            return ImageTextInfo(ocr_backend=self._ocr.backend_name)
        translations = self.translate_to_japanese(texts)
        return ImageTextInfo(
            zh_texts=texts,
            translations=translations,
            has_text=True,
            advice=_ADVICE_HAS_TEXT,
            ocr_backend=self._ocr.backend_name,
        )
