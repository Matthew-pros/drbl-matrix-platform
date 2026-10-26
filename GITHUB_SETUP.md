# GitHub — DRBL Matrix Platform

Hlavní repozitář projektu je **https://github.com/Matthew-pros/drbl-matrix-platform**. TEMACD modul, datové providery, Streamlit stránka, detailní zadání a skript pro metriky za 1/3/5/10/20/30 let jsou do repozitáře přidané.

## Aktualizace lokální kopie

```bash
git clone https://github.com/Matthew-pros/drbl-matrix-platform.git
cd drbl-matrix-platform
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -e ".[dev]"
# Jen na VPS, pokud použiješ IBKR Gateway:
pip install -e ".[ibkr]"
streamlit run app.py
```

Streamlit Community Cloud používá jako Main file path `app.py`. Nová sekce TEMACD je dostupná přes `pages/06_TEMACD_Rotation.py`.

## Historické metriky

```bash
python scripts/run_temacd_period_table.py --end 2026-10-24 --warmup-years 3
```

Skript vytvoří CSV/Markdown tabulku, coverage historii, equity CSV a HTML grafy vs. SPY. Skutečné výkonnostní hodnoty se musí vypočítat z dostupných historických dat; čísla z původního návrhu jsou pouze neověřená hypotéza.

## Datové zdroje

- Streamlit Cloud: Yahoo Finance přes `yfinance` (historická denní data, ne garantovaný live feed). UI se načte bez požadavku na data; stahování začne až po kliknutí na „Načíst / obnovit data“.
- Vlastní VPS: nainstaluj `pip install -r requirements-vps.txt` nebo `pip install -e ".[ibkr]"` pro IBKR Gateway historická/read-only data. V této verzi aplikace neposílá skutečné objednávky.
- Streamlit Cloud má jen runtime dependencies; vývojové balíky a IBKR knihovna se instalují odděleně, pokud jsou potřeba.

Nepřidávej `.env`, přihlašovací údaje, broker tokeny ani osobní databázi do Gitu.

## Per-asset grid search

    python scripts/run_temacd_grid_search.py --end 2026-10-26 --train-years 5 --oos-years 2
    python scripts/run_temacd_backtest.py --start 2021-10-26 --end 2026-10-26 --params-file outputs/temacd_grid/asset_params.json
    python scripts/run_temacd_period_table.py --end 2026-10-26 --params-file outputs/temacd_grid/asset_params.json

Grid search vybere parametry z in-sample období. OOS metriky se vykážou odděleně a nevstupují do výběru. V Streamlit stránce lze asset_params.json nahrát do přepínače per-asset parametrů.
