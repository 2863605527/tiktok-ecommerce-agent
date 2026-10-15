"""选品评估报告模型。"""
from pydantic import BaseModel, Field


class ReviewInsight(BaseModel):
    """评论主题洞察：一个聚类主题（优点/痛点）及其证据。

    防幻觉设计：
    - evidence 必须引用检索资料中的评论原文（日语），禁止 LLM 编造
    - mentions 为提及次数（由 LLM 依据上下文统计，用于判断是否共性问题）
    """

    topic: str = Field(..., min_length=1, description="主题名，如 触感 / 洗后缩水 / 尺寸不符")
    sentiment: str = Field("negative", pattern="^(positive|negative)$",
                           description="positive=优点 / negative=痛点")
    mentions: int = Field(1, ge=1, description="该主题被提及/出现次数（>=1）")
    severity: str = Field("中", description="严重度：高/中/低（仅 negative 主题有意义）")
    evidence: list[str] = Field(default_factory=list, description="代表评论原文（必须来自检索资料）")


class SelectionReport(BaseModel):
    """② 分析 Agent 输出的结构化选品评估报告。"""

    summary: str = Field("", description="一句话总结核心卖点和市场表现")
    pros: list[str] = Field(default_factory=list, description="商品优点")
    cons: list[str] = Field(default_factory=list, description="商品缺点")
    market_hot: str = Field("", description="市场热度：高/中/低 + 理由")
    competition: str = Field("", description="竞争程度分析")
    risks: list[str] = Field(default_factory=list, description="风险列表")
    suggestion: str = Field("", description="是否建议售卖及原因")
    keywords: list[str] = Field(default_factory=list, description="核心关键词（供货源匹配用）")
    insights: list[ReviewInsight] = Field(
        default_factory=list,
        description="评论主题洞察（优点/痛点聚类，含证据），供报告展示与货源反推",
    )

    def to_markdown(self) -> str:
        """转成可读的 Markdown 报告。"""
        lines = [
            "## 选品评估报告",
            f"- **总结**: {self.summary}",
            f"- **市场热度**: {self.market_hot}",
            f"- **建议**: {self.suggestion}",
            f"- **优点**: {', '.join(self.pros) or '无'}",
            f"- **缺点**: {', '.join(self.cons) or '无'}",
            f"- **风险**: {', '.join(self.risks) or '无'}",
            f"- **竞争**: {self.competition}",
            f"- **关键词**: {', '.join(self.keywords) or '无'}",
        ]
        if self.insights:
            lines.append("")
            lines.append("### 评论洞察（聚类 + 证据）")
            for ins in self.insights:
                tag = "👍" if ins.sentiment == "positive" else "⚠️"
                lines.append(f"- {tag} **{ins.topic}**（提及 {ins.mentions} 次，严重度 {ins.severity}）")
                for ev in ins.evidence[:2]:
                    lines.append(f"  - 证据：{ev}")
        return "\n".join(lines)
