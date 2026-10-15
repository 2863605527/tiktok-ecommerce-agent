"""第八步 流水线（LangGraph）单元测试：阶段裁剪、错误短路、非法阶段校验。"""
from __future__ import annotations

from typing import Any

import pytest

from tiktok_ecommerce.pipelines.selection import STAGE_ORDER, SelectionPipeline


class FakeStage:
    """测试用 Agent：记录调用次数，按预设结果更新 state。"""

    def __init__(self, name: str, result: dict[str, Any]):
        self.name = name
        self.result = result
        self.calls = 0

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        return {k: v for k, v in self.result.items()}


def _build(enabled: list[str] | None = None, results: dict[str, dict] | None = None):
    results = results or {
        "crawler": {"products": [{"id": "p1"}]},
        "analyzer": {"report": {"summary": "ok"}},
        "sourcing": {"offers": [{"title": "货源A"}]},
        "listing": {"listing_path": "/tmp/x.json"},
    }
    agents = {name: FakeStage(name, results[name]) for name in STAGE_ORDER}
    pipe = SelectionPipeline(
        crawler_agent=agents["crawler"],
        analyzer_agent=agents["analyzer"],
        sourcing_agent=agents["sourcing"],
        listing_agent=agents["listing"],
        enabled_stages=enabled,
    )
    return pipe, agents


class TestPipeline:
    def test_full_pipeline_runs_all_stages(self):
        pipe, agents = _build()
        result = pipe.run(query="床笠", region="JP")
        assert all(a.calls == 1 for a in agents.values())
        assert result["listing_path"] == "/tmp/x.json"

    def test_stage_pruning_skips_disabled(self):
        pipe, agents = _build(enabled=["crawler", "listing"])
        pipe.run(query="x")
        assert agents["crawler"].calls == 1
        assert agents["listing"].calls == 1
        assert agents["analyzer"].calls == 0
        assert agents["sourcing"].calls == 0

    def test_crawler_empty_short_circuits(self):
        """采集无商品 → 分析/货源/上架全部短路（不空跑 LLM）。"""
        pipe, agents = _build(results={
            "crawler": {"products": []},
            "analyzer": {"report": {"summary": "不该跑"}},
            "sourcing": {"offers": []},
            "listing": {"listing_path": "不该跑"},
        })
        result = pipe.run(query="不存在")
        assert result["products"] == []
        assert agents["analyzer"].calls == 0
        assert agents["sourcing"].calls == 0
        assert agents["listing"].calls == 0

    def test_analyzer_empty_short_circuits(self):
        """分析无报告 → 货源/上架短路。"""
        pipe, agents = _build(results={
            "crawler": {"products": [{"id": "p1"}]},
            "analyzer": {"report": None},
            "sourcing": {"offers": []},
            "listing": {"listing_path": "不该跑"},
        })
        result = pipe.run(query="x")
        assert result["report"] is None
        assert agents["sourcing"].calls == 0
        assert agents["listing"].calls == 0

    def test_unknown_stage_raises(self):
        with pytest.raises(ValueError, match="未知阶段"):
            _build(enabled=["crawler", "hacker_stage"])

    def test_on_progress_reports_each_stage(self):
        """流式进度回调：每个执行的阶段各触发一次，且结果与同步模式一致。"""
        pipe, agents = _build()
        events: list[str] = []

        def on_progress(stage: str, text: str, update: Any = None) -> None:
            events.append(stage)

        result = pipe.run(query="床笠", region="JP", on_progress=on_progress)
        assert events == ["crawler", "analyzer", "sourcing", "listing"]
        assert result["listing_path"] == "/tmp/x.json"

    def test_on_progress_respects_short_circuit(self):
        """流式进度回调在短路时只报已执行阶段（不报跳过阶段）。"""
        pipe, agents = _build(results={
            "crawler": {"products": []},
            "analyzer": {"report": {"summary": "不该跑"}},
            "sourcing": {"offers": []},
            "listing": {"listing_path": "不该跑"},
        })
        events: list[str] = []

        def on_progress(stage: str, text: str, update: Any = None) -> None:
            events.append(stage)

        pipe.run(query="不存在", on_progress=on_progress)
        assert events == ["crawler"]
        assert agents["analyzer"].calls == 0
