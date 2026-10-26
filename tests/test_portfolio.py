from src.models import ModelName, PortfolioState, Position
from src.portfolio import apply_confirmed_fill, mark_to_market


def test_shadow_fill_updates_position_cash_and_alm_tier():
    state = PortfolioState(ModelName.COMBINED, cash_usd=10_000.0)
    apply_confirmed_fill(
        state, "SPY", target_usd=2_000.0, quantity=20.0,
        price=100.0, side="BUY", commission=1.0, alm_tier="crash_event",
    )
    assert state.cash_usd == 7_999.0
    assert state.positions["SPY"].quantity == 20.0
    assert "crash_event" in state.alm_levels_filled
    assert state.alm_completed and state.alm_fill_confirmed
    assert state.active_alm_ticker == "SPY"

    mark_to_market(state, {"SPY": 90.0})
    assert state.positions["SPY"].market_value_usd == 1_800.0
    assert state.equity_usd == 9_799.0


def test_matrix_trade_does_not_mark_alm_completed():
    state = PortfolioState(ModelName.COMBINED, cash_usd=10_000.0)
    apply_confirmed_fill(
        state, "TQQQ", target_usd=5_000.0, quantity=50.0,
        price=100.0, side="BUY", commission=1.0,
    )
    assert not state.alm_completed
    assert not state.alm_fill_confirmed
    assert not state.alm_levels_filled


def test_active_crisis_alm_ticker_is_tracked_and_cleared_on_exit():
    state = PortfolioState(ModelName.COMBINED, cash_usd=10_000.0)
    apply_confirmed_fill(
        state, "SPY", target_usd=2_000.0, quantity=20.0,
        price=100.0, side="BUY", commission=1.0, alm_tier="crash_event",
    )
    assert state.active_alm_ticker == "SPY"

    apply_confirmed_fill(
        state, "SPY", target_usd=0.0, quantity=20.0,
        price=100.0, side="SELL", commission=1.0,
    )
    assert state.active_alm_ticker is None


def test_simulated_crisis_fill_never_claims_broker_confirmation():
    from src.portfolio import apply_simulated_fill

    state = PortfolioState(ModelName.COMBINED, cash_usd=10_000.0)
    apply_simulated_fill(
        state, "SPY", target_usd=2_000.0, quantity=20.0,
        price=100.0, side="BUY", commission=1.0, slippage=2.0, alm_tier="crash_event",
    )
    assert state.cash_usd == 7_997.0
    assert state.active_alm_ticker == "SPY"
    assert "crash_event" in state.alm_levels_filled
    assert state.alm_completed is False
    assert state.alm_fill_confirmed is False


def test_simulated_sell_includes_slippage_and_removes_empty_position():
    from src.portfolio import apply_simulated_fill

    state = PortfolioState(
        ModelName.DRBL_MATRIX,
        cash_usd=0.0,
        positions={"QQQ": Position("QQQ", 1_000.0, 10.0, 100.0)},
    )
    apply_simulated_fill(
        state, "QQQ", target_usd=0.0, quantity=10.0,
        price=100.0, side="SELL", commission=1.0, slippage=2.0,
    )
    assert state.cash_usd == 997.0
    assert "QQQ" not in state.positions
