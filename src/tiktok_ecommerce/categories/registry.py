"""品类注册表：集中管理可用品类。

- get_category(name)：按名称取品类，未注册回退到通用配置
- list_categories()：列出全部可用品类（CLI / Web 界面共用）
"""
from __future__ import annotations

from tiktok_ecommerce.categories.base import CategoryProfile
from tiktok_ecommerce.categories.bedding import BeddingProfile
from tiktok_ecommerce.categories.examples import ApparelProfile, ElectronicsProfile

# 品类注册表（新增品类在此注册）
_CATEGORIES: dict[str, CategoryProfile] = {
    "bedding": BeddingProfile(),
    "electronics": ElectronicsProfile(),
    "apparel": ApparelProfile(),
}

# 默认品类：床上用品（主推）
DEFAULT_CATEGORY = "bedding"


class _DefaultProfile(CategoryProfile):
    """未注册品类的通用兜底。"""

    name = "default"
    display_name = "通用品类"
    description = "未配置领域知识的品类，使用通用选品逻辑"
    selection_dimensions = [
        "产品核心功能与卖点",
        "目标市场价格带与竞争",
        "物流与合规风险",
    ]
    review_analysis_focus = ["质量投诉", "功能是否符合宣传", "性价比"]
    keyword_templates = ["{style} 批发", "{style} 工厂 货源"]


_DEFAULT_PROFILE = _DefaultProfile()


def get_category(name: str | None) -> CategoryProfile:
    """按名称取品类配置；未注册/空值回退通用。"""
    if not name:
        return _CATEGORIES[DEFAULT_CATEGORY]
    return _CATEGORIES.get(name.lower(), _DEFAULT_PROFILE)


def list_categories() -> list[dict[str, str]]:
    """返回可用品类列表（名称/显示名/描述）。"""
    return [
        {"name": p.name, "display_name": p.display_name, "description": p.description}
        for p in _CATEGORIES.values()
    ]
