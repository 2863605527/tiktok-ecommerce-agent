"""品类配置抽象：每个品类携带自己的领域知识。

设计动机：
- 选品 Agent 的核心能力依赖"品类领域知识"（该看什么、关注什么风险）
- 把领域知识抽成 CategoryProfile，新增品类 = 新增一个配置类 + 注册
- Agent / Pipeline 只依赖接口，不知道具体品类 → 可扩展

一个品类包含：
- 选品维度：分析 Agent 重点评估的维度
- 评论分析重点：从评论里重点挖掘的信息
- 货源搜索词模板：构造 1688 搜索关键词
- 上架要点：Listing Agent 文案必须遵守的品类规则
- 目标市场注意点：不同国家市场的规格/文化差异
"""
from __future__ import annotations

from abc import ABC


class CategoryProfile(ABC):
    """品类领域知识基类。

    新增品类 = 继承本类并覆盖类属性即可（见 categories/examples.py）。
    """

    name: str = "default"
    display_name: str = "通用品类"
    description: str = "不限定品类的通用选品逻辑"

    # 选品评估维度（分析 Agent 必须覆盖）
    selection_dimensions: list[str] = []

    # 评论分析重点（从评论中重点挖掘的信息）
    review_analysis_focus: list[str] = []

    # 货源搜索词模板（{} 为占位，由 sourcing 模块填充）
    keyword_templates: list[str] = []

    # 品类判定词（中日英，标题命中任一即判定属于该品类；用于采集后过滤，
    # 实现"用户未指定品类时只保留本品类商品"。空列表 = 不过滤）
    category_markers: list[str] = []

    # 上架文案要点（Listing Agent 必须遵守）
    listing_guidelines: list[str] = []

    # 目标市场注意点（key: 市场代码，value: 说明）
    market_notes: dict[str, str] = {}

    def __init__(self) -> None:
        """拷贝可变默认值，避免所有实例共享同一 list/dict。"""
        self.selection_dimensions = list(self.selection_dimensions)
        self.review_analysis_focus = list(self.review_analysis_focus)
        self.keyword_templates = list(self.keyword_templates)
        self.category_markers = list(self.category_markers)
        self.listing_guidelines = list(self.listing_guidelines)
        self.market_notes = dict(self.market_notes)

    # ---------- 行为 ----------
    def matches_category(self, title: str) -> bool:
        """标题是否属于本品类（任一判定词命中，大小写不敏感）。

        - 无判定词（通用品类）：一律通过，不做过滤
        - 有判定词：标题命中任一即通过，保证"没特殊要求时只找本品类商品"
        """
        if not self.category_markers:
            return True
        t = title.lower()
        return any(m.lower() in t for m in self.category_markers)

    def build_search_keywords(self, report_keywords: list[str], region: str) -> list[str]:
        """由报告关键词 + 品类模板生成货源搜索词（模板优先，报告词兜底）。"""
        keywords: list[str] = []
        # 用模板生成（含品类领域词，命中率更高）
        for tpl in self.keyword_templates:
            filled = tpl.format(material="", size="", style="").strip()
            # 去掉空占位符产生的多余符号
            filled = " ".join(filled.split())
            if filled and filled not in keywords:
                keywords.append(filled)
        # 报告关键词兜底（LLM 从商品信息提炼的词）
        for kw in report_keywords[:3]:
            if kw not in keywords:
                keywords.append(kw)
        return keywords[:5]

    def selection_prompt_block(self) -> str:
        """转成给分析 Agent 的 prompt 片段。"""
        lines = [f"【品类领域知识 · {self.display_name}】", f"- 说明：{self.description}"]
        if self.selection_dimensions:
            lines.append(f"- 选品重点维度：{', '.join(self.selection_dimensions)}")
        if self.review_analysis_focus:
            lines.append(f"- 评论分析重点：{', '.join(self.review_analysis_focus)}")
        return "\n".join(lines)

    def listing_prompt_block(self, region: str) -> str:
        """转成给素材 Agent 的 prompt 片段（含目标市场注意点）。"""
        lines = [f"【品类上架要求 · {self.display_name}】"]
        if self.listing_guidelines:
            lines.append(f"- 必须包含：{'；'.join(self.listing_guidelines)}")
        note = self.market_notes.get(region.upper(), self.market_notes.get("*", ""))
        if note:
            lines.append(f"- {region.upper()} 市场注意：{note}")
        return "\n".join(lines)
