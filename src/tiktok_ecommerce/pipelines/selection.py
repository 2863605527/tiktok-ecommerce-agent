"""选品流水线：LangGraph 编排 4 个 Agent（含阶段裁剪 + 错误短路）。

LangGraph 编排要点：
- StateGraph + TypedDict State：节点间通过共享状态传数据
- add_node 注册节点，add_conditional_edges 条件路由（本实现的核心亮点）
- 错误短路：采集无商品 → 跳过分析直接结束；分析无报告 → 跳过货源/上架，
  避免对空数据空跑 LLM（省成本、结果更诚实）
- 阶段裁剪：Web/CLI 可只勾选要跑的阶段，图按启用顺序动态构建
"""
from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph

from tiktok_ecommerce.agents.analyzer_agent import AnalyzerAgent
from tiktok_ecommerce.agents.crawler_agent import CrawlerAgent
from tiktok_ecommerce.agents.listing_agent import ListingAgent
from tiktok_ecommerce.agents.sourcing_agent import SourcingAgent
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.orchestrator.supervisor import SupervisorOrchestrator

logger = get_logger(__name__)


class SelectionState(TypedDict, total=False):
    """流水线共享状态（total=False 允许字段缺失）。"""

    query: str                    # 用户输入：商品关键词/链接
    region: str                   # 目标市场
    category: str                 # 品类（bedding/electronics/apparel...）
    language: str                 # 上架文案语言（ja/en/es...，默认日语）
    supplier_source: str          # 运行时货源源（1688/jiafang/sample/api；空=默认）
    products: list                # ① 采集结果
    filtered_note: str            # 采集阶段品类过滤说明（搜到的都不是本品类时如实告知）
    report: Any                   # ② 选品报告
    offers: list                  # ③ 货源清单
    sourcing_keywords: list       # 货源搜索关键词
    sourcing_note: str            # 货源模块备注
    listing: Any                  # ④ 素材包
    listing_path: str
    image_dir: str | None         # 图片源目录（可选）
    error: str                    # 错误信息


# 流水线阶段顺序（可裁剪：只跑勾选的阶段）
STAGE_ORDER = ["crawler", "analyzer", "sourcing", "listing"]

# 阶段 → 面向用户的进度文案（流式推送 / 前端展示）
STAGE_TEXT: dict[str, str] = {
    "crawler": "正在采集竞品（真实搜索 TikTok 商品）…",
    "analyzer": "正在分析评论（RAG 检索 + 痛点聚类）…",
    "sourcing": "正在匹配货源（以图找货 + 官方视觉）…",
    "listing": "正在生成上架素材（日语文案 + 规格翻译）…",
}


class SelectionPipeline:
    """选品全链路流水线。"""

    def __init__(
        self,
        crawler_agent: CrawlerAgent,
        analyzer_agent: AnalyzerAgent,
        sourcing_agent: SourcingAgent,
        listing_agent: ListingAgent,
        enabled_stages: list[str] | None = None,
    ):
        self.agents = {
            "crawler": crawler_agent,
            "analyzer": analyzer_agent,
            "sourcing": sourcing_agent,
            "listing": listing_agent,
        }
        # 阶段裁剪：默认全流程
        self.enabled_stages = enabled_stages or STAGE_ORDER
        invalid = [s for s in self.enabled_stages if s not in self.agents]
        if invalid:
            raise ValueError(f"未知阶段: {invalid}，可选 {STAGE_ORDER}")
        self.graph = self._build_graph()
        # 并行编排器（parallel=True 时使用）：与串行图产物等价，Phase2 并行提速
        self.supervisor = SupervisorOrchestrator(
            crawler_agent=crawler_agent,
            analyzer_agent=analyzer_agent,
            sourcing_agent=sourcing_agent,
            listing_agent=listing_agent,
        )

    def _build_graph(self):
        """按启用的阶段动态构建 LangGraph，并在阶段间插入错误短路路由。"""
        g = StateGraph(SelectionState)

        for name in self.enabled_stages:
            g.add_node(name, self.agents[name].run)
        g.set_entry_point(self.enabled_stages[0])

        # 每个阶段后按"是否产生下一阶段所需数据"决定继续或提前结束
        for i, name in enumerate(self.enabled_stages):
            next_stage = self.enabled_stages[i + 1] if i + 1 < len(self.enabled_stages) else None
            g.add_conditional_edges(
                name,
                self._make_router(name, next_stage),
                {next_stage: next_stage, END: END} if next_stage else {END: END},
            )

        return g.compile()

    @staticmethod
    def _make_router(stage: str, next_stage: str | None):
        """路由函数：上游无数据则短路到 END，避免空跑后续 LLM 阶段。"""

        def router(state: dict[str, Any]) -> str:
            if next_stage is None:
                return END
            if stage == "crawler" and not state.get("products"):
                logger.warning("[pipeline] 未采集到商品，跳过分析直接结束")
                return END
            if stage == "analyzer" and not state.get("report"):
                logger.warning("[pipeline] 分析未产出报告，跳过货源/上架")
                return END
            return next_stage

        return router

    def run(
        self,
        query: str,
        region: str = "US",
        image_dir: str | None = None,
        category: str = "bedding",
        language: str = "ja",
        on_progress: Any | None = None,
        parallel: bool = False,
        supplier_source: str | None = None,
    ) -> dict:
        """执行一次流水线，返回最终状态。

        on_progress(stage, text, update)：可选流式进度回调，在每个阶段完成后触发。
        update 为该阶段产物的 state 片段（如 {"products": [...]}），供调用方生成
        "采集到 N 个竞品"这类阶段小结（真实流式体验的关键数据）。
        回调模式下用 graph.stream 逐步执行（阶段裁剪/错误短路逻辑完全一致）。

        parallel=True：改用 Supervisor 并行编排（Phase2 分析∥货源预搜并行提速），
        产物与串行模式一致。并行模式要求四阶段全启用；裁剪阶段仍走串行图。

        supplier_source：运行时货源源（1688/jiafang/sample/api），来自聊天切换
        （"去1688找货源"）；None = 用 .env 默认源。
        """
        if parallel and self.enabled_stages == STAGE_ORDER:
            return self.supervisor.run(
                query=query, region=region, image_dir=image_dir,
                category=category, language=language, on_progress=on_progress,
                supplier_source=supplier_source)

        logger.info("流水线启动: %s (%s) 品类=%s 语言=%s 阶段=%s 货源=%s",
                    query, region, category, language, self.enabled_stages, supplier_source)
        state: SelectionState = {
            "query": query, "region": region,
            "image_dir": image_dir, "category": category, "language": language,
            "supplier_source": supplier_source or "",
        }
        if on_progress is None:
            result = self.graph.invoke(state)
            logger.info("流水线完成")
            return result

        # 流式模式：graph.stream 逐步产出各节点结果，边跑边回调进度
        final_state: dict[str, Any] = dict(state)
        for event in self.graph.stream(state, stream_mode="updates"):
            for node, update in (event or {}).items():
                if isinstance(update, dict):
                    final_state.update(update)
                on_progress(node, STAGE_TEXT.get(node, f"正在执行 {node} …"),
                            update if isinstance(update, dict) else None)
        logger.info("流水线完成（流式）")
        return final_state

