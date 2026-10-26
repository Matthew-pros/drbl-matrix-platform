from __future__ import annotations

from streamlit.testing.v1 import AppTest

from src.data.yfinance_provider import YahooFinanceProvider


def test_app_startup_does_not_fetch_market_data(monkeypatch) -> None:
    def fail_if_called(*_args, **_kwargs):
        raise AssertionError("Data provider must not run until the user clicks the load button.")

    monkeypatch.setattr(YahooFinanceProvider, "get_daily_bars", fail_if_called)
    app = AppTest.from_file("app.py").run(timeout=30)

    assert len(app.exception) == 0
    assert any("Aplikace je připravena" in element.value for element in app.info)
