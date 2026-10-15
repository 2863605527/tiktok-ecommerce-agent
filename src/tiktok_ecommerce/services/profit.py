"""利润测算：TikTok 日本站卖家单件利润模型（真实落地、可调参）。

业务模型（参数全部可配置，默认值基于行业常规并在结果中标注「估算」）：
- 收入：售价（JPY，TikTok 站内成交价）
- 成本：进价（CNY）+ 国内运费（CNY）+ 国际段运费（CNY）→ 按汇率折 JPY
- 平台费用：TikTok Shop 佣金率（默认 8%，可配）+ 支付通道费（默认 2%，可配）
- 广告费（JPY，可选）
- 产出：毛利（售价-总成本）、平台费、净利、净利率、保本销量（广告回本件数）

单件利润是卖家最关心的数字；口径透明（汇率/费率来源标注估算），
参数化而非写死，方便按真实平台政策调整。
"""
from __future__ import annotations

from pydantic import BaseModel, Field


class ProfitRequest(BaseModel):
    """利润测算请求（金额单位：售价 JPY，成本/运费 CNY）。"""

    selling_price_jpy: float = Field(..., gt=0, description="TikTok 售价（日元）")
    cost_cny: float = Field(..., ge=0, description="商品进价（人民币）")
    shipping_cny: float = Field(0, ge=0, description="国内+国际运费合计（人民币）")
    ads_jpy: float = Field(0, ge=0, description="单件广告分摊（日元，可选）")
    platform_fee_rate: float = Field(0.08, ge=0, le=0.5, description="平台佣金率（默认 8%，估算）")
    payment_fee_rate: float = Field(0.02, ge=0, le=0.5, description="支付通道费率（默认 2%，估算）")
    fx_cny_jpy: float | None = Field(None, gt=0, description="汇率 CNY→JPY，空=用配置默认值")


class ProfitResult(BaseModel):
    """利润测算结果（全部金额 JPY，除注明外）。"""

    selling_price_jpy: float
    cost_jpy: float
    shipping_jpy: float
    gross_profit_jpy: float
    platform_fee_jpy: float
    payment_fee_jpy: float
    ads_jpy: float
    net_profit_jpy: float
    net_margin: float            # 净利率（净利/售价，0-1）
    break_even_units: float | None  # 广告回本件数（净利>0 时有意义）
    fx_used: float               # 实际使用的汇率
    platform_fee_rate: float
    payment_fee_rate: float
    note: str                    # 口径说明（标注估算项）


def compute_profit(req: ProfitRequest, default_fx: float = 21.0) -> ProfitResult:
    """按请求参数计算单件利润。

    default_fx：CNY→JPY 汇率默认值（约 1 CNY ≈ 21 JPY，2026 年区间）；
    配置可覆盖：.env FX_CNY_JPY=21。
    """
    fx = req.fx_cny_jpy or default_fx
    cost_jpy = round(req.cost_cny * fx, 1)
    shipping_jpy = round(req.shipping_cny * fx, 1)
    gross = round(req.selling_price_jpy - cost_jpy - shipping_jpy, 1)
    fee = round(req.selling_price_jpy * req.platform_fee_rate, 1)
    pay = round(req.selling_price_jpy * req.payment_fee_rate, 1)
    net = round(gross - fee - pay - req.ads_jpy, 1)
    margin = round(net / req.selling_price_jpy, 4) if req.selling_price_jpy > 0 else 0.0
    break_even = None
    if net > 0 and req.ads_jpy > 0:
        break_even = round(req.ads_jpy / net, 1)

    note = (
        f"汇率按 1 CNY ≈ {fx} JPY（{fx} 为可配置默认值，属估算）；"
        f"平台佣金率 {req.platform_fee_rate:.0%}、支付费率 {req.payment_fee_rate:.0%} "
        f"为行业估算值，请按 TikTok Shop 日本站当期政策核对；"
        f"运费为进价/运费合计的估算，未计关税与海外仓费用。"
    )
    return ProfitResult(
        selling_price_jpy=req.selling_price_jpy,
        cost_jpy=cost_jpy, shipping_jpy=shipping_jpy,
        gross_profit_jpy=gross,
        platform_fee_jpy=fee, payment_fee_jpy=pay, ads_jpy=req.ads_jpy,
        net_profit_jpy=net, net_margin=margin, break_even_units=break_even,
        fx_used=fx, platform_fee_rate=req.platform_fee_rate,
        payment_fee_rate=req.payment_fee_rate, note=note,
    )
