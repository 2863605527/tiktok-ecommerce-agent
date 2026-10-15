"""② 分析 Agent：RAG 多主题检索 → LLM 结构化评估 → 选品报告（含评论洞察）。

企业级要点：
- 多主题检索：按品类「评论分析重点」逐主题召回评论，比单次检索覆盖更全
- 证据约束：insights.evidence 必须引用检索资料原文，从源头防幻觉
- 空检索兜底：检索为空时明确告知 LLM 资料不足，返回空洞察而非编造
- 结构化输出：ReviewInsight 用 Pydantic 校验，字段缺失自动兜底
"""
from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models import BaseChatModel

from tiktok_ecommerce.agents.base import BaseAgent
from tiktok_ecommerce.categories.base import CategoryProfile
from tiktok_ecommerce.common.exceptions import AgentError
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.models.product import Product
from tiktok_ecommerce.models.report import ReviewInsight, SelectionReport
from tiktok_ecommerce.rag.retriever import Retriever

logger = get_logger(__name__)

ANALYSIS_PROMPT = """你是一名跨境电商选品分析师，专精日本站家纺/床上用品。请依据下面的检索资料，分析该商品是否适合在TikTok日本站销售。

【商品】{title} | 价格: {price} | 热度: {heat}

【生命周期】（规则引擎依据真实评论时间判断，引用其结论，不要自行推断）
{lifecycle}

{category_block}

【检索资料】（必须严格依据，禁止编造）
{context}

【要求】
1. 只能依据检索资料回答，资料没有的信息不要编造
2. 必须覆盖【品类领域知识】中列出的选品重点维度与评论分析重点
3. insights 为评论主题聚类：把多条评论归纳成主题（如 触感、洗后缩水、尺寸、ゴムのズレ），
   sentiment=positive 表示优点、negative 表示痛点；mentions 统计该主题被提及次数；
   severity（高/中/低）只对 negative 主题有意义；evidence 必须逐字引用资料中的评论原文（日语），至少1条、最多3条
4. 若检索资料为空或不足以判断，insights 输出空数组，并在 suggestion 中如实说明资料不足
5. 输出严格 JSON，不要多余文字：
{{
  "summary": "一句话总结核心卖点和市场表现",
  "pros": ["优点1", "优点2"],
  "cons": ["缺点1", "缺点2"],
  "market_hot": "高/中/低，理由",
  "competition": "竞争程度分析",
  "risks": ["风险1", "风险2"],
  "suggestion": "是否建议售卖及原因",
  "keywords": ["核心关键词1", "核心关键词2", "核心关键词3"],
  "insights": [
    {{"topic": "触感", "sentiment": "positive", "mentions": 3, "severity": "低", "evidence": ["评论原文1"]}},
    {{"topic": "洗后缩水", "sentiment": "negative", "mentions": 2, "severity": "高", "evidence": ["评论原文2"]}}
  ]
}}"""

# 每个主题最多召回条数（多主题检索总预算可控）
PER_TOPIC_K = 3


class AnalyzerAgent(BaseAgent):
    """分析 Agent。"""

    name = "analyzer_agent"
    description = "基于 RAG 多主题检索分析商品优缺点与市场风险，输出带证据的选品报告"

    def __init__(self, retriever: Retriever, llm: BaseChatModel, category: CategoryProfile | None = None):
        self.retriever = retriever
        self.llm = llm
        self.category = category or CategoryProfile()

    def run(self, state: dict[str, Any]) -> dict[str, Any]:
        products: list[Product] = state.get("products", [])
        if not products:
            return {"report": None, "error": "没有可分析的商品"}

        logger.info("[%s] 开始分析 %d 个商品", self.name, len(products))
        report = self._analyze(products[0])
        return {"report": report}

    # ---------- 检索 ----------
    def _build_queries(self, product: Product) -> list[str]:
        """构造多个检索主题：商品标题 + 品类评论分析重点（保证覆盖面）。"""
        queries = [product.title]
        for focus in self.category.review_analysis_focus[:5]:
            # 用简短主题词检索（如 "缩水/起球"），避免整句过长稀释语义
            queries.append(f"{product.title} {focus.split('（')[0]}")
        return queries

    def _retrieve_merged(self, product: Product) -> str:
        """多主题检索 + 去重合并，组装为给 LLM 的上下文。"""
        seen: set[str] = set()
        blocks: list[str] = []
        for q in self._build_queries(product):
            for h in self.retriever.retrieve(q, top_k=PER_TOPIC_K):
                text = h.get("text", "").strip()
                if not text or text in seen:
                    continue
                seen.add(text)
                meta = h.get("metadata") or {}
                if isinstance(meta, str):
                    try:
                        meta = json.loads(meta)
                    except ValueError:
                        meta = {}
                title = meta.get("title") or "未知来源"
                blocks.append(f"[资料{len(blocks) + 1}] 标题：{title}\n内容：{text}")
        if not blocks:
            return ""
        return "\n---\n".join(blocks)

    # ---------- 分析 ----------
    def _analyze(self, product: Product) -> SelectionReport:
        context = self._retrieve_merged(product)
        heat = _format_heat(product)
        # 生命周期（规则引擎，真实评论时间序列）拼进提示，让 LLM 引用而非编造
        from tiktok_ecommerce.services.lifecycle import analyze_lifecycle, lifecycle_block
        lifecycle_ctx = lifecycle_block(analyze_lifecycle(product))
        prompt = ANALYSIS_PROMPT.format(
            title=product.title,
            price=product.price,
            heat=heat,
            category_block=self.category.selection_prompt_block(),
            context=context or "（无检索结果：资料不足，请如实说明并输出空 insights）",
            lifecycle=lifecycle_ctx,
        )
        try:
            resp = self.llm.invoke(prompt)
            data = self._parse_json(resp.content)
        except Exception as e:
            raise AgentError("分析 Agent 执行失败", detail=str(e)) from e

        # insights 字段缺失/非法时兜底为空，不阻断报告生成
        insights = data.get("insights", [])
        if not isinstance(insights, list):
            insights = []
        data["insights"] = [ReviewInsight(**i) for i in insights if isinstance(i, dict)]
        if context:
            logger.info("[%s] 检索上下文 %d 条，解析出 %d 个评论洞察",
                        self.name, len(context.split("---")), len(data["insights"]))
        else:
            logger.warning("[%s] 检索为空，报告将如实说明资料不足", self.name)
        return SelectionReport(**data)

    @staticmethod
    def _parse_json(text: str) -> dict:
        """容错解析 LLM JSON 输出（兼容 ```json 包裹与前后解释文字）。"""
        from tiktok_ecommerce.common.text import extract_json
        return extract_json(text)


def _format_heat(product: Product) -> str:
    """把商品热度信息格式化成分析提示（销量缺失时诚实说明，不编造）。"""
    parts = []
    if product.sales > 0:
        parts.append(f"销量 {product.sales}")
    else:
        parts.append("销量未披露（本数据源 SocialCrawl JP 搜索卡不返回销量字段）")
    if product.rating is not None:
        parts.append(f"评分 {product.rating}")
    if product.reviews_count is not None:
        parts.append(f"评论数 {product.reviews_count}")
    if not parts:
        return "销量未披露、无评分/评论数（资料不足）"
    return "；".join(parts)
