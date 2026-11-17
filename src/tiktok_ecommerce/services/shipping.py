"""日本站跨境运费估算：按重量 + 日本专线小包计费规则推算单件运费（估算模型）。

业务背景：TikTok Shop 日本站跨境卖家（中国直发）在利润测算时，
用户常常只给售价和进价、不给运费。把运费当 0 会把利润算虚高，
这里按行业常规费率估算，并把口径标注为「估算」。

估算规则（可在 .env 覆盖）：
- 渠道：中国 → 日本 跨境专线小包（日本站跨境卖家最常用）
- 首重 0.5kg：42 元（SHIPPING_FIRST_PRICE_CNY）
- 续重：28 元/kg（SHIPPING_EXTRA_PER_KG_CNY），按每 0.5kg 向上取整计费
- 未计关税/清关（单票 < 1 万日元日本通常免税），未计日本国内派送
  （若走日本海外仓，需再叠加 ヤマト/佐川 60 サイズ ≈ 750 日元）

例：1kg → 42 + 1×14 = 56 元；2kg → 42 + 3×14 = 84 元。
"""
from __future__ import annotations

import math
import re

from pydantic import BaseModel

# 重量解析：重量1.2kg / 毛重500g / 重量：2公斤 / 重 3kg
_WEIGHT_RE = re.compile(
    r"(?:重量|毛重|重)\s*[:：=]?\s*(\d+(?:\.\d+)?)\s*(kg|KG|Kg|公斤|千克|g|G|克)?")
_MIN_WEIGHT_KG = 0.05
_MAX_WEIGHT_KG = 30.0


class ShippingEstimate(BaseModel):
    """运费估算结果（CNY）。"""

    weight_kg: float
    cost_cny: float
    channel: str = "中国→日本 专线小包"
    grade: str          # 计费档位说明（首重/续重拆解）
    note: str           # 口径说明（标注估算、未计项）
    estimated: bool = True


def parse_weight_kg(message: str) -> float | None:
    """从消息里解析重量（kg）；无重量或超出合理区间 → None。

    支持：重量1.2kg / 毛重500g / 重量2公斤；不带单位按 kg 处理。
    """
    m = _WEIGHT_RE.search(message or "")
    if not m:
        return None
    try:
        value = float(m.group(1))
    except ValueError:
        return None
    unit = (m.group(2) or "kg").lower()
    weight = value / 1000 if unit in ("g", "克") else value
    if not (_MIN_WEIGHT_KG <= weight <= _MAX_WEIGHT_KG):
        return None
    return round(weight, 3)


def estimate_shipping_cny(
    weight_kg: float,
    *,
    first_weight_kg: float = 0.5,
    first_price_cny: float = 42.0,
    extra_per_kg_cny: float = 28.0,
) -> ShippingEstimate:
    """按首重 + 续重规则估算跨境运费（CNY）。

    weight_kg：单件重量（kg）；续重按 0.5kg 档位向上取整（物流计费惯例）。
    """
    w = max(float(weight_kg or 0), first_weight_kg)
    if w <= first_weight_kg:
        cost = first_price_cny
        grade = f"首重 {first_weight_kg:g}kg 内 {first_price_cny:g} 元"
    else:
        units = math.ceil((w - first_weight_kg) / 0.5)
        per_half_kg = extra_per_kg_cny / 2
        cost = first_price_cny + units * per_half_kg
        grade = (f"首重 {first_price_cny:g} 元 + 续重 {units}×0.5kg"
                 f"×{per_half_kg:g} 元")
    note = (
        "按中国→日本 专线小包行业常规费率估算："
        f"首重 {first_weight_kg:g}kg {first_price_cny:g} 元、"
        f"续重 {extra_per_kg_cny:g} 元/kg；未计关税/清关与日本国内派送，"
        f"实际以货代报价为准。"
    )
    return ShippingEstimate(
        weight_kg=round(w, 3),
        cost_cny=round(cost, 1),
        grade=grade,
        note=note,
    )
