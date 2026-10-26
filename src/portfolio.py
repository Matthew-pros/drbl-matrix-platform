from __future__ import annotations

from .models import PortfolioState, Position


def mark_to_market(state: PortfolioState, prices: dict[str, float]) -> PortfolioState:
    for ticker, pos in list(state.positions.items()):
        if ticker in prices and prices[ticker] > 0:
            pos.market_value_usd = pos.quantity * prices[ticker] if pos.quantity else pos.market_value_usd
        if pos.market_value_usd <= 0:
            state.positions.pop(ticker, None)
            if state.active_alm_ticker == ticker:
                state.active_alm_ticker = None
    return state


def target_delta(state: PortfolioState, ticker: str, target_usd: float) -> float:
    current = state.positions.get(ticker)
    return target_usd - (current.market_value_usd if current else 0.0)


def _apply_fill(
    state: PortfolioState,
    ticker: str,
    target_usd: float,
    quantity: float,
    price: float,
    side: str,
    commission: float,
    slippage: float,
    alm_tier: str | None,
    broker_confirmed: bool,
) -> None:
    side = side.upper()
    if not ticker or price <= 0 or quantity < 0 or commission < 0 or slippage < 0 or target_usd < 0:
        raise ValueError("Ticker, cena, množství, cílová pozice a náklady musí být validní.")
    if side not in {"BUY", "SELL"}:
        raise ValueError("Neznámá strana obchodu.")
    notional = quantity * price
    total_cost = commission + slippage
    if side == "BUY":
        if notional + total_cost > state.cash_usd + 1e-6:
            raise ValueError("Nedostatek hotovosti pro simulovaný/potvrzený nákup.")
        state.cash_usd -= notional + total_cost
    else:
        existing_before = state.positions.get(ticker)
        if existing_before is None or quantity > existing_before.quantity + 1e-6:
            raise ValueError("Prodej převyšuje aktuální množství v portfoliu.")
        state.cash_usd += notional - total_cost

    existing = state.positions.get(ticker)
    new_value = max(0.0, target_usd)
    if new_value <= 0.005 or (side == "SELL" and existing and existing.quantity - quantity <= 1e-8):
        state.positions.pop(ticker, None)
    else:
        old_quantity = existing.quantity if existing else 0.0
        new_quantity = old_quantity + quantity if side == "BUY" else max(0.0, old_quantity - quantity)
        state.positions[ticker] = Position(ticker, new_value, new_quantity, price)

    if alm_tier and side == "BUY" and target_usd > 0:
        state.alm_levels_filled.add(alm_tier)
        if state.model.value == "Combined":
            state.active_alm_ticker = ticker
            if broker_confirmed:
                state.alm_completed = True
                state.alm_fill_confirmed = True
    elif side == "SELL" and target_usd <= 0.005 and state.active_alm_ticker == ticker:
        state.active_alm_ticker = None


def apply_confirmed_fill(
    state: PortfolioState, ticker: str, target_usd: float, quantity: float,
    price: float, side: str, commission: float = 0.0, alm_tier: str | None = None,
) -> None:
    """Update state after a broker-reported fill; only this function marks broker confirmation."""
    _apply_fill(state, ticker, target_usd, quantity, price, side, commission, 0.0, alm_tier, True)


def apply_simulated_fill(
    state: PortfolioState, ticker: str, target_usd: float, quantity: float,
    price: float, side: str, commission: float = 0.0, slippage: float = 0.0,
    alm_tier: str | None = None,
) -> None:
    """Record an explicitly user-confirmed paper-ledger fill; never claims broker execution."""
    _apply_fill(state, ticker, target_usd, quantity, price, side, commission, slippage, alm_tier, False)
