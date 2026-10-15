"""文本处理工具（清洗、切分、去重、JSON 提取、价格解析）。"""
import json
import re
import unicodedata

STOPWORDS = {
    "the", "a", "an", "and", "or", "for", "with", "this", "that",
    "is", "are", "was", "were", "to", "of", "in", "on", "at", "it",
    "i", "you", "he", "she", "we", "they", "my", "your",
}


def clean_html(raw: str) -> str:
    """去除 HTML 标签与多余空白。"""
    if not raw:
        return ""
    return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", raw)).strip()


def remove_emoji(text: str) -> str:
    """移除 emoji（评论数据常见噪声）。"""
    if not text:
        return ""
    return "".join(ch for ch in text if unicodedata.category(ch) != "So")


def normalize(text: str) -> str:
    """NFKC 归一化 + 压缩空白。

    日本站必备：全角英数/片假名兼容字符归一化，
    例如 "１．８ｍ" → "1.8m"、全角括号 → 半角。
    """
    if not text:
        return ""
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", text)).strip()


def truncate(text: str, max_len: int = 500) -> str:
    """按长度截断。"""
    return text[:max_len] if text and len(text) > max_len else (text or "")


def deduplicate(items: list[str]) -> list[str]:
    """有序去重。"""
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        key = normalize(item).lower()
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


def extract_keywords(text: str, top_n: int = 10) -> list[str]:
    """词频关键词粗筛（英文；日语无空格分词，日语关键词交给 LLM 精炼）。"""
    if not text:
        return []
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9'\-]{1,}", text.lower())
    freq: dict[str, int] = {}
    for w in words:
        if w not in STOPWORDS:
            freq[w] = freq.get(w, 0) + 1
    return [w for w, _ in sorted(freq.items(), key=lambda x: -x[1])[:top_n]]


def extract_json(text: str) -> dict | list:
    """从 LLM 输出中稳健提取 JSON 对象或数组。

    兼容三种真实返回：
    1. 纯 JSON：{"a": 1} 或 ["a", "b"]
    2. markdown 围栏：```json ... ```
    3. 前后带解释文字：好的，结果如下 {...} 请查收

    解析失败抛 ValueError（上层统一转 AgentError）。
    """
    if not text or not text.strip():
        raise ValueError("空内容无法提取 JSON")
    t = text.strip()

    # 去掉 markdown 代码围栏
    if t.startswith("```"):
        t = t.strip("`").strip()
        if t[:4].lower() == "json":
            t = t[4:].strip()

    # 先整体解析一次（对象或数组均可）
    try:
        data = json.loads(t)
        if isinstance(data, (dict, list)):
            return data
    except json.JSONDecodeError:
        pass

    # 兜底：截取第一个 '{' 到最后一个 '}'；数组则取第一个 '[' 到最后一个 ']'
    for start_ch, end_ch in (("{", "}"), ("[", "]")):
        start, end = t.find(start_ch), t.rfind(end_ch)
        if start != -1 and end != -1 and end > start:
            try:
                return json.loads(t[start:end + 1])
            except json.JSONDecodeError:
                continue

    raise ValueError(f"未在输出中找到 JSON: {text[:80]}")


def parse_price(text: str | None) -> float:
    """从价格字符串提取数值，支持多币种、千分位、日语全角。

    示例：
        "¥12.50" → 12.50；"$19.99" → 19.99；
        "1,200円" → 1200.0；"１．８" → 1.8（NFKC 全角转半角）
    无法解析返回 0.0（调用方据此判脏数据）。
    """
    if not text:
        return 0.0
    # NFKC：全角数字/货币符号归一化
    t = unicodedata.normalize("NFKC", str(text))
    # 去千分位逗号（中/日/美用逗号做千分位；欧洲逗号小数点场景本项目不涉及）
    t = t.replace(",", "")
    m = re.search(r"\d+(?:\.\d+)?", t)
    return float(m.group()) if m else 0.0
