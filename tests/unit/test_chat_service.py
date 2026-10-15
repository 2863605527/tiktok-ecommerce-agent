"""聊天服务单元测试：意图路由 + 商品词提取（电商限定、范围外拒答）。"""
import pytest

from tiktok_ecommerce.services.chat_service import (
    ChatService,
    classify_intent,
    extract_product,
    NEED_PRODUCT_REPLY,
    OUT_OF_SCOPE_REPLY,
)


class TestClassifyIntent:
    @pytest.mark.parametrize("msg,expected", [
        # 选品意图（中文+日文）
        ("帮我分析 ボックスシーツ 能不能卖", "select_product"),
        ("分析一下法兰绒床笠适不适合卖", "select_product"),
        ("这个牛奶绒四件套能卖吗", "select_product"),
        ("ボックスシーツ 売れる？", "select_product"),
        ("选品 ボックスシーツ", "select_product"),
        # 货源意图
        ("找 牛奶绒床笠 的货源", "sourcing_only"),
        ("帮我找找法兰绒床笠的代发供应商", "sourcing_only"),
        ("仕入れ先を探して", "sourcing_only"),
        # 上架素材意图
        ("生成 法兰绒床笠 的上架素材", "listing_only"),
        ("帮我把这个标题翻译成日语", "listing_only"),
        ("商品説明を生成して", "listing_only"),
        # 带货视频脚本意图（对标 tiktok-viral-factory）
        ("生成 牛奶绒床笠 的带货脚本", "script_only"),
        ("写一个 法兰绒床笠 的台本", "script_only"),
        ("帮我写个短视频文案", "script_only"),
        ("ショート動画の台本を作って", "script_only"),
        # 电商常识 → 引导（不在工具能力内）
        ("日本站物流运费怎么算", "qa_ecommerce"),
        ("关税怎么交", "qa_ecommerce"),
        # 自我介绍/问候 → 老实介绍自己（不属于范围外）
        ("你是谁", "self_intro"),
        ("你是干啥的", "self_intro"),
        ("你是干什么的", "self_intro"),
        ("介绍一下你自己", "self_intro"),
        ("你好", "self_intro"),
        ("こんにちは", "self_intro"),
        # 货源平台切换（说1688/找家纺 → 动态切换货源源）
        ("去1688找货源", "switch_supplier"),
        ("用1688找 牛奶绒床笠 的货源", "switch_supplier"),
        ("换回找家纺网", "switch_supplier"),
        ("去其他地方找货源", "switch_supplier"),
        # 范围外
        ("今天天气怎么样", "out_of_scope"),
        ("给我写个python代码", "out_of_scope"),
        ("聊聊八卦", "out_of_scope"),
        ("", "out_of_scope"),
    ])
    def test_classify(self, msg, expected):
        assert classify_intent(msg) == expected


class TestExtractProduct:
    @pytest.mark.parametrize("msg,expected", [
        ("帮我分析 ボックスシーツ 能不能卖", "ボックスシーツ"),
        ("分析一下法兰绒床笠适不适合卖", "法兰绒床笠"),
        ("这个牛奶绒四件套能卖吗", "牛奶绒四件套"),
        ("生成 法兰绒床笠 的上架素材", "法兰绒床笠"),
        ("找 牛奶绒床笠 的货源", "牛奶绒床笠"),
        ("生成 牛奶绒床笠 的带货脚本", "牛奶绒床笠"),
        # 无商品词 → None（引导补充）
        ("帮我分析一下", None),
        ("能不能卖", None),
        ("", None),
    ])
    def test_extract(self, msg, expected):
        assert extract_product(msg) == expected


class TestChatServiceHandle:
    def make_service(self, **overrides):
        """用桩对象组装 ChatService，只测意图路由与回复组装。"""
        class _Stub:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        settings = _Stub()
        pipeline_getter = overrides.get("pipeline_getter")
        supplier_crawler = overrides.get("supplier_crawler")
        listing_agent = overrides.get("listing_agent")
        supplier_factory = overrides.get("supplier_factory")
        return ChatService(settings, pipeline_getter, supplier_crawler, listing_agent,
                           supplier_factory=supplier_factory)

    def test_self_intro_introduces(self):
        svc = self.make_service()
        r = svc.handle("你是干啥的")
        assert r["intent"] == "self_intro"
        assert "电商选品助手" in r["reply"]
        assert "帮你" in r["reply"]

    def test_out_of_scope(self):
        svc = self.make_service()
        r = svc.handle("今天天气怎么样")
        assert r["intent"] == "out_of_scope"
        assert "不在我的回答范围" in r["reply"]
        assert r["data"] is None

    def test_qa_ecommerce_guides_without_fabrication(self):
        svc = self.make_service()
        r = svc.handle("日本站物流运费怎么算")
        assert r["intent"] == "qa_ecommerce"
        assert "官方卖家中心" in r["reply"]
        # 不编造具体费率数字
        assert "%" not in r["reply"]

    def test_select_product_needs_product_name(self):
        svc = self.make_service()
        r = svc.handle("帮我分析一下")
        assert r["intent"] == "select_product"
        assert r["needs_product"] is True
        assert r["reply"] == NEED_PRODUCT_REPLY

    def test_select_product_runs_pipeline(self):
        calls = {"n": 0}

        class _FakeReport:
            summary = "低价法兰绒保暖床笠，销量为0"
            suggestion = "谨慎试卖"

            def model_dump(self):
                return {"summary": self.summary, "suggestion": self.suggestion}

        class _FakeProduct:
            title = "ふわふわミルクフランネルボックスシーツ"
            price = "1428"
            currency = "JPY"

            def model_dump(self):
                return {"title": self.title, "price": self.price}

            @property
            def price_value(self):
                return 1428.0

        class _FakePipeline:
            def __init__(self):
                self.agents = {"listing": object()}

            def run(self, **kw):
                calls["n"] += 1
                assert kw["query"] == "ボックスシーツ"
                return {"products": [_FakeProduct()], "report": _FakeReport(),
                        "offers": [], "listing_path": "out/listings/x/listing.json"}

        def getter(settings, category_name, enabled_stages):
            return _FakePipeline()

        svc = self.make_service(pipeline_getter=getter)
        r = svc.handle("帮我分析 ボックスシーツ 能不能卖")
        assert r["intent"] == "select_product"
        assert calls["n"] == 1
        assert "3" not in r["reply"]  # 数据真实来自管道返回
        assert r["data"]["listing_path"].endswith("listing.json")

    def test_sourcing_only_uses_crawler(self):
        class _FakeOffer:
            def __init__(self, title, price):
                self.title = title
                self.price = price
                self.supplier_name = "浅梦纺"
                self.delivery = "1件代发"
                self.min_order = "1件代发"
                self.url = ""
                self.match_score = 0.5
                self.score_breakdown = {}

            def model_dump(self):
                return {"title": self.title, "price": self.price,
                        "supplier_name": self.supplier_name}

        class _FakeCrawler:
            def search_offers(self, keywords, top_n=6):
                assert keywords[0] == "牛奶绒床笠"
                return [_FakeOffer("牛奶绒床笠 1.5m", "¥105.00"),
                        _FakeOffer("法兰绒床笠 1.8m", "¥98.00")]

        svc = self.make_service(supplier_crawler=_FakeCrawler())
        r = svc.handle("找 牛奶绒床笠 的货源")
        assert r["intent"] == "sourcing_only"
        assert "2 条真实货源" in r["reply"]
        assert len(r["data"]["offers"]) == 2

    def test_sourcing_empty_offers_honest(self):
        class _EmptyCrawler:
            def search_offers(self, keywords, top_n=6):
                return []

        svc = self.make_service(supplier_crawler=_EmptyCrawler())
        r = svc.handle("找 牛奶绒床笠 的货源")
        assert r["intent"] == "sourcing_only"
        assert "没搜到" in r["reply"]
        assert r["data"]["offers"] == []

    def test_listing_only_generates_package(self):
        class _FakeListing:
            title = "ふわふわミルクフランネルボックスシーツ"
            keywords = ["フランネル", "ボックスシーツ", "冬用"]

            def model_dump(self):
                return {"title": self.title, "keywords": self.keywords}

        class _FakeAgent:
            def run(self, state):
                assert state["products"][0].title == "法兰绒床笠"
                return {"listing": _FakeListing(),
                        "listing_path": "out/listings/法兰绒床笠/listing.json"}

        svc = self.make_service(listing_agent=_FakeAgent())
        r = svc.handle("生成 法兰绒床笠 的上架素材")
        assert r["intent"] == "listing_only"
        assert "已生成" in r["reply"]
        assert r["data"]["listing"]["title"].startswith("ふわふわ")


class TestSupplierSwitch:
    """货源平台切换："去1688找货源"→ 会话级切换 + 立即搜索；后续货源走新平台。"""

    def make_service(self, crawler, factory_calls=None):
        class _Stub:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        class _Offer:
            def __init__(self, title, price, supplier_name):
                self.title, self.price, self.supplier_name = title, price, supplier_name
                self.url = f"https://1688/{title[:4]}"

            def model_dump(self):
                return {"title": self.title, "price": self.price,
                        "supplier_name": self.supplier_name}

        class _FakeCrawler:
            def search_offers(self, keywords, top_n=6):
                if factory_calls is not None:
                    factory_calls.append(keywords[:1])
                return [_Offer("牛奶绒床笠 工厂 一件代发", "¥28.00", "义乌家纺厂"),
                        _Offer("加厚法兰绒毛毯 跨境专供", "¥18.50", "南通家纺厂")]

        factory = None
        if crawler == "factory":
            factory = lambda src: _FakeCrawler() if src == "1688" else _FakeCrawler()
        return ChatService(_Stub(), None, _FakeCrawler(), None, supplier_factory=factory)

    def test_switch_pure_switches_session(self):
        svc = self.make_service("factory")
        r = svc.handle("去1688找货源", conversation_id="s1")
        assert r["intent"] == "switch_supplier"
        assert "已把货源平台" in r["reply"] and "1688" in r["reply"]
        # 会话级持久：后续货源搜索自动走 1688
        assert svc._ctx("s1").supplier_source == "1688"

    def test_switch_with_product_searches_new_source(self):
        svc = self.make_service("factory")
        r = svc.handle("用1688找 牛奶绒床笠 的货源", conversation_id="s2")
        assert r["intent"] == "switch_supplier"
        assert "已切换目标为1688" in r["reply"]
        assert "牛奶绒床笠 工厂 一件代发" in r["reply"]
        assert svc._ctx("s2").supplier_source == "1688"

    def test_switch_back_to_jiafang(self):
        svc = self.make_service("factory")
        r = svc.handle("换回找家纺网", conversation_id="s3")
        assert "找家纺网" in r["reply"]
        assert svc._ctx("s3").supplier_source == "jiafang"

    def test_unspecified_other_platform_asks_choices(self):
        svc = self.make_service("factory")
        r = svc.handle("去其他地方找货源", conversation_id="s4")
        assert r["intent"] == "switch_supplier"
        assert "可选" in r["reply"]
        assert svc._ctx("s4").supplier_source == ""  # 未点名不切换

    def test_followup_sourcing_uses_switched_source(self):
        svc = self.make_service("factory")
        svc.handle("去1688找货源", conversation_id="s5")
        r2 = svc.handle("找 牛奶绒床笠 的货源", conversation_id="s5")
        assert r2["intent"] == "sourcing_only"
        assert "1688" in r2["reply"]          # 后续货源走 1688 平台文案
        assert "牛奶绒床笠 工厂 一件代发" in r2["reply"]

    def test_stream_switch_emits_delta_then_done(self):
        svc = self.make_service("factory")
        evs = list(svc.handle_stream("去1688找货源", conversation_id="s6"))
        assert all(e["type"] == "delta" for e in evs[:-1])
        assert evs[-1]["type"] == "done"
        assert "已把货源平台" in evs[-1]["reply"]
        assert "".join(e["text"] for e in evs[:-1]) == evs[-1]["reply"]

    def test_1688_unavailable_falls_back_to_jiafang(self):
        """1688 直连未启用（登录墙/风控）→ 自动回退找家纺网并如实说明。"""
        from tiktok_ecommerce.common.exceptions import CrawlerError

        class _Offer:
            title, price, supplier_name = "法兰绒床笠 工厂 一件代发", "¥22.00", "南通家纺厂"
            url = "https://jiafang/1"

            def model_dump(self):
                return {"title": self.title, "price": self.price,
                        "supplier_name": self.supplier_name}

        class _Unavailable1688:
            def search_offers(self, keywords, top_n=6):
                raise CrawlerError("1688 直连采集默认未启用：JS 渲染 + 登录墙 + 风控")

        class _Stub:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        default_crawler = type("D", (), {"search_offers": lambda self, k, top_n=6: [_Offer()]})()
        svc = ChatService(_Stub(), None, default_crawler, None,
                          supplier_factory=lambda src: _Unavailable1688())
        r = svc.handle("用1688找 法兰绒床笠 的货源", conversation_id="s7")
        assert r["intent"] == "switch_supplier"
        assert "1688 直连需要登录态或开放平台 API" in r["reply"]
        assert "找家纺网" in r["reply"] and "法兰绒床笠 工厂 一件代发" in r["reply"]
        # 会话源已重置为默认（避免后续每次都撞 1688 错误）
        assert svc._ctx("s7").supplier_source == ""


class TestChatServiceStream:
    """流式（SSE）聊天：事件序列 + 完成事件载荷。"""

    def collect(self, svc, msg, **kw):
        return list(svc.handle_stream(msg, **kw))

    def make_service(self, **overrides):
        class _Stub:
            def __init__(self, **kw):
                self.__dict__.update(kw)
        return ChatService(_Stub(), overrides.get("pipeline_getter"),
                           overrides.get("supplier_crawler"),
                           overrides.get("listing_agent"))

    def test_out_of_scope_streams_delta_then_done(self):
        svc = self.make_service()
        evs = self.collect(svc, "今天天气怎么样")
        assert evs[0]["type"] == "delta"
        assert all(e["type"] == "delta" for e in evs[:-1])
        assert evs[-1]["type"] == "done"
        assert evs[-1]["intent"] == "out_of_scope"
        assert "不在我的回答范围" in evs[-1]["reply"]
        assert evs[-1]["data"] is None
        # 文本块按顺序拼接 = 完整回复
        assert "".join(e["text"] for e in evs[:-1]) == evs[-1]["reply"]

    def test_self_intro_streams_introduction(self):
        svc = self.make_service()
        evs = self.collect(svc, "你是干啥的")
        assert evs[-1]["type"] == "done"
        assert evs[-1]["intent"] == "self_intro"
        assert "电商选品助手" in evs[-1]["reply"]
        assert evs[-1]["data"] is None

    def test_qa_ecommerce_streams_guide(self):
        svc = self.make_service()
        evs = self.collect(svc, "日本站物流运费怎么算")
        assert evs[-1]["intent"] == "qa_ecommerce"
        assert "官方卖家中心" in evs[-1]["reply"]

    def test_select_missing_product_asks(self):
        svc = self.make_service()
        evs = self.collect(svc, "帮我分析一下")
        assert evs[-1]["intent"] == "select_product"
        assert evs[-1]["needs_product"] is True

    def test_select_product_streams_progress_then_done(self):
        """重活分支：开场白流式 → status + 阶段小结 delta 边跑边出 → done。"""
        calls = {"n": 0}

        class _FakeProduct:
            title = "ふわふわミルクフランネルボックスシーツ"
            price_value = 1285.0

            def model_dump(self):
                return {"title": self.title, "price": "1285"}

        class _FakePipeline:
            def __init__(self):
                self.agents = {"listing": object()}

            def run(self, query, region="JP", category="bedding", language="ja",
                    on_progress=None, parallel=False, supplier_source=None):
                calls["n"] += 1
                if on_progress:
                    on_progress("crawler", "正在采集竞品…",
                                {"products": [_FakeProduct()]})
                    on_progress("analyzer", "正在分析评论…",
                                {"report": {"summary": "冬用厚手起毛，销量为0"}})
                return {"products": [_FakeProduct()], "report": None, "offers": [],
                        "listing_path": ""}

        def getter(settings, category_name, enabled_stages):
            return _FakePipeline()

        svc = self.make_service(pipeline_getter=getter)
        evs = self.collect(svc, "帮我分析 ボックスシーツ 能不能卖")
        types = [e["type"] for e in evs]
        assert "status" in types            # 有阶段进度（深度思考步骤）
        assert types[-1] == "done"
        statuses = [e for e in evs if e["type"] == "status"]
        assert [s["stage"] for s in statuses] == ["crawler", "analyzer"]
        # 阶段小结 delta（可选）：采集到竞品 / 分析完成（前端并入思考步骤）
        deltas = [e["text"] for e in evs if e["type"] == "delta"]
        assert any("采集到 1 个真实竞品" in d for d in deltas)
        assert any("分析完成" in d for d in deltas)
        # 第一个事件是阶段进度（不再有开场白打字机文本，最终答案随 done 一次性输出）
        assert evs[0]["type"] == "status"
        assert calls["n"] == 1
        assert evs[-1]["intent"] == "select_product"
        assert evs[-1]["data"] is not None
        # done 携带完整最终答复（前端完成后一次性展示）
        assert isinstance(evs[-1]["reply"], str) and len(evs[-1]["reply"]) > 0

    def test_sourcing_streams_offers(self):
        class _FakeOffer:
            def __init__(self, title, price):
                self.title = title
                self.price = price
                self.supplier_name = "浅梦纺"
                self.delivery = "1件代发"
                self.min_order = "1件代发"
                self.url = ""
                self.match_score = 0.5
                self.score_breakdown = {}

            def model_dump(self):
                return {"title": self.title, "price": self.price,
                        "supplier_name": self.supplier_name}

        class _FakeCrawler:
            def search_offers(self, keywords, top_n=6):
                return [_FakeOffer("牛奶绒床笠 1.5m", "¥105.00")]

        svc = self.make_service(supplier_crawler=_FakeCrawler())
        evs = self.collect(svc, "找 牛奶绒床笠 的货源")
        assert evs[-1]["type"] == "done"
        assert evs[-1]["intent"] == "sourcing_only"
        assert "1 条真实货源" in evs[-1]["reply"]
        assert len(evs[-1]["data"]["offers"]) == 1


class TestChatServiceContext:
    """会话上下文（继续聊下去，不重新搜索）："第一条货源生成素材"等。"""

    def make_service(self, **overrides):
        class _Stub:
            def __init__(self, **kw):
                self.__dict__.update(kw)

        return ChatService(
            _Stub(),
            overrides.get("pipeline_getter"),
            overrides.get("supplier_crawler"),
            overrides.get("listing_agent"),
            contexts=overrides.get("contexts") or {},
        )

    @staticmethod
    def _offer(title, price, url="", images=()):
        class _O:
            def __init__(self, t, p, u, im):
                self.title = t
                self.price = p
                self.supplier_name = "安绮家纺"
                self.min_order = "1件代发"
                self.delivery = "1件代发"
                self.url = u
                self.images = list(im)
                self.match_score = 0.9
                self.score_breakdown = {"visual_label": "疑似同款"}

            def model_dump(self):
                return {"title": self.title, "price": self.price,
                        "url": self.url, "images": self.images,
                        "supplier_name": self.supplier_name,
                        "min_order": self.min_order, "delivery": self.delivery,
                        "match_score": self.match_score,
                        "score_breakdown": self.score_breakdown}

        return _O(title, price, url, images)

    def test_listing_from_context_skips_search(self):
        """先找货源（存上下文）→ 引用第一条货源生成素材 → 不重新搜索。"""
        calls = {"search": 0, "listing": 0}

        class _FakeCrawler:
            def search_offers(self, keywords, top_n=6):
                calls["search"] += 1
                return [self.__class__._offer() for _ in range(0)] if False else [
                    TestChatServiceContext._offer(
                        "牛奶绒床笠 加厚保暖 90x200cm", "¥18.00",
                        "https://m.zhaojiafang.com/goods/123456",
                        ["https://imgniu.zhaojiafang.com/store/goods/1/1_a.jpg"])]

        class _FakeListingAgent:
            def run(self, inputs):
                calls["listing"] += 1
                # 用的是货源标题，而不是让用户重新给商品词
                assert inputs["products"][0].title.startswith("牛奶绒床笠")
                assert inputs["products"][0].images[0].startswith("https://imgniu")
                class _L:
                    title = "日本限定ふわふわミルクフランネルボックスシーツ"
                    keywords = ["ボックスシーツ", "フランネル"]
                    description = "柔らかくて暖かい"
                    translated_title = "Milk Flannel Box Sheet"
                    hashtags = []
                    specs_translated = {}
                    images = []

                    def model_dump(self):
                        return {"title": self.title, "keywords": self.keywords,
                                "description": self.description}

                return {"listing": _L(), "listing_path": "out/listings/x/listing.json"}

        svc = self.make_service(supplier_crawler=_FakeCrawler(),
                                listing_agent=_FakeListingAgent())
        r1 = svc.handle("找 牛奶绒床笠 货源", conversation_id="c1")
        assert r1["intent"] == "sourcing_only"
        assert calls["search"] == 1

        r2 = svc.handle("请帮我把找到的货源第一条链接给我生成日本站点的素材，分析卖点",
                        conversation_id="c1")
        assert r2["intent"] == "listing_context"
        assert calls["search"] == 1  # 关键：没有重新搜索！
        assert calls["listing"] == 1
        assert "日本限定" in r2["reply"]
        assert "m.zhaojiafang.com/goods/123456" in r2["reply"]
        assert r2["data"]["offers"]  # 货源卡片保留

    def test_sourcing_from_context_answers_without_search(self):
        """引用"这个货源"问价格/链接 → 基于上下文回答，不搜索。"""
        calls = {"search": 0}

        class _FakeCrawler:
            def search_offers(self, keywords, top_n=6):
                calls["search"] += 1
                return [TestChatServiceContext._offer(
                    "法兰绒床笠 加厚", "¥22.00", "https://m.zhaojiafang.com/goods/999")]

        svc = self.make_service(supplier_crawler=_FakeCrawler())
        r1 = svc.handle("找 法兰绒床笠 货源", conversation_id="c2")
        assert r1["intent"] == "sourcing_only"

        r2 = svc.handle("这个货源多少钱，链接发我", conversation_id="c2")
        assert r2["intent"] == "sourcing_context"
        assert calls["search"] == 1  # 不重新搜索
        assert "m.zhaojiafang.com/goods/999" in r2["reply"]
        assert "¥22.00" in r2["reply"]

    def test_context_isolated_by_conversation(self):
        """不同会话上下文隔离：新会话引用货源 → 引导先找货源。"""
        class _FakeCrawler:
            def search_offers(self, keywords, top_n=6):
                return [TestChatServiceContext._offer("牛奶绒床笠", "¥18.00")]

        svc = self.make_service(supplier_crawler=_FakeCrawler())
        svc.handle("找 牛奶绒床笠 货源", conversation_id="cA")
        r = svc.handle("这个货源多少钱", conversation_id="cB")  # 另一个会话
        assert r["intent"] == "sourcing_context"
        assert "还没有上次的货源结果" in r["reply"]

    def test_context_isolated_by_user(self):
        """关键安全项：不同用户同 conversation_id 不串上下文（user_id 隔离）。"""
        class _FakeCrawler:
            def search_offers(self, keywords, top_n=6):
                return [TestChatServiceContext._offer("牛奶绒床笠", "¥18.00")]

        svc = self.make_service(supplier_crawler=_FakeCrawler())
        # 用户 A 找到货源（conversation_id="shared"）
        svc.handle("找 牛奶绒床笠 货源", conversation_id="shared", user_id="userA")
        # 用户 B 用同一个 conversation_id 问"这个货源多少钱" → 不应看到 A 的货源
        r_b = svc.handle("这个货源多少钱", conversation_id="shared", user_id="userB")
        assert r_b["intent"] == "sourcing_context"
        assert "还没有上次的货源结果" in r_b["reply"]
        # 用户 A 自己再问 → 上下文仍在
        r_a = svc.handle("这个货源多少钱", conversation_id="shared", user_id="userA")
        assert "牛奶绒床笠" in r_a["reply"]

    def test_script_only_generates_script(self):
        """带货脚本意图：注入 script_generator 后生成日文脚本。"""
        class _FakeLLM:
            def invoke(self, prompt):
                assert "牛奶绒床笠" in prompt
                assert "日语" in prompt or "口播" in prompt
                class _R:
                    content = "[开场画面] ベッドルーム\n[口播] 寒い冬の夜、眠れない…"
                return _R()

        svc = self.make_service()
        svc.script_generator = _FakeLLM()
        r = svc.handle("生成 牛奶绒床笠 的带货脚本", conversation_id="s1")
        assert r["intent"] == "script_only"
        assert "口播" in r["reply"]
        assert r["data"]["script"].startswith("[开场画面]")

    def test_script_only_without_generator_degrades(self):
        """未注入生成器 → 诚实降级引导（不报错）。"""
        svc = self.make_service()
        svc.script_generator = None
        r = svc.handle("生成 牛奶绒床笠 的带货脚本", conversation_id="s2")
        assert r["intent"] == "script_only"
        assert "尚未配置" in r["reply"]

    def test_stream_listing_from_context(self):
        """流式版：引用货源生成素材 → status(素材) → done（无 crawler/analyzer 阶段）。"""
        calls = {"search": 0, "listing": 0}

        class _FakeCrawler:
            def search_offers(self, keywords, top_n=6):
                calls["search"] += 1
                return [TestChatServiceContext._offer(
                    "牛奶绒床笠 加厚", "¥18.00", "https://m.zhaojiafang.com/goods/888")]

        class _FakeListingAgent:
            def run(self, inputs):
                calls["listing"] += 1
                class _L:
                    title = "日本限定ふわふわミルクフランネルボックスシーツ"
                    keywords = ["ボックスシーツ"]
                    description = "暖かい"

                    def model_dump(self):
                        return {"title": self.title, "keywords": self.keywords,
                                "description": self.description}

                return {"listing": _L(), "listing_path": "out/listings/x/listing.json"}

        svc = self.make_service(supplier_crawler=_FakeCrawler(),
                                listing_agent=_FakeListingAgent())
        evs = []
        for ev in svc.handle_stream("找 牛奶绒床笠 货源", conversation_id="c3"):
            evs.append(ev)
        # 再发引用消息（流式）
        evs2 = list(svc.handle_stream(
            "第一条货源生成素材", conversation_id="c3"))
        stages = [e["stage"] for e in evs2 if e["type"] == "status"]
        assert stages == ["listing"]  # 只有生成素材阶段
        assert calls["search"] == 1  # 不重新搜索
        assert evs2[-1]["type"] == "done"
        assert evs2[-1]["intent"] == "listing_context"
