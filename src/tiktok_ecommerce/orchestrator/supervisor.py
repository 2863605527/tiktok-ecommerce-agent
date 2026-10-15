"""Supervisor 并行编排器：多 Agent 并行分发 + 聚合（借鉴主流 Supervisor 模式）。

设计动机：
- 串行 LangGraph 的短板：crawler → analyzer → sourcing → listing 全串行，
  RAG 评论分析（LLM，慢）与货源搜索（真实网络请求 + 以图找货视觉，也慢）互不依赖，
  却被串行排队 → 总耗时 ≈ 四段相加。
- 本编排器把流水线改成三阶段：
    Phase 1  crawler                       —— 唯一前置依赖（产物 products）
    Phase 2  analyzer ∥ sourcing.pre_search —— 并行（互不依赖；各自都是耗时大户）
    Phase 3  sourcing.refine_merge → listing —— 报告产出后精炼补搜 → 生成素材
- 产物与串行模式完全一致（products/report/offers/listing），仅调度不同；
  短路规则一致：无商品 → 结束；无报告 → 跳过补搜/素材。

线程模型：Agent 为同步函数（内部 LLM/网络为 IO 等待），用 ThreadPoolExecutor 并行执行，
on_progress 回调保持调用方线程语义（聊天服务用 queue 转发，天然线程安全）。
"""
from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable

from tiktok_ecommerce.common.logging import get_logger

logger = get_logger(__name__)

# 阶段 → 面向用户的进度文案（与 selection.STAGE_TEXT 保持一致口径）
STAGE_TEXT: dict[str, str] = {
    "crawler": "正在采集竞品（真实搜索 TikTok 商品）…",
    "analyzer": "正在分析评论（RAG 检索 + 痛点聚类）…",
    "sourcing": "正在匹配货源（以图找货 + 官方视觉）…",
    "listing": "正在生成上架素材（日语文案 + 规格翻译）…",
}


class SupervisorOrchestrator:
    """Supervisor 编排器：并行分发 + 聚合，与串行流水线产物等价。"""

    def __init__(
        self,
        crawler_agent: Any,
        analyzer_agent: Any,
        sourcing_agent: Any,
        listing_agent: Any,
        max_workers: int = 2,
    ):
        self.crawler_agent = crawler_agent
        self.analyzer_agent = analyzer_agent
        self.sourcing_agent = sourcing_agent
        self.listing_agent = listing_agent
        self.max_workers = max_workers

    def run(
        self,
        query: str,
        region: str = "JP",
        image_dir: str | None = None,
        category: str = "bedding",
        language: str = "ja",
        on_progress: Callable[[str, str, dict | None], None] | None = None,
        supplier_source: str | None = None,
    ) -> dict[str, Any]:
        """执行一次并行选品流水线，返回与串行模式一致的最终状态。"""
        t0 = time.perf_counter()
        state: dict[str, Any] = {
            "query": query, "region": region, "image_dir": image_dir,
            "category": category, "language": language,
            "supplier_source": supplier_source or "",
        }
        logger.info("[supervisor] 启动并行编排: %s (%s) 品类=%s 语言=%s 货源=%s",
                    query, region, category, language, supplier_source)

        # ---- Phase 1：采集（唯一前置） ----
        try:
            crawler_out = self._run_agent(
                self.crawler_agent, dict(state), "crawler", on_progress)
        except Exception as e:  # 采集失败不空跑后续阶段
            logger.exception("[supervisor] 采集失败")
            state["error"] = f"采集失败：{type(e).__name__}"
            return state
        state.update(crawler_out or {})
        products = state.get("products") or []
        if not products:
            logger.warning("[supervisor] 未采集到商品，短路结束")
            return state

        # ---- Phase 2：analyzer ∥ sourcing.pre_search 并行（两个耗时大户） ----
        analyzer_state = {"products": products, "region": region, "category": category}
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            fut_analyzer = pool.submit(self._run_agent, self.analyzer_agent,
                                       analyzer_state, "analyzer", on_progress)
            fut_sourcing = pool.submit(self._run_sourcing_pre,
                                       products, region, "sourcing", on_progress,
                                       supplier_source)
            analyzer_out = fut_analyzer.result()
            pre_offers, pre_keywords = fut_sourcing.result()
        state.update(analyzer_out or {})
        report = state.get("report")

        # ---- Phase 3：精炼补搜 + 上架素材（依赖 Phase2 全部产物，串行） ----
        try:
            offers = self.sourcing_agent.refine_merge(
                report, pre_offers, pre_keywords, products, region=region,
                supplier_source=supplier_source)
        except Exception as e:
            logger.exception("[supervisor] 货源精炼失败，保留预搜索结果")
            offers = pre_offers
        state["offers"] = offers
        state["sourcing_keywords"] = pre_keywords

        if report is None:
            logger.warning("[supervisor] 分析未产出报告，跳过上架素材")
            self._notify(on_progress, "listing", STAGE_TEXT["listing"], None)
            state["sourcing_note"] = "分析无报告（资料不足），已给出预搜货源但未生成素材"
            return state

        listing_state = {
            "products": products, "report": report, "offers": offers,
            "region": region, "language": language, "image_dir": image_dir,
        }
        try:
            listing_out = self._run_agent(
                self.listing_agent, listing_state, "listing", on_progress)
            state.update(listing_out or {})
        except Exception as e:
            logger.exception("[supervisor] 素材生成失败")
            state["error"] = f"素材生成失败：{type(e).__name__}"

        cost_ms = (time.perf_counter() - t0) * 1000
        logger.info("[supervisor] 并行编排完成，耗时 %.0fms", cost_ms)
        state["orchestrator"] = "supervisor"
        state["latency_ms"] = round(cost_ms)
        return state

    # ---------------- 内部执行 ----------------

    @staticmethod
    def _run_agent(agent: Any, state: dict, stage: str,
                   on_progress: Callable | None) -> dict:
        """执行单个 Agent：进度通知 → 调用 → 返回 update。异常向上抛由编排器处理。"""
        from tiktok_ecommerce.common.logging import get_logger as _gl
        gl = _gl(__name__)
        gl.info("[supervisor] 阶段开始: %s", stage)
        SupervisorOrchestrator._notify(
            on_progress, stage, STAGE_TEXT.get(stage, f"正在执行 {stage} …"), None)
        update = agent.run(state)
        SupervisorOrchestrator._notify(on_progress, stage, None, update)
        return update or {}

    def _run_sourcing_pre(self, products: list, region: str, stage: str,
                          on_progress: Callable | None,
                          supplier_source: str | None = None) -> tuple[list, list[str]]:
        """sourcing.pre_search 包装：保持与 _run_agent 一致的进度通知。"""
        self._notify(on_progress, stage, STAGE_TEXT["sourcing"], None)
        offers, keywords = self.sourcing_agent.pre_search(
            products, region=region, supplier_source=supplier_source)
        self._notify(on_progress, stage, None, {"offers_pre": offers})
        return offers, keywords

    @staticmethod
    def _notify(on_progress: Callable | None, stage: str, text: str | None,
                update: dict | None) -> None:
        if on_progress is None:
            return
        try:
            if text is not None:
                on_progress(stage, text, None)
            elif update is not None:
                on_progress(stage, STAGE_TEXT.get(stage, stage), update)
        except Exception:  # 回调异常不影响主流程
            logger.debug("进度回调异常（忽略）: %s", stage)
