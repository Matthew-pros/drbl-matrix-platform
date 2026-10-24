import pytest
from src.config import CostConfig
from src.costs import estimate_costs, preview_quantity

def test_commission_minimum_applies_per_order():
    cfg=CostConfig(commission_per_share=.0035,minimum_per_order=.35,slippage_bps_per_side=10)
    estimate=estimate_costs(10,100,"buy",cfg)
    assert estimate.commission_usd==pytest.approx(.35)
    assert estimate.slippage_usd==pytest.approx(1.0)
    assert estimate.fill_price==pytest.approx(100.1)

def test_sell_slippage_reduces_fill_price():
    cfg=CostConfig(slippage_bps_per_side=25)
    assert estimate_costs(2,100,"sell",cfg).fill_price==pytest.approx(99.75)

def test_fractional_disabled_rounds_quantity():
    cfg=CostConfig(fractional_shares=False)
    _,qty,_,_=preview_quantity(1000,0,333,cfg)
    assert qty==3
