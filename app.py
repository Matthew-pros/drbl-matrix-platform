from __future__ import annotations

import logging
import os
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import streamlit as st

from src.backtest.engine import run_backtest
from src.backtest.metrics import monthly_returns
from src.broker.ibkr_adapter import IBKROrderAdapter
from src.config import AVAILABLE_FACTORS, BASE_TICKERS, DEFAULT_FACTORS, CostConfig, StrategyConfig, APP_NAME
from src.data.yfinance_provider import YahooFinanceProvider
from src.models import DataMode, ModelName, PortfolioState
from src.services.recommendation_service import recommend
from src.storage import list_backtests, save_backtest
from src.portfolio import apply_simulated_fill, mark_to_market
from src.strategies.drbl_matrix import ASSETS, process_monthly_rotation

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
LOG = logging.getLogger(__name__)
st.set_page_config(page_title=APP_NAME, page_icon="📈", layout="wide", initial_sidebar_state="expanded")
st.markdown("""
<style>
.block-container {max-width: 1500px; padding-top: 1.4rem; padding-bottom: 3rem;}
[data-testid="stMetric"] {background: var(--secondary-background-color); border: 1px solid rgba(128,128,128,.18); padding: 12px 15px; border-radius: 12px;}
</style>
""", unsafe_allow_html=True)
st.title("DRBL Matrix Platform")
st.caption("ALM · DRBL Matrix · Combined | Portfoliová měna USD | UI Europe/Prague | burza America/New_York")
st.warning("Jde o analytický prototyp a historickou simulaci, nikoli o garanci výnosu. Automatické odesílání pokynů je vypnuto; IBKR se používá pouze read-only a pro order preview.")

with st.sidebar:
    st.header("Model a kapitál")
    model = ModelName(st.selectbox("Model", [m.value for m in ModelName], index=1))
    initial_equity = st.number_input("Počáteční equity (USD)", min_value=100.0, value=100_000.0, step=5_000.0)
    start_date = st.date_input("Začátek vyhodnocení", value=date.today() - timedelta(days=365 * 5), max_value=date.today())
    end_date = st.date_input("Konec vyhodnocení", value=date.today(), min_value=start_date, max_value=date.today())
    ibkr_enabled = os.getenv("IBKR_ENABLED", "false").strip().lower() == "true"
    source_options = ["Yahoo Finance · historical"]
    if ibkr_enabled:
        source_options.append("IBKR Gateway · read-only historical")
    source_kind = st.selectbox("Datový zdroj", source_options)
    if ibkr_enabled:
        st.caption("IBKR Gateway = historická/read-only data. Nejde o garantovaný live feed.")
    else:
        st.caption("Streamlit Cloud používá Yahoo Finance. IBKR volba se zobrazí jen na VPS při IBKR_ENABLED=true.")
    st.divider()
    risk_overlay_enabled = st.checkbox(
        "Zapnout risk-off ochranu", value=True,
        help="Risk-off má přednost před běžným signálem Matrix a blokuje nové vstupy.",
    )
    with st.expander("Risk-off a krizový ALM"):
        risk_off_vix_threshold = st.number_input("Silný risk-off: VIX ≥", min_value=15.0, max_value=80.0, value=35.0, step=1.0)
        risk_elevated_vix_threshold = st.number_input("Zvýšený VIX", min_value=10.0, max_value=60.0, value=25.0, step=1.0)
        risk_vix_spike_threshold = st.slider("Růst VIX za 5 seancí (%)", 10, 100, 35, 5) / 100.0
        risk_crash_daily_return = st.slider("Denní pokles pro crash tripwire (%)", -10, -1, -4, 1) / 100.0
        risk_crash_range_multiple = st.number_input("Rozsah svíčky / průměrný rozsah", 1.5, 6.0, 3.0, 0.5)
        risk_crash_cooldown_sessions = st.slider(
            "Crash spouštěč platí (obchodní seance)", min_value=1, max_value=10, value=5,
            help="Umožní nejprve uzavřít Matrix pozici a až potom otevřít krizový ALM starter.",
        )
        crisis_alm_enabled = st.checkbox("Povolit krizový starter pouze pro SPY/QQQ", value=True)
        crisis_alm_drawdown = st.slider("Minimální drawdown pro krizový starter (%)", 10, 40, 15, 5) / 100.0
        crisis_alm_allocation = st.slider("Velikost krizového starteru (% equity)", 5, 20, 10, 5) / 100.0
    st.divider()
    st.header("Faktory podle aktiva")
    factors = {asset: st.selectbox(f"{asset} faktor", AVAILABLE_FACTORS, index=AVAILABLE_FACTORS.index(DEFAULT_FACTORS[asset]), key=f"factor_{asset}") for asset in ASSETS}
    gld_lev = st.text_input("Vlastní pákový ticker GLD", value="").strip().upper() or None
    btc_lev = st.text_input("Vlastní pákový ticker BTC (volitelné; broker-validní)", value="").strip().upper() or None
    st.caption("Ticker pákového GLD/BTC se nikdy neodhaduje. IBIT se nepákuje.")
    st.divider()
    st.header("Náklady a exekuce")
    commission_profile = st.selectbox("Komisní profil", ["IBKR Pro Tiered · odhad", "IBKR Pro Fixed · odhad", "Vlastní sazby"])
    commission_default = 0.0035 if commission_profile.startswith("IBKR Pro Tiered") else 0.005 if commission_profile.startswith("IBKR Pro Fixed") else 0.0035
    commission = st.number_input("Komise USD/akcii", min_value=0.0, value=commission_default, step=0.0005, format="%.4f")
    minimum = st.number_input("Min. komise USD/pokyn", min_value=0.0, value=0.35, step=0.05)
    extra = st.number_input("Další poplatky USD/akcii", min_value=0.0, value=0.0, step=0.0005, format="%.4f")
    slippage = st.select_slider("Slippage na stranu (bps)", options=[0, 5, 10, 25, 50], value=10)
    cash_interest = st.number_input("Roční úročení hotovosti (%)", min_value=0.0, max_value=10.0, value=0.0, step=0.25, format="%.2f", help="Zadej procenta p.a.; například 4.00 znamená 4 % ročně.") / 100.0
    fractional = st.checkbox("Povolit frakční kusy v simulaci", value=True)
    fetch = st.button("Načíst / obnovit data", type="primary", use_container_width=True)
    reset_portfolio = st.button("Resetovat lokální stínové portfolio", use_container_width=True)

config = StrategyConfig(
    initial_equity=initial_equity,
    factor_by_asset=factors,
    gld_leveraged_ticker=gld_lev,
    btc_leveraged_ticker=btc_lev,
    risk_overlay_enabled=risk_overlay_enabled,
    risk_off_vix_threshold=risk_off_vix_threshold,
    risk_elevated_vix_threshold=risk_elevated_vix_threshold,
    risk_vix_spike_threshold=risk_vix_spike_threshold,
    risk_crash_daily_return=risk_crash_daily_return,
    risk_crash_range_multiple=risk_crash_range_multiple,
    risk_crash_cooldown_sessions=risk_crash_cooldown_sessions,
    crisis_alm_enabled=crisis_alm_enabled,
    crisis_alm_drawdown=crisis_alm_drawdown,
    crisis_alm_allocation=crisis_alm_allocation,
)
costs = CostConfig(
    profile=commission_profile,
    commission_per_share=commission,
    minimum_per_order=minimum,
    additional_fee_per_share=extra,
    slippage_bps_per_side=float(slippage),
    fractional_shares=fractional,
    cash_interest_annual=cash_interest,
)

@st.cache_data(ttl=900, show_spinner=False)
def load_data(
    end: str, source: str, ticker_pairs: tuple[tuple[str, str], ...],
    refresh_generation: int = 0,
) -> tuple[dict[str, pd.DataFrame], dict[str, str], str]:
    """Načti kompletní dostupnou historii pro ALM ATH, rotaci a indikátorový warm-up."""
    if source.startswith("IBKR"):
        from src.data.ibkr_provider import IBKRProvider
        provider = IBKRProvider()
    else:
        provider = YahooFinanceProvider()
    data: dict[str, pd.DataFrame] = {}
    data_source: dict[str, str] = {}
    failures: list[str] = []
    end_exclusive = (pd.Timestamp(end) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    request_start = "1990-01-01"
    use_yahoo_batch = not source.startswith("IBKR")
    yahoo_batch = {}
    if use_yahoo_batch:
        try:
            yahoo_batch = provider.get_many_daily_bars(
                [ticker for _logical, ticker in ticker_pairs], request_start, end_exclusive,
                force_refresh=refresh_generation > 0,
            )
        except Exception as exc:
            failures.append(f"Yahoo Finance hromadné načtení selhalo: {exc}")
            LOG.warning("Hromadné načtení Yahoo Finance selhalo: %s", exc)

    for logical, ticker in ticker_pairs:
        try:
            if use_yahoo_batch:
                result = yahoo_batch.get(ticker)
                if result is None:
                    raise RuntimeError("Ticker není v odpovědi hromadného načtení; opakuj načtení po kontrole sítě.")
            else:
                request_ticker = "VIX" if source.startswith("IBKR") and ticker == "^VIX" else ticker
                result = provider.get_daily_bars(request_ticker, request_start, end_exclusive)
            if result.bars.empty:
                raise RuntimeError(result.warning or "prázdná historie")
            # Keep logical and provider ticker aliases for downstream strategy lookups.
            data[logical] = result.bars
            data[ticker] = result.bars
            data_source[logical] = f"{result.source} · {result.mode.value} · {result.last_timestamp}"
        except Exception as exc:
            failures.append(f"{logical} ({ticker}): {exc}")
            LOG.warning("Načtení %s/%s selhalo: %s", logical, ticker, exc)
    return data, data_source, "\n".join(failures)

pairs: dict[str, str] = dict(BASE_TICKERS)
pairs.update({"UPRO": "UPRO", "TQQQ": "TQQQ", "VIX": "^VIX"})
if gld_lev:
    pairs["GLD_3X"] = gld_lev
if btc_lev:
    pairs["BTCUSD_3X"] = btc_lev
# Deployment startup must not perform remote market-data downloads automatically.
# The user explicitly starts the download; subsequent reruns reuse Streamlit's data cache.
if "data_refresh_generation" not in st.session_state:
    st.session_state["data_refresh_generation"] = 0

if fetch:
    load_data.clear()
    st.session_state["market_data_loaded"] = True
    st.session_state["data_refresh_generation"] += 1

if not st.session_state.get("market_data_loaded", False):
    st.info(
        "Aplikace je připravena. Historická data se zatím nestahují, aby se úvodní načtení "
        "na Streamlit Cloud nezablokovalo. Zkontroluj nastavení a v levém panelu klikni na "
        "„Načíst / obnovit data“."
    )
    st.caption(
        "Yahoo Finance poskytuje historická data bez garance dostupnosti. Kompletní historické "
        "řady a warm-up indikátorů se načtou až po výslovném spuštění."
    )
    status_cols = st.columns(3)
    status_cols[0].metric("Stav aplikace", "Připravena")
    status_cols[1].metric("Datový zdroj", "Yahoo Finance" if source_kind.startswith("Yahoo") else "IBKR Gateway")
    status_cols[2].metric("Síťová volání", "Zatím žádná")
    st.subheader("Co aplikace obsahuje")
    overview = st.columns(3)
    overview[0].markdown(
        "**ALM**\n\nStupňované tranše podle drawdownu SPY/QQQ. "
        "V Combined režimu je ALM vyhrazen pouze pro krizový starter."
    )
    overview[1].markdown(
        "**DRBL Matrix**\n\nMěsíční rotační faktor, trendové filtry, "
        "ATR/RVOL/ADX a risk-off ochrana."
    )
    overview[2].markdown(
        "**TEMACD rotace**\n\nSektorové a agresivní universe, ATR sizing, "
        "equity vs. SPY a audit rebalancování na samostatné stránce."
    )
    st.info(
        "Pro načtení dashboardu klikni vlevo na „Načíst / obnovit data“. "
        "Pokud se stahování nezdaří, aplikace zobrazí chybu každého symbolu místo nekonečného načítání."
    )
    st.stop()

with st.spinner("Načítám historická denní data; první stažení může trvat déle…"):
    market_data, source_map, load_errors = load_data(
        end_date.isoformat(), source_kind, tuple(pairs.items()),
        int(st.session_state["data_refresh_generation"]),
    )
if not market_data or "SPY" not in market_data:
    # SPY is the required exchange-session calendar and benchmark. Partial data for
    # other tickers must not let the app continue into misleading recommendations.
    st.session_state["market_data_loaded"] = False
    st.error("Nepodařilo se načíst povinná historická data SPY. Bez SPY nelze bezpečně sestavit kalendář portfolia ani benchmark.")
    if load_errors:
        st.code(load_errors)
    st.info("Zkontroluj chybové hlášky a klikni na „Načíst / obnovit data“ pro nový pokus.")
    st.stop()
if load_errors:
    with st.expander("Neúplná data / chyby poskytovatele"):
        st.code(load_errors)
# Use the last completed SPY exchange session as the strategy timestamp. Crypto has
# weekend bars; using its newest timestamp would falsely date ETF signals on Saturday/Sunday.
spy_history = market_data.get("SPY")
if spy_history is not None and not spy_history.empty:
    last_timestamp = pd.Timestamp(spy_history.index[-1]).to_pydatetime()
else:
    last_timestamp = max(
        pd.Timestamp(frame.index[-1]).to_pydatetime()
        for frame in market_data.values() if not frame.empty
    )

# Každý model má zcela vlastní stav.
state_key = f"portfolio_{model.value}"
if state_key not in st.session_state or reset_portfolio:
    st.session_state[state_key] = PortfolioState(model, initial_equity)
state: PortfolioState = st.session_state[state_key]
if not state.positions and abs(state.cash_usd - initial_equity) > 1e-6:
    state.cash_usd = initial_equity
latest_prices = {
    ticker: float(frame["Close"].iloc[-1])
    for ticker, frame in market_data.items()
    if frame is not None and not frame.empty and pd.notna(frame["Close"].iloc[-1])
}
mark_to_market(state, latest_prices)

# Rotaci vyhodnoť pouze ve vhodný plánovaný den; nikdy ji nespouštěj z denního signálu mimo plán.
if model == ModelName.DRBL_MATRIX or (
    model == ModelName.COMBINED and state.active_alm_ticker is None
):
    rotation_date = last_timestamp.date().isoformat()
    rotation_frames = {asset: market_data[asset] for asset in ASSETS if asset in market_data}
    try:
        old_leader = state.selected_asset
        new_leader, changed, scores = process_monthly_rotation(rotation_frames, state, config, rotation_date)
        if changed:
            st.info(f"Plánovaná rotace: {old_leader or 'bez lídra'} → {new_leader}. Je-li pozice otevřená, doporučení nejprve uzavře starý ticker.")
    except Exception as exc:
        LOG.warning("Měsíční rotace není dostupná: %s", exc)

view_options = ["Dashboard", "Denní doporučení", "Backtest", "Porovnání", "Nastavení"]
requested_view = st.session_state.pop("requested_view", "Dashboard")
if requested_view not in view_options:
    requested_view = "Dashboard"
view = st.radio("Sekce", view_options, index=view_options.index(requested_view), horizontal=True, label_visibility="collapsed")

if view in {"Dashboard", "Denní doporučení"}:
    rec = recommend(
        model, market_data, state, config, costs,
        source="Yahoo Finance historical" if source_kind.startswith("Yahoo") else "IBKR historical",
        data_mode=DataMode.HISTORICAL, latest_timestamp=last_timestamp,
        gld_leveraged_ticker=gld_lev, btc_leveraged_ticker=btc_lev,
    )
    current_equity = state.equity_usd
    if view == "Dashboard":
        st.subheader("Dashboard")
        cols = st.columns(5)
        cols[0].metric("Model", model.value)
        cols[1].metric("Equity USD", f"${current_equity:,.2f}")
        cols[2].metric("Hotovost USD", f"${state.cash_usd:,.2f}")
        cols[3].metric("Vybraný lídr", state.selected_asset or "—")
        cols[4].metric("Režim", state.current_regime.value)
        st.caption(f"Poslední bar: {last_timestamp} · zdroj: {rec.source} · režim dat: {rec.data_mode.value}. Data z Yahoo se nikdy nevydávají za live.")
        st.subheader("Poslední pravidlové doporučení")
    else:
        st.subheader("Denní doporučení")
        st.caption("Signál vzniká z posledního dostupného uzavřeného baru a případná exekuce je určena pro následující seanci.")
    if not rec.available:
        st.error(f"Doporučení nedostupné: {rec.reason}")
    else:
        if rec.regime.value == "A": st.success("Režim A · 3× páka povolena pouze při splnění ADX, RVOL a ATR filtru")
        elif rec.regime.value == "B": st.warning("Režim B · základní 1× podklad")
        elif rec.regime.value == "C": st.error("Režim C · cash / uzavření pozice")
        else: st.info("Zatím není aktivní jednoznačný vstupní režim")
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Akce", rec.action)
        c2.metric("Ticker", rec.ticker or "—")
        c3.metric("Cílová pozice", f"${rec.target_usd:,.2f}")
        c4.metric("Delta", f"${rec.delta_usd:+,.2f}")
        st.write(rec.reason)
        st.caption(f"Zdroj: {rec.source} · data: {rec.data_mode.value} · timestamp: {rec.as_of} · {'předběžná' if rec.provisional else 'finální historická'} data")
        n1, n2 = st.columns(2)
        n1.metric("Odhad komise", f"${rec.estimated_commission_usd:,.2f}")
        n2.metric("Odhad slippage", f"${rec.estimated_slippage_usd:,.2f}", help=f"Modelový předpoklad {slippage} bps na každou stranu.")
        if rec.ticker:
            px_frame = market_data.get(rec.ticker)
            asset_key = next((asset for asset, ticker in {**BASE_TICKERS, "UPRO":"UPRO", "TQQQ":"TQQQ", "GLD_3X":gld_lev, "BTCUSD_3X":btc_lev}.items() if ticker == rec.ticker), None)
            if px_frame is None and asset_key:
                px_frame = market_data.get(asset_key)
            if px_frame is not None and not px_frame.empty:
                ref_px = float(px_frame["Close"].iloc[-1])
                adapter = IBKROrderAdapter(costs, fractional_allowed=fractional)
                current_value = state.positions.get(rec.ticker).market_value_usd if rec.ticker in state.positions else 0.0
                preview = adapter.preview_order(rec.ticker, rec.target_usd, current_value, ref_px)
                st.subheader("Order preview · pouze náhled, bez odeslání")
                st.dataframe(pd.DataFrame([{
                    "Ticker": preview.ticker, "Strana": preview.side, "Cílová USD": preview.target_usd,
                    "Delta USD": preview.delta_usd, "Cena": preview.estimated_price,
                    "Kusy (odhad)": preview.estimated_quantity, "Komise USD": preview.commission_usd,
                    "Slippage USD": preview.slippage_usd, "Další poplatky USD": preview.other_fees_usd,
                    "Status": preview.status,
                    "Zdroj ceny": rec.source, "Timestamp": rec.as_of,
                }]), use_container_width=True, hide_index=True)
                st.caption("Volitelné: zaznamenej simulovaný fill pouze do lokálního stínového portfolia. Tím se nemění broker ani se neodesílá skutečný pokyn.")
                if preview.side in {"BUY", "SELL"} and preview.estimated_quantity > 0:
                    if st.button(
                        "Zaznamenat simulovaný fill",
                        key=f"sim_fill_{model.value}_{rec.ticker}_{rec.action}",
                        type="secondary",
                    ):
                        alm_tier = rec.indicators.get("alm_tier")
                        if model == ModelName.COMBINED:
                            if alm_tier != "crash_event" or rec.ticker not in {"SPY", "QQQ"}:
                                alm_tier = None
                        elif alm_tier not in {"dd_30", "dd_50", "dd_80"} or rec.ticker not in {"SPY", "QQQ"}:
                            alm_tier = None
                        try:
                            apply_simulated_fill(
                                state,
                                ticker=preview.ticker,
                                target_usd=preview.target_usd,
                                quantity=preview.estimated_quantity,
                                price=preview.estimated_price,
                                side=preview.side,
                                commission=preview.commission_usd,
                                slippage=preview.slippage_usd,
                                other_fees=preview.other_fees_usd,
                                alm_tier=alm_tier,
                            )
                            st.success(
                                f"Simulovaný fill {preview.side} {preview.ticker} byl zaznamenán. "
                                "Nejde o brokerem potvrzený fill a žádný skutečný příkaz nebyl odeslán."
                            )
                            st.rerun()
                        except ValueError as exc:
                            st.error(f"Simulovaný fill nebyl zaznamenán: {exc}")
            elif rec.action not in {"HOLD", "HOLD_CASH"}:
                st.warning("Chybí cena přesného cílového tickeru; automatický order preview se nevytváří.")
        if rec.indicators:
            with st.expander("Indikátory a warm-up"):
                st.json(rec.indicators)
    if view == "Denní doporučení":
        rows = []
        for asset in ASSETS:
            frame = market_data.get(asset)
            if frame is not None and not frame.empty:
                rows.append({"Aktivum": asset, "Ticker dat": BASE_TICKERS[asset], "Poslední Close": float(frame.Close.iloc[-1]), "Timestamp": str(frame.index[-1]), "Bary": len(frame), "Data": source_map.get(asset, "neznámé")})
        st.subheader("Stav historických dat")
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        chosen = st.selectbox("Cenový graf", [asset for asset in ASSETS if asset in market_data])
        chart_data = market_data[chosen].tail(500)
        fig = px.line(chart_data, y="Close", title=f"{chosen} · denní Close (historická data)")
        st.plotly_chart(fig, use_container_width=True)
        st.info("Provisional pre-close vyžaduje ověřený IBKR stream se správným typem market data. Tato verze vrací z IBKR pouze HISTORICAL; nedostupné live hodnoty nevymýšlí.")

elif view == "Backtest":
    st.subheader("Event-driven backtest")
    st.caption("Signál po Close(t) → exekuce na Open(t+1). Warm-up historie zůstává dostupná před začátkem vyhodnocení.")
    if st.button("Spustit backtest", type="primary"):
        try:
            result = run_backtest(market_data, model, config, costs, start_date.isoformat(), end_date.isoformat(), gld_lev, btc_lev)
            st.session_state[f"backtest_{model.value}"] = result
            save_backtest(model.value, {"initial_equity": initial_equity, "start": str(start_date), "end": str(end_date), "factors": factors, "slippage_bps_per_side": slippage}, result.metrics, result.trades.to_json(orient="records", date_format="iso"))
        except Exception as exc:
            LOG.exception("Backtest selhal")
            st.error(f"Backtest se nepodařilo dokončit: {exc}")
    result = st.session_state.get(f"backtest_{model.value}")
    if result is not None:
        metrics = result.metrics
        cols = st.columns(5)
        cols[0].metric("Celkový výnos", f"{metrics['total_return']:.2%}" if pd.notna(metrics['total_return']) else "N/A")
        cols[1].metric("CAGR", f"{metrics['annualized_return']:.2%}" if pd.notna(metrics['annualized_return']) else "N/A")
        cols[2].metric("Max DD", f"{-metrics['max_drawdown']:.2%}" if pd.notna(metrics['max_drawdown']) else "N/A")
        cols[3].metric("Sharpe", f"{metrics['sharpe']:.2f}" if pd.notna(metrics['sharpe']) else "N/A")
        cols[4].metric("Profit factor", f"{metrics.get('profit_factor', float('nan')):.2f}" if pd.notna(metrics.get('profit_factor', float('nan'))) else "N/A")
        st.plotly_chart(px.line(result.equity, title="Equity (USD)"), use_container_width=True)
        st.plotly_chart(px.area(result.drawdown, title="Drawdown"), use_container_width=True)
        if not result.monthly_returns.empty:
            st.plotly_chart(px.bar(result.monthly_returns, x=result.monthly_returns.index, y="return", title="Měsíční výnosy"), use_container_width=True)
        st.write({"Komise USD": result.costs["commissions"], "Slippage USD": result.costs["slippage"], "Další poplatky USD": result.costs["other_fees"], "Počet pokynů": metrics["trades"], "Turnover": metrics["turnover"], "Čas v trhu": metrics["time_in_market"]})
        st.dataframe(result.trades, use_container_width=True, hide_index=True)
        st.download_button("Stáhnout trade log CSV", result.trades.to_csv(index=False).encode("utf-8"), file_name="drbl_trade_log.csv", mime="text/csv")
        if result.warnings:
            with st.expander(f"Upozornění ({len(result.warnings)})"):
                st.write(result.warnings[:100])

elif view == "Porovnání":
    st.subheader("Porovnání všech tří modelů")
    if st.button("Spustit porovnání", type="primary"):
        all_results = {}
        for candidate in ModelName:
            try:
                all_results[candidate.value] = run_backtest(market_data, candidate, config, costs, start_date.isoformat(), end_date.isoformat(), gld_lev, btc_lev)
            except Exception as exc:
                all_results[candidate.value] = f"Chyba: {exc}"
        st.session_state["comparison_results"] = all_results
    results = st.session_state.get("comparison_results", {})
    if results:
        rows = []
        for name, result in results.items():
            if isinstance(result, str):
                rows.append({"Model": name, "Stav": result})
            else:
                rows.append({"Model": name, **result.metrics, "Komise USD": result.costs["commissions"], "Slippage USD": result.costs["slippage"]})
        st.dataframe(pd.DataFrame(rows), use_container_width=True, hide_index=True)
        for name, result in results.items():
            if not isinstance(result, str):
                st.plotly_chart(px.line(result.equity, title=f"Equity · {name}"), use_container_width=True)
    st.info("Historické backtesty samy o sobě nepotvrzují budoucí výnos. Výsledek je citlivý na cenu, corporate actions, financování páky a brokerovu exekuci.")

else:
    st.subheader("Nastavení a diagnostika")
    st.json({
        "Měna": "USD", "UI timezone": "Europe/Prague", "Burzovní timezone": "America/New_York",
        "Zdroj": source_kind, "Poslední bar": str(last_timestamp), "Typ dat": "HISTORICAL",
        "Komisní profil": costs.profile, "Komise/share": commission, "Minimum/order": minimum,
        "Další fee/share": extra, "Slippage bps/strana": slippage, "Úrok hotovosti": cash_interest,
        "Faktory": factors, "Ticker mapping": BASE_TICKERS, "Pákový GLD": gld_lev, "Pákový BTC": btc_lev,
        "IBKR host": "IBKR_HOST environment/.env", "IBKR port": "IBKR_PORT environment/.env; default 4002 paper gateway",
        "IBKR clientId": "IBKR_CLIENT_ID environment/.env", "ENABLE_ORDER_SUBMISSION": "false; order sending is not implemented",
    })
    st.subheader("Uložené běhy backtestu")
    st.dataframe(pd.DataFrame(list_backtests()), use_container_width=True, hide_index=True)
    st.warning("IBKR bridge je read-only. Odeslání objednávek není implementováno. Nejdříve ověřuj strategii v historickém backtestu a následně na paper účtu.")
