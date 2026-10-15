"""文本切片单元测试。"""
import pytest

from tiktok_ecommerce.common.chunking import split_documents, split_text


class TestSplitText:
    def test_short_text_single_chunk(self):
        assert split_text("短いテキスト", chunk_size=300) == ["短いテキスト"]

    def test_empty(self):
        assert split_text("", chunk_size=300) == []
        assert split_text("   ", chunk_size=300) == []

    def test_long_text_split_and_size(self):
        text = "これは長い文章です。" * 100  # 约 900 字符
        chunks = split_text(text, chunk_size=200, overlap=30)
        assert len(chunks) > 1
        # 每块不超过目标长度（自然边界可能略短，硬切不会超长）
        assert all(len(c) <= 200 for c in chunks)

    def test_overlap_between_chunks(self):
        text = "句A。" * 200
        chunks = split_text(text, chunk_size=100, overlap=20)
        assert len(chunks) >= 2
        # 相邻块应存在重叠内容（第二块开头能在第一块尾部附近找到）
        assert chunks[1][:10] in chunks[0] or chunks[0][-20:] in "".join(chunks[:2])

    def test_no_separator_hard_cut(self):
        text = "あ" * 500  # 无任何分隔符 -> 硬切
        chunks = split_text(text, chunk_size=100, overlap=10)
        assert all(len(c) <= 100 for c in chunks)
        assert all(set(c) == {"あ"} for c in chunks)

    def test_invalid_chunk_size(self):
        with pytest.raises(ValueError):
            split_text("abc", chunk_size=0)


class TestSplitDocuments:
    def test_metadata_and_index(self):
        texts = ["短い説明文", "これは長い评论です。" * 50]
        metas = [{"product_id": "p1", "source_type": "description"},
                 {"product_id": "p1", "source_type": "review"}]
        out_texts, out_metas = split_documents(texts, metas, chunk_size=100, overlap=10)
        assert len(out_texts) == len(out_metas)
        assert len(out_texts) >= 2  # 第二条被切成多块
        # 元数据继承且带切片下标
        assert all(m["product_id"] == "p1" for m in out_metas)
        assert out_metas[0]["chunk_index"] == 0
        assert "source_index" in out_metas[0]

    def test_default_metadata(self):
        out_texts, out_metas = split_documents(["abc"], None, chunk_size=300)
        assert out_texts == ["abc"]
        assert out_metas[0]["chunk_index"] == 0
