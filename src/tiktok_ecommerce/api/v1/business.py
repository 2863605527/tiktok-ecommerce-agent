"""经营测算接口：POST /api/v1/business/profit（单件利润测算，参数化可调）。"""
from __future__ import annotations

from fastapi import APIRouter, Depends

from tiktok_ecommerce.api.v1.auth import get_current_user
from tiktok_ecommerce.common.logging import get_logger
from tiktok_ecommerce.config import get_settings
from tiktok_ecommerce.services.profit import ProfitRequest, ProfitResult, compute_profit

logger = get_logger(__name__)
router = APIRouter()


@router.post("/business/profit", response_model=ProfitResult)
def estimate_profit(
    req: ProfitRequest,
    user=Depends(get_current_user),
) -> ProfitResult:
    """单件利润测算：售价(JPY) + 成本/运费(CNY) → 毛利/净利/净利率/回本件数。"""
    fx = None
    try:
        fx = float(get_settings().fx_cny_jpy) if get_settings().fx_cny_jpy else None
    except Exception:
        fx = None
    result = compute_profit(req, default_fx=fx or 21.0)
    logger.info("利润测算: 售价=%.0fJPY 成本=%.2fCNY 净利=%.1fJPY 净利率=%.1f%% user=%s",
                req.selling_price_jpy, req.cost_cny, result.net_profit_jpy,
                result.net_margin * 100, user.id)
    return result
