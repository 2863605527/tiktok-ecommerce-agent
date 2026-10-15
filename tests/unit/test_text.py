"""文本工具单元测试。"""
import pytest

from tiktok_ecommerce.common.text import (
    clean_html,
    deduplicate,
    extract_json,
    extract_keywords,
    normalize,
    parse_price,
    remove_emoji,
    truncate,
)


class TestClean:
    def test_clean_html(self):
        assert clean_html("<p>hello <b>world</b></p>") == "hello world"

    def test_clean_html_empty(self):
        assert clean_html("") == ""

    def test_remove_emoji(self):
        assert remove_emoji("很好👍 满意😄") == "很好 满意"

    def test_normalize(self):
        assert normalize("  Hello   World  ") == "Hello World"

    def test_normalize_japanese_fullwidth(self):
        # 日本站规格常见全角：NFKC 归一化为半角
        assert normalize("１．８ｍ") == "1.8m"
        assert normalize("１，２００円") == "1,200円"

    def test_truncate(self):
        assert len(truncate("x" * 100, 10)) == 10

    def test_deduplicate(self):
        assert deduplicate(["a", "A", "b"]) == ["a", "b"]

    def test_extract_keywords(self):
        kws = extract_keywords("wireless bluetooth earbuds for running", top_n=5)
        assert "earbuds" in kws


class TestExtractJson:
    def test_plain_json(self):
        assert extract_json('{"a": 1, "b": "x"}') == {"a": 1, "b": "x"}

    def test_markdown_fence(self):
        text = '```json\n{"intent": "logistics", "confidence": 0.9}\n```'
        assert extract_json(text)["intent"] == "logistics"

    def test_fence_without_lang(self):
        text = '```\n{"summary": "好产品"}\n```'
        assert extract_json(text)["summary"] == "好产品"

    def test_surrounded_by_noise(self):
        text = '好的，分析结果如下：\n{"pros": ["柔软"], "cons": []}\n以上供参考'
        data = extract_json(text)
        assert data["pros"] == ["柔软"]

    def test_invalid_raises(self):
        with pytest.raises(ValueError):
            extract_json("没有任何 JSON 内容")

    def test_empty_raises(self):
        with pytest.raises(ValueError):
            extract_json("")


class TestParsePrice:
    def test_rmb(self):
        assert parse_price("¥12.50") == 12.50

    def test_usd(self):
        assert parse_price("$19.99") == 19.99

    def test_jpy_thousands(self):
        # 日元千分位：1,200円 → 1200
        assert parse_price("1,200円") == 1200.0

    def test_japanese_fullwidth(self):
        # 全角数字 NFKC 归一化
        assert parse_price("１９８０円") == 1980.0

    def test_plain_number(self):
        assert parse_price("9.99") == 9.99

    def test_dirty_returns_zero(self):
        assert parse_price("价格面议") == 0.0
        assert parse_price("") == 0.0
        assert parse_price(None) == 0.0
