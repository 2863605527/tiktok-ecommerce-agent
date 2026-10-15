"""领域模型单元测试。"""
from tiktok_ecommerce.models.product import Product, Review
from tiktok_ecommerce.models.report import SelectionReport
from tiktok_ecommerce.models.supplier import ListingPackage, SupplierOffer


class TestProduct:
    def test_to_embedding_texts(self):
        p = Product(
            title="earbuds",
            price="9.99",
            description="good sound",
            reviews=[Review(content="very good", rating=4.5)],
        )
        pairs = p.to_embedding_texts()
        assert len(pairs) == 2  # 描述 + 评论
        assert pairs[0][1]["source"] == "tiktok"

    def test_review_texts_filters_empty(self):
        p = Product(title="x", reviews=[Review(content="  "), Review(content="ok")])
        assert p.review_texts() == ["ok"]

    def test_price_value_multi_currency(self):
        assert Product(title="x", price="$19.99").price_value == 19.99
        assert Product(title="x", price="¥12.50").price_value == 12.5
        # 日语全角 + 千分位
        assert Product(title="x", price="１，２００円").price_value == 1200.0

    def test_price_value_dirty_is_zero(self):
        assert Product(title="x", price="").price_value == 0.0

    def test_specs_default_empty(self):
        p = Product(title="纯棉床笠", specs={"size": "1.8m", "material": "纯棉"})
        assert p.specs["size"] == "1.8m"
        assert Product(title="x").specs == {}


class TestReport:
    def test_to_markdown(self):
        r = SelectionReport(summary="测试", suggestion="可试销")
        md = r.to_markdown()
        assert "选品评估报告" in md
        assert "可试销" in md


class TestSupplierOffer:
    def test_price_value(self):
        offer = SupplierOffer(title="纯棉四件套工厂直供", price="¥38.80")
        assert offer.price_value == 38.8

    def test_match_score_bounds(self):
        import pytest
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            SupplierOffer(title="x", match_score=1.5)  # 超过上限 1


class TestListingPackage:
    def test_defaults(self):
        pkg = ListingPackage(title="綿100%ボックスシーツ")
        assert pkg.keywords == []
        assert pkg.images == []
        assert pkg.title == "綿100%ボックスシーツ"
