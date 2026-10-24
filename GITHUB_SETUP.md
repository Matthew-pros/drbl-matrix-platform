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
streamlit run app.py
```

Streamlit Community Cloud používá jako Main file path `app.py`. Nová sekce TEMACD je dostupná přes `pages/06_TEMACD_Rotation.py`.

## Historické metriky

```bash
python scripts/run_temacd_period_table.py --end 2026-10-24 --warmup-years 3
```

Skript vytvoří CSV/Markdown tabulku, coverage historii, equity CSV a HTML grafy vs. SPY. Skutečné výkonnostní hodnoty se musí vypočítat z dostupných historických dat; čísla z původního návrhu jsou pouze neověřená hypotéza.

## Datové zdroje

- Streamlit Cloud: Yahoo Finance přes `yfinance` (historická denní data, ne garantovaný live feed).
- Vlastní VPS: IBKR Gateway pro historická/read-only data. V této verzi aplikace neposílá skutečné objednávky.

Nepřidávej `.env`, přihlašovací údaje, broker tokeny ani osobní databázi do Gitu.
