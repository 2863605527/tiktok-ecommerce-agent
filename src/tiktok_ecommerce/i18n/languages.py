"""语言注册表：上架文案主语言（日本站主推日语，其他语言可扩展）。

- DEFAULT_LANGUAGE = "ja"：TikTok 日本站为主，上架文案默认日语
- 未注册语言回退日语，避免文案语言缺失
- 新增语言 = 在 LANGUAGES 里加一行，CLI / Web 下拉自动出现
"""
from __future__ import annotations

# 支持的上架语言（key: 语言代码，value: 显示名 + 用途说明）
LANGUAGES: dict[str, str] = {
    "ja": "日语（日本站主推）",
    "en": "英语（欧美站）",
    "es": "西班牙语（拉美/西班牙）",
    "fr": "法语（欧洲/加拿大）",
    "de": "德语（德国/奥地利）",
    "ko": "韩语（韩国站）",
}

# 默认语言：日语（日本站）
DEFAULT_LANGUAGE = "ja"

# 副语言（translated_title 备选输出，可配置）
SECONDARY_LANGUAGE = "en"


def get_language(code: str | None) -> str:
    """校验语言代码，未注册回退日语。"""
    if not code:
        return DEFAULT_LANGUAGE
    code = code.lower().strip()
    return code if code in LANGUAGES else DEFAULT_LANGUAGE


def language_label(code: str) -> str:
    """语言显示名。"""
    return LANGUAGES.get(code, LANGUAGES[DEFAULT_LANGUAGE])


def list_languages() -> list[dict[str, str]]:
    """可用语言列表（CLI / Web 下拉共用）。"""
    return [
        {"code": k, "name": v.split("（")[0], "note": v}
        for k, v in LANGUAGES.items()
    ]
