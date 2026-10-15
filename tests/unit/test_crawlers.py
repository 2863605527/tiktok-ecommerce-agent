"""采集层单元测试（全部离线：本地样本 + mock HTTP，不访问外网）。"""
import pytest

from tiktok_ecommerce.common.exceptions import CrawlerError
from tiktok_ecommerce.config import ROOT_DIR, get_settings
from tiktok_ecommerce.crawlers.factory import (
    get_product_crawler,
    get_supplier_crawler,
)
from tiktok_ecommerce.crawlers.http import HttpClient
from tiktok_ecommerce.crawlers.local_sample import (
    FileProductCrawler,
    FileSupplierCrawler,
)
from tiktok_ecommerce.crawlers.supplier import ChinaSupplierCrawler
from tiktok_ecommerce.crawlers.zhaojiafang import ZhaojiafangSupplierCrawler
from tiktok_ecommerce.crawlers.third_party import (
    ThirdPartyProductCrawler,
    ThirdPartySupplierCrawler,
    _find_records,
)
from tiktok_ecommerce.crawlers.tiktok import TikTokProductCrawler
from tiktok_ecommerce.models.supplier import SupplierOffer

SAMPLE_DIR = ROOT_DIR / "data" / "samples"
PRODUCT_SAMPLE = SAMPLE_DIR / "products_jp_bedding.json"
SUPPLIER_SAMPLE = SAMPLE_DIR / "suppliers_jiafang_bedding.json"
SUPPLIER_1688_SAMPLE = SAMPLE_DIR / "suppliers_1688_bedding.json"


class _FakeClient:
    """极简 HttpClient 替身（构造 crawler 用，不真正发请求）。"""

    def __init__(self, payload: dict):
        self.payload = payload

    def get_json(self, *args, **kwargs):
        return self.payload

    def get(self, *args, **kwargs):
        return ""


# ---------- 本地样本数据源 ----------
class TestFileProductCrawler:
    def setup_method(self):
        self.crawler = FileProductCrawler(PRODUCT_SAMPLE)

    def test_load_count(self):
        products = self.crawler._load()
        assert len(products) == 3

    def test_japanese_keyword_match(self):
        # 日语关键词「ボックスシーツ」应命中床笠类商品
        results = self.crawler.search_products("ボックスシーツ", limit=5)
        assert results
        assert any("ボックスシーツ" in p.title for p in results)

    def test_fetch_by_url(self):
        p = self.crawler.fetch_product(
            "https://shop.tiktok.com/sample/product/7300000000001"
        )
        assert "綿100%" in p.title
        assert p.currency == "JPY"
        assert p.price_value == 2980.0  # 2,980円

    def test_reviews_and_specs_parsed(self):
        p = self.crawler.fetch_product(
            "https://shop.tiktok.com/sample/product/7300000000001"
        )
        assert len(p.reviews) == 7
        assert p.specs["material"].startswith("綿100%")
        # 评论评分与有用数被正确解析
        assert p.reviews[0].rating == 5
        assert p.reviews[0].helpful_count == 214

    def test_chinese_keyword_fallback_returns_all(self):
        # 样本标题为日语，中文关键词 0 命中时样本模式兜底返回全部（并可识别）
        results = self.crawler.search_products("纯棉床笠", limit=5)
        assert len(results) == 3

    def test_empty_keyword_returns_all(self):
        assert len(self.crawler.search_products("", limit=2)) == 2

    def test_fetch_missing_raises(self):
        with pytest.raises(ValueError):
            self.crawler.fetch_product("not-exist-id")


class TestFileSupplierCrawler:
    def test_load_jiafang_sample(self):
        # 默认货源：91家纺风格样本，8 条
        crawler = FileSupplierCrawler(SUPPLIER_SAMPLE)
        offers = crawler.search_offers(["纯棉", "床笠"], top_n=10)
        assert len(offers) == 8
        assert offers[0].price_value == 17.8
        assert offers[0].supplier_name
        assert "一件代发" in offers[0].min_order or "代发" in offers[0].min_order

    def test_load_1688_sample_still_works(self):
        # 1688 作为可选数据源，其样本文件仍能被同一加载器解析
        crawler = FileSupplierCrawler(SUPPLIER_1688_SAMPLE)
        offers = crawler.search_offers(["纯棉"], top_n=10)
        assert len(offers) == 6
        assert offers[0].price_value == 18.5


# ---------- 第三方 API 数据源（mock HTTP）----------
class FakeHttpClient:
    """记录调用并返回预设 JSON 的假 HTTP 客户端。"""

    def __init__(self, payload):
        self.payload = payload
        self.calls: list[tuple[str, dict | None]] = []

    def get_json(self, url, params=None, headers=None, method="GET"):
        self.calls.append((url, params))
        return self.payload


class TestThirdPartyMapping:
    def test_find_records_wrappers(self):
        assert len(_find_records({"data": {"list": [1, 2]}})) == 2
        assert len(_find_records({"data": {"records": [1]}})) == 1
        assert len(_find_records({"data": [1, 2, 3]})) == 3
        assert len(_find_records([1])) == 1
        assert _find_records({"foo": 1}) == []

    def test_product_field_mapping(self):
        # 模拟 FastMoss 风格：data.list + 非标准字段名
        payload = {"code": 0, "data": {"list": [
            {
                "product_id": "X1",
                "product_title": "接触冷感 敷きパッド",
                "sale_price": "1,980円",
                "sales": 25600,
                "attributes": {"size": "シングル"},
                "comments": [
                    {"text": "ひんやり良い", "star": 5, "likes": 30, "nickname": "a"},
                    {"content": "ベタつく", "score": 2},
                ],
            }
        ]}}
        client = FakeHttpClient(payload)
        crawler = ThirdPartyProductCrawler(client, "https://api.example.com", "secret")
        products = crawler.search_products("冷感", limit=5)

        assert len(products) == 1
        p = products[0]
        assert p.id == "X1"
        assert p.title == "接触冷感 敷きパッド"
        assert p.price_value == 1980.0
        assert p.sales == 25600
        assert p.specs == {"size": "シングル"}
        assert len(p.reviews) == 2
        assert p.reviews[0].content == "ひんやり良い"
        assert p.reviews[0].rating == 5
        assert p.reviews[0].author == "a"
        # 鉴权头与关键词参数确实发出
        url, params = client.calls[0]
        assert "/product/search" in url
        assert params["keyword"] == "冷感"

    def test_supplier_dedup(self):
        payload = {"data": {"records": [
            {"subject": "纯棉床笠", "price_info": "¥18.50", "moq": "2件",
             "ship_time": "48h", "company": "某厂", "detail_url": "u1"},
        ]}}
        # 两个关键词都返回同一条 u1，应去重为 1
        client = FakeHttpClient(payload)
        crawler = ThirdPartySupplierCrawler(client, "https://api.example.com", "secret")
        offers = crawler.search_offers(["纯棉床笠", "床笠 日式"], top_n=10)
        assert len(offers) == 1
        assert offers[0].title == "纯棉床笠"
        assert offers[0].price_value == 18.5


# ---------- 工厂：数据源切换 ----------
class TestFactory:
    def setup_method(self):
        self.settings = get_settings()

    def test_default_is_sample(self):
        crawler = get_product_crawler(self.settings, source="sample")
        assert isinstance(crawler, FileProductCrawler)
        assert len(crawler.search_products("ボックスシーツ")) >= 1

        supplier = get_supplier_crawler(self.settings, source="sample")
        assert isinstance(supplier, FileSupplierCrawler)
        # 默认货源是家纺垂直站样本（8 条），不是 1688
        assert len(supplier.search_offers(["纯棉"])) == 8

    def test_api_without_config_raises(self):
        with pytest.raises(CrawlerError):
            get_product_crawler(self.settings, source="api")
        with pytest.raises(CrawlerError):
            get_supplier_crawler(self.settings, source="api")

    def test_direct_raises_at_runtime(self):
        crawler = get_product_crawler(self.settings, source="direct")
        assert isinstance(crawler, TikTokProductCrawler)
        with pytest.raises(CrawlerError):
            crawler.search_products("任意词")

        # 家纺垂直站直连（默认货源平台）：找家纺网真实 API 实现，工厂返回可用实例
        jiafang = get_supplier_crawler(self.settings, source="jiafang")
        assert isinstance(jiafang, ZhaojiafangSupplierCrawler)

        # 1688 作为可选综合平台直连（扩展点，默认不可用）
        supplier1688 = get_supplier_crawler(self.settings, source="1688")
        assert isinstance(supplier1688, ChinaSupplierCrawler)
        with pytest.raises(CrawlerError):
            supplier1688.search_offers(["床笠"])

    def test_unknown_source_raises(self):
        with pytest.raises(CrawlerError):
            get_product_crawler(self.settings, source="weird")


# ---------- HTTP 客户端 ----------
class TestHttpClient:
    def test_ua_rotation_header(self):
        client = HttpClient(min_interval=0)
        h1 = client._build_headers(None)
        assert "User-Agent" in h1
        h2 = client._build_headers(referer="https://www.tiktok.com")
        assert h2["Referer"] == "https://www.tiktok.com"


# ---------- 直连通道解析工具（拿到渲染 HTML 后可复用）----------
class TestDirectParsers:
    def test_parse_review_block(self):
        html = (
            '<div>'
            '<div data-review="1">とても良い👍</div>'
            '<div data-review="2">普通</div>'
            '</div>'
        )
        reviews = TikTokProductCrawler._parse_review_block(html)
        assert len(reviews) == 2
        assert "とても良い" in reviews[0].content
        assert "👍" not in reviews[0].content  # emoji 被清除

    def test_parse_supplier_card(self):
        html = (
            '<div class="sm-offer-item">'
            '<a class="title" href="https://x/1">纯棉床笠 工厂直供</a>'
            '<span class="price">¥18.50</span>'
            '</div>'
        )
        offers = ChinaSupplierCrawler._parse_search_result(html, "床笠")
        assert len(offers) == 1
        assert offers[0].title == "纯棉床笠 工厂直供"
        assert offers[0].url == "https://x/1"

    def test_parse_zhaojiafang_store_payload(self):
        # 基于 2026-10 实测的找家纺搜索 API 响应结构（店铺 + 推荐商品）
        payload = {
            "ResponseStatus": 0,
            "ResponseMsg": "success",
            "datas": {"store_data": {"data": [
                {
                    "store_id": 6255,
                    "store_name": "居眠床笠",
                    "store_zy": "床笠，全棉床笠，夹棉床笠",
                    "store_address": "巨丰桥东50路南",
                    "store_daifa": 1,
                    "store_sales": "75万",
                    "recommend": [
                        {"goods_id": 117594939, "goods_price": "22.00",
                         "goods_name": "2026新款奶皮绒深睡无痕床笠 120*200cm 桃粉",
                         "goods_salenum": 0},
                        {"goods_id": 117431875, "goods_price": "13.00",
                         "goods_name": "2026新款全棉色织水洗夹棉枕套-条纹款",
                         "goods_salenum": 0},
                    ],
                }
            ]}},
        }
        offers = ZhaojiafangSupplierCrawler(
            client=_FakeClient({}))._parse_store_payload(payload)
        assert len(offers) == 2
        o = offers[0]
        assert "奶皮绒深睡无痕床笠" in o.title
        assert o.price == "¥22.00"
        assert "居眠床笠" in o.supplier_name
        assert "床笠，全棉床笠" in o.supplier_name  # 主营并入商家
        assert o.delivery == "1件代发"
        assert o.min_order == "1件代发"

    def test_parse_zhaojiafang_images_field(self):
        # 真实 API 返回 goods_image（2026-10 实测）→ 解析进 offer.images（以图找货用）
        payload = {
            "ResponseStatus": 0,
            "ResponseMsg": "success",
            "datas": {"store_data": {"data": [
                {
                    "store_id": 6255,
                    "store_name": "居眠床笠",
                    "store_zy": "床笠",
                    "store_daifa": 1,
                    "recommend": [
                        {"goods_id": 117594939, "goods_price": "22.00",
                         "goods_name": "2026新款奶皮绒深睡无痕床笠 120*200cm 桃粉",
                         "goods_image": "https://imgniu.zhaojiafang.com/store/goods/11848/11848_abc.jpg",
                         "goods_salenum": 0},
                        {"goods_id": 117431875, "goods_price": "13.00",
                         "goods_name": "2026新款全棉色织水洗夹棉枕套-条纹款",
                         "goods_image": "",  # 无图 → 不写 images
                         "goods_salenum": 0},
                    ],
                }
            ]}},
        }
        offers = ZhaojiafangSupplierCrawler(
            client=_FakeClient({}))._parse_store_payload(payload)
        assert offers[0].images == ["https://imgniu.zhaojiafang.com/store/goods/11848/11848_abc.jpg"]
        assert offers[1].images == []

    def test_parse_zhaojiafang_empty_payload(self):
        # ResponseStatus=1 或空数据 → 返回空列表，不抛错
        crawler = ZhaojiafangSupplierCrawler(client=_FakeClient({}))
        assert crawler._parse_store_payload(
            {"ResponseStatus": 1, "ResponseMsg": "", "datas": None}
        ) == []
        assert crawler._parse_store_payload({}) == []

    def test_keyword_degrade_sequence(self):
        # 长句关键词 → 逐级截断序列（原词 → 前2段 → 前1段）
        from tiktok_ecommerce.crawlers.zhaojiafang import _keyword_degrade

        seq = _keyword_degrade("牛奶绒床笠 加厚保暖 全包松紧 日本单双人")
        assert seq[0] == "牛奶绒床笠 加厚保暖 全包松紧 日本单双人"
        assert "牛奶绒床笠 加厚保暖" in seq
        assert seq[-1] == "牛奶绒床笠"
        # 顿号/逗号/中文逗号均视为分隔符
        assert _keyword_degrade("法兰绒,床笠，加厚")[-1] == "法兰绒"
        # 单段关键词只返回原词
        assert _keyword_degrade("床笠") == ["床笠"]
        # 空输入
        assert _keyword_degrade("   ") == []

    def test_parse_official_image_search_payload(self):
        """官方图搜响应（goods_list）→ 货源报价（ali_score 视觉分+代发标签）。"""
        payload = {
            "ResponseStatus": 0,
            "ResponseMsg": "获取成功！",
            "datas": {
                "goods_list": [
                    {
                        "goods_id": 96561570, "goods_name": "(长期款不断货)2026新款牛奶绒床笠加厚保暖",
                        "goods_price": "￥52.00", "ali_score": 0.9914,
                        "goods_image_url": "https://imgniu.zhaojiafang.com/store/goods/44022/44022_x.jpg",
                        "storeinfo": {"store_id": 44022, "store_name": "榆禾家纺"},
                        "tags": [{"tagname": "代发", "fontcolor": "FF2D51"}],
                        "goods_salenum": 30,
                    },
                    {
                        "goods_id": 9661447, "goods_name": "法兰绒毛毯 冬季加厚",
                        "goods_price": "￥38.00", "ali_score": 0.72,
                        "goods_image_url": "",
                        "storeinfo": {"store_id": 2, "store_name": "安绮家纺"},
                        "tags": [],
                        "goods_salenum": 0,
                    },
                ],
                "source": "aliyun",
            },
        }
        offers = ZhaojiafangSupplierCrawler(
            client=_FakeClient({}))._parse_image_search_payload(payload, top_n=5)
        assert len(offers) == 2
        top = offers[0]
        assert top.match_score == 0.991
        assert top.score_breakdown["visual_label"] == "疑似同款"
        assert top.score_breakdown["source"] == "official_image_search"
        assert "￥" not in top.price and top.price == "¥52.00"
        assert top.min_order == "1件代发"
        assert top.images == ["https://imgniu.zhaojiafang.com/store/goods/44022/44022_x.jpg"]
        assert offers[1].images == []

    def test_parse_official_image_search_error_status(self):
        # 服务端报错（ResponseStatus!=0）→ 空列表不抛错
        assert ZhaojiafangSupplierCrawler(client=_FakeClient({}))._parse_image_search_payload(
            {"ResponseStatus": 103, "datas": {"errors": "x"}}, top_n=5
        ) == []

    def test_clean_image_url(self):
        """TikTok CDN 图带 ~tplv/query 特殊后缀 → 清洗（服务端解析崩溃实测驱动）；站内 imgniu 图保留原样。"""
        from tiktok_ecommerce.crawlers.zhaojiafang import _clean_image_url

        tt = "https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/c0edcdf04eaf43dbb01d9076bfd87779~tplv-aphluv4xwc-crop-webp:400?x-signature=abc"
        cleaned = _clean_image_url(tt)
        assert "~tplv" not in cleaned and "?" not in cleaned
        assert cleaned == "https://p16-oec-sg.ibyteimg.com/tos-alisg-i-aphluv4xwc-sg/c0edcdf04eaf43dbb01d9076bfd87779"
        # 站内图（含 imageMogr2 query）原样保留
        site = "https://imgniu.zhaojiafang.com/store/goods/1/1_a.jpg?imageMogr2/thumbnail/452x452>/quality/100"
        assert _clean_image_url(site) == site

    def test_augment_with_official_image_search_merges(self):
        """本地视觉 Top1 为站内图 → 官方同款去重后排最前（最多 top_n 条）。"""
        crawler = ZhaojiafangSupplierCrawler(
            client=_FakeClient({}), image_search_token="tok123")
        local = [
            SupplierOffer(title="牛奶绒床笠 加厚", price="¥14.00", supplier_name="安绮",
                          min_order="", delivery="", url="",
                          images=["https://imgniu.zhaojiafang.com/store/goods/1/1_a.jpg"]),
            SupplierOffer(title="法兰绒床笠 保暖", price="¥18.00", supplier_name="禧缘",
                          min_order="", delivery="", url=""),
        ]
        # 官方结果：与 Top1 同款（不同店）→ 排最前；含 Top1 自身 → 去重
        official = [
            SupplierOffer(title="牛奶绒床笠 加厚", price="¥15.00", supplier_name="榆禾家纺",
                          min_order="1件代发", delivery="1件代发", url="",
                          images=["https://imgniu.zhaojiafang.com/store/goods/2/2_b.jpg"]),
            SupplierOffer(title="牛奶绒床笠 加厚", price="¥14.00", supplier_name="安绮",
                          min_order="", delivery="", url="",
                          images=["https://imgniu.zhaojiafang.com/store/goods/1/1_a.jpg"]),
        ]
        crawler.search_similar_by_image = lambda img, top_n=6, token="": official
        merged = crawler._augment_with_official_image_search(local, top_n=6)
        assert merged[0].supplier_name == "榆禾家纺"  # 官方同款排最前
        assert len(merged) == 3  # 2 官方（去重 1）+ 1 本地（Top1 被去重）
        assert [o.supplier_name for o in merged] == ["榆禾家纺", "安绮", "禧缘"]
