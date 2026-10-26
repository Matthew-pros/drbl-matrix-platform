from __future__ import annotations

from datetime import date, timedelta
import os

import pandas as pd
import streamlit as st

from src.strategies.temacd_rotation import (
    AGGRESSIVE_ASSETS,
    CORE_ASSETS,
    TEMACDConfig,
    TEMACD_UNIVERSE,
    run_temacd_backtest,
)
from src.data.yfinance_provider import YahooFinanceProvider

st.set_page_config(page_title="TEMACD Rotace", page_icon="📊", layout="wide")
st.title("TEMACD Volatility-Sized Rotace")
st.caption("Sektorová, agresivní a kombinovaná rotace · ATR sizing · benchmark SPY Buy & Hold")
st.warning("Historický výzkumný backtest, nikoliv příslib výnosu. Žádné skutečné objednávky nejsou odesílány.")

with st.sidebar:
    st.header("Parametry backtestu")
    ibkr_enabled = os.getenv("IBKR_ENABLED", "false").strip().lower() == "true"
    source_options = ["Yahoo Finance · bezplatná historická data"]
    if ibkr_enabled:
        source_options.append("IBKR Gateway · VPS / historická data")
    source_name = st.selectbox("Datový zdroj", source_options)
    if not ibkr_enabled:
        st.caption("Na Streamlit Cloud je aktivní Yahoo Finance; IBKR se povoluje pouze na VPS pomocí IBKR_ENABLED=true.")
    portfolio_name = st.selectbox(
        "Portfolio",
        ["Combined Rotation", "Sector Rotation", "Aggressive Rotation"],
    )
    end_date = st.date_input("Konec období", value=date.today(), max_value=date.today())
    start_date = st.date_input(
        "Začátek vyhodnocení",
        value=date.today() - timedelta(days=365 * 5),
        max_value=end_date,
    )
    initial_equity = st.number_input("Počáteční kapitál (USD)", min_value=1000.0, value=100_000.0, step=5000.0)
    top_n = st.slider("Top N aktiv", min_value=1, max_value=len(TEMACD_UNIVERSE), value=3)
    rebalance = st.selectbox(
        "Rebalancování",
        ["monthly", "weekly"],
        index=0,
        format_func=lambda value: "Měsíčně" if value == "monthly" else "Týdně",
    )
    target_risk_pct = st.number_input("Cílový risk na pozici (%)", min_value=0.1, max_value=10.0, value=1.0, step=0.1)
    max_weight_pct = st.number_input("Max. váha jednoho aktiva (%)", min_value=1.0, max_value=100.0, value=35.0, step=1.0)
    commission_bps = st.number_input("Komise (bps na stranu)", min_value=0.0, max_value=100.0, value=5.0, step=1.0)
    run_button = st.button("Načíst data a spustit backtest", type="primary", use_container_width=True)

if run_button:
    if start_date >= end_date:
        st.error("Začátek musí být před koncem období.")
        st.stop()

    if source_name.startswith("IBKR"):
        from src.data.ibkr_provider import IBKRProvider
        provider = IBKRProvider()
    else:
        provider = YahooFinanceProvider()

    if portfolio_name == "Sector Rotation":
        universe = CORE_ASSETS
    elif portfolio_name == "Aggressive Rotation":
        universe = AGGRESSIVE_ASSETS
    else:
        universe = TEMACD_UNIVERSE

    warmup_start = (pd.Timestamp(start_date) - pd.DateOffset(years=3)).strftime("%Y-%m-%d")
    fetch_end = (pd.Timestamp(end_date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    tickers = list(dict.fromkeys((*universe, "SPY")))
    market_data: dict[str, pd.DataFrame] = {}
    errors: list[str] = []
    bulk_data = None
    if source_name.startswith("Yahoo"):
        try:
            bulk_data = provider.get_many_daily_bars(tickers, warmup_start, fetch_end, force_refresh=True)
        except Exception as exc:
            errors.append(f"Hromadné načtení Yahoo Finance selhalo: {exc}")
            bulk_data = {}
    progress = st.progress(0, text="Načítám historická denní OHLCV data…")

    for i, ticker in enumerate(tickers):
        try:
            if source_name.startswith("Yahoo"):
                item = (bulk_data or {}).get(ticker)
                if item is None or item.bars.empty:
                    raise RuntimeError(item.warning if item is not None else "Ticker chybí v odpovědi Yahoo Finance.")
            else:
                item = provider.get_daily_bars(ticker, warmup_start, fetch_end)
            market_data[ticker] = item.bars
        except Exception as exc:
            errors.append(f"{ticker}: {exc}")
        progress.progress((i + 1) / len(tickers), text=f"Načítání {ticker} ({i + 1}/{len(tickers)})")

    progress.empty()
    try:
        config = TEMACDConfig(
            top_n=top_n,
            rebalance=rebalance,
            target_risk=target_risk_pct / 100.0,
            max_asset_weight=max_weight_pct / 100.0,
            transaction_cost_rate=commission_bps / 10_000.0,
            initial_equity=initial_equity,
        )
        result = run_temacd_backtest(
            market_data,
            config,
            start=start_date.isoformat(),
            end=end_date.isoformat(),
            universe=universe,
        )
    except Exception as exc:
        st.error(f"Backtest se nepodařilo spustit: {exc}")
        st.stop()

    if errors:
        st.warning("Některá aktiva nebyla načtena a budou vynechána:\n\n" + "\n".join(errors))
    if result.warnings:
        with st.expander("Varování backtestu"):
            st.write("\n".join(result.warnings))

    st.caption(f"Portfolio: {portfolio_name} · Zdroj: {source_name} · Signál na Close(t), simulovaná exekuce na Open(t+1)")
    initial = initial_equity
    net_profit = float(result.metrics.get("ending_equity", initial) - initial)
    m1, m2, m3, m4, m5, m6 = st.columns(6)
    m1.metric("Čistý zisk", f"${net_profit:,.0f}")
    m2.metric("Celkový výnos", f"{result.metrics.get('total_return', float('nan')):.2%}")
    m3.metric("CAGR", f"{result.metrics.get('cagr', float('nan')):.2%}")
    m4.metric("Max. drawdown", f"-{result.metrics.get('max_drawdown', float('nan')):.2%}")
    m5.metric("Sharpe", f"{result.metrics.get('sharpe', float('nan')):.2f}")
    m6.metric("Sortino", f"{result.metrics.get('sortino', float('nan')):.2f}")

    st.subheader("Equity křivka vs. SPY Buy & Hold")
    st.line_chart(pd.concat([result.equity, result.benchmark_equity], axis=1).sort_index())

    left, right = st.columns(2)
    with left:
        st.subheader("Rebalanční log")
        if result.rebalance_log.empty:
            st.info("Pro období nejsou žádné rebalanční záznamy.")
        else:
            st.dataframe(result.rebalance_log.tail(150), use_container_width=True, hide_index=True)
            st.download_button(
                "Stáhnout rebalance_log.csv",
                result.rebalance_log.to_csv(index=False).encode("utf-8"),
                "rebalance_log.csv", "text/csv",
            )
    with right:
        st.subheader("ATR váhy")
        if result.weights.empty:
            st.info("Váhy zatím nejsou k dispozici.")
        else:
            st.dataframe(result.weights.tail(150), use_container_width=True, hide_index=True)
            st.download_button(
                "Stáhnout weights.csv",
                result.weights.to_csv(index=False).encode("utf-8"),
                "weights.csv", "text/csv",
            )

    st.subheader("Obchody a transakční náklady")
    st.write(
        f"Simulované exekuce: {len(result.trades)} · náklady: "
        f"${result.total_transaction_costs:,.2f} · náklad na stranu: {commission_bps:g} bps"
    )
    if not result.trades.empty:
        st.dataframe(result.trades.tail(150), use_container_width=True, hide_index=True)
        st.download_button(
            "Stáhnout trades.csv",
            result.trades.to_csv(index=False).encode("utf-8"),
            "trades.csv", "text/csv",
        )
else:
    st.info("Vyber portfolio, datový zdroj a období v levém panelu a spusť backtest.")
    st.markdown(
        "Výchozím zdrojem jsou bezplatná historická data Yahoo Finance. Na vlastním VPS "
        "lze zvolit historická data z IBKR Gateway. Tato stránka pouze čte historická data; "
        "neodesílá příkazy brokerovi."
    )
