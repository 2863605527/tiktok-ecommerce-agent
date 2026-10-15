"""示例品类：电子产品、服装 —— 展示品类体系的扩展性。

新增品类只需三步：
1. 继承 CategoryProfile 写一个配置类
2. 在 registry 注册
3. 前端/CLI 自动出现该品类选项
"""
from tiktok_ecommerce.categories.base import CategoryProfile


class ElectronicsProfile(CategoryProfile):
    """电子产品品类（示例）。"""

    name = "electronics"
    display_name = "电子产品"
    description = "3C数码类目（耳机、充电器、小家电等），核心看参数、兼容性与售后"

    selection_dimensions = [
        "核心参数（续航、功率、接口协议）——是否满足目标市场需求",
        "兼容性（苹果/安卓/协议版本）",
        "认证合规（CE/FCC/PSE 等目标市场认证）",
        "售后与保修（跨境电子产品退货率高）",
    ]

    review_analysis_focus = [
        "续航/性能是否符合宣传",
        "兼容性投诉（连不上/不识别）",
        "做工与品控",
        "售后体验",
    ]

    keyword_templates = [
        "无线蓝牙耳机 工厂 批发",
        "快充 充电器 type-c 批发",
        "智能小家电 出口 工厂",
    ]

    listing_guidelines = [
        "标题含核心参数（容量/功率/协议）",
        "标注认证标识",
        "注明兼容设备清单",
    ]

    market_notes = {
        "JP": "日本需 PSE 认证，110V 电压，标题建议日语。",
        "US": "美国需 FCC 认证，120V 电压，注意插头标准。",
        "*": "电子产品务必核对目标市场认证与电压。",
    }


class ApparelProfile(CategoryProfile):
    """服装品类（示例）。"""

    name = "apparel"
    display_name = "服装"
    description = "服饰类目，核心看版型、尺码体系与面料"

    selection_dimensions = [
        "版型与剪裁（欧美/日韩版型差异大）",
        "尺码体系（S/M/L vs 数字码，需对照表）",
        "面料与季节属性",
        "退货率（服装类目退货率最高）",
    ]

    review_analysis_focus = [
        "尺码是否偏大偏小",
        "面料触感与色差",
        "版型上身效果",
        "做工质量",
    ]

    keyword_templates = [
        "T恤 纯棉 批发 出口",
        "卫衣 加绒 工厂",
        "瑜伽裤 高腰 批发",
    ]

    listing_guidelines = [
        "必须附尺码对照表（厘米+英寸）",
        "标注面料成分",
        "注明版型（宽松/修身）",
    ]

    market_notes = {
        "US": "美国版型普遍偏大，尺码表需实测。",
        "EU": "欧洲常用数字码（36-46），注意欧码转换。",
        "*": "服装务必提供真实测量尺码表。",
    }
