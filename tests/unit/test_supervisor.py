"""Supervisor 并行编排单元测试：并行调度、短路、产物等价性。"""
from __future__ import annotations

from typing import Any

from tiktok_ecommerce.orchestrator.supervisor import SupervisorOrchestrator


class FakeCrawler:
    """采集 Agent 桩：返回预设商品。"""

    def __init__(self, products: list | None = None):
        self.products = products if products is not None else [{"id": "p1", "title": "ボックスシーツ"}]
        self.calls = 0

    def run(self, state: dict) -> dict:
        self.calls += 1
        return {"products": self.products}


class FakeAnalyzer:
    """分析 Agent 桩：sleep 模拟 LLM 耗时，返回预设报告（None=分析无产出）。"""

    def __init__(self, report: dict | None = None):
        self.report = report
        self.calls = 0

    def run(self, state: dict) -> dict:
        import time
        self.calls += 1
        time.sleep(0.05)  # 模拟 LLM 延迟
        return {"report": self.report}


class FakeSourcing:
    """货源 Agent 桩：pre_search 与 refine_merge 两阶段（与真实 Agent 同构）。"""

    def __init__(self, pre: list | None = None, extra: list | None = None):
        self.pre = pre if pre is not None else [{"title": "货源A", "url": "http://a"}]
        self.extra = extra if extra is not None else [{"title": "货源B", "url": "http://b"}]
        self.pre_calls = 0
        self.refine_calls = 0

    def pre_search(self, products: list, region: str = "JP", supplier_source: str | None = None):
        import time
        time.sleep(0.05)  # 模拟网络搜索延迟
        self.pre_calls += 1
        return self.pre, ["床笠 加厚"]

    def refine_merge(self, report, pre_offers, pre_keywords, products, region="JP",
                     supplier_source: str | None = None):
        self.refine_calls += 1
        if report is None or not (report or {}).get("keywords"):
            return pre_offers  # 报告为空：直接用预搜索（真实 Agent 行为）
        return pre_offers + [o for o in self.extra if o not in pre_offers]


class FakeListing:
    def __init__(self):
        self.calls = 0

    def run(self, state: dict) -> dict:
        self.calls += 1
        return {"listing": {"title": "素材"}, "listing_path": "/tmp/x.json"}


def _build(**kw):
    crawler = FakeCrawler(kw.get("products"))
    # 默认给一份报告；显式传 report=None 表示"分析无产出"
    report = kw["report"] if "report" in kw else {"summary": "ok", "keywords": ["床笠 加厚"]}
    analyzer = FakeAnalyzer(report)
    sourcing = FakeSourcing(kw.get("pre"), kw.get("extra"))
    listing = FakeListing()
    sup = SupervisorOrchestrator(crawler, analyzer, sourcing, listing)
    return sup, {"crawler": crawler, "analyzer": analyzer,
                 "sourcing": sourcing, "listing": listing}


class TestSupervisor:
    def test_full_parallel_runs_all_phases(self):
        sup, agents = _build()
        result = sup.run(query="ボックスシーツ", region="JP")
        assert result["products"] == agents["crawler"].products
        assert result["report"] == agents["analyzer"].report
        assert len(result["offers"]) == 2          # pre 1 + extra 1 合并
        assert result["listing"]["title"] == "素材"
        assert agents["listing"].calls == 1
        assert result.get("orchestrator") == "supervisor"
        assert result.get("latency_ms") is not None

    def test_no_products_short_circuits(self):
        """采集无商品 → 分析/货源/上架全部短路。"""
        sup, agents = _build(products=[])
        result = sup.run(query="不存在")
        assert result["products"] == []
        assert agents["analyzer"].calls == 0
        assert agents["sourcing"].pre_calls == 0
        assert agents["listing"].calls == 0

    def test_no_report_keeps_pre_offers_skips_listing(self):
        """分析无报告 → 保留预搜索货源（真实行为：不编造关键词），跳过素材。"""
        sup, agents = _build(report=None)
        result = sup.run(query="x")
        assert result["report"] is None
        assert agents["sourcing"].pre_calls == 1   # 预搜索仍执行（并行阶段）
        assert agents["sourcing"].refine_calls == 1  # refine 空报告分支
        assert result["offers"] == agents["sourcing"].pre
        assert agents["listing"].calls == 0

    def test_on_progress_reports_all_stages(self):
        """并行阶段两个事件都触发，且顺序为 crawler → analyzer → sourcing → listing。"""
        sup, agents = _build()
        events: list[str] = []

        def on_progress(stage: str, text: str, update: Any = None) -> None:
            events.append(stage)

        sup.run(query="x", on_progress=on_progress)
        # analyzer 与 sourcing 并行：两者事件都在 crawler 之后、listing 之前
        assert events[0] == "crawler"
        assert events[-1] == "listing"
        assert "analyzer" in events
        assert "sourcing" in events
        assert events.index("analyzer") < events.index("listing")
        assert events.index("sourcing") < events.index("listing")

    def test_parallel_beats_serial_ordering(self):
        """并行模式下 analyzer 与 sourcing 同时开始：两者总耗时 ≈ 单阶段耗时（非相加）。"""
        sup, agents = _build()
        import time
        t0 = time.perf_counter()
        sup.run(query="x")
        elapsed = (time.perf_counter() - t0) * 1000
        # 两阶段各 sleep 50ms，串行约 100ms；并行 < 85ms（含调度开销）
        assert elapsed < 90, f"并行未生效: {elapsed:.0f}ms"
