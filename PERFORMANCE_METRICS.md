# Performance Quant Metrics — TEMACD

## Stav skutečně vypočítaných výsledků

**Historické výsledky nejsou doplněné odhadem.** V tomto vývojovém prostředí nebylo možné stáhnout úplné denní historie přes Yahoo Finance, a proto zde nejsou tvrzeny skutečné hodnoty Net Profit, MaxDD, CAGR, Sharpe, Sortino ani Profit Factor. Po spuštění skriptu s přístupem k Yahoo Finance se tabulka vygeneruje z reálných stažených dat.

Spuštění z kořene projektu:

```bash
pip install -e '.[dev]'
python scripts/run_temacd_period_table.py --end 2026-10-24 --initial-equity 100000 --top-n 3 --rebalance monthly
```

Výstupy se uloží do `outputs/temacd_periods/`: `period_metrics.csv`, `period_metrics.md`, `data_coverage.csv`, denní equity, trades a rebalanční logy. Řádky, u kterých není k dispozici celá základní SPY historie, budou označeny jako N/A. Chybějící jednotlivá aktiva se explicitně uvedou ve sloupci coverage; nebudou nahrazena vymyšlenými daty.

## Požadovaná tabulka po skutečném spuštění

Všechny výsledky níže jsou záměrně označeny jako **N/A — neprovedeno v tomto prostředí**, nikoliv 0.00 %. Spusťte runner výše, aby byly nahrazeny vypočítanými historickými hodnotami.

| Portfolio | Horizont | Net Profit (USD / %) | MaxDD | CAGR | Sharpe | Sortino | Profit Factor |
|---|---:|---:|---:|---:|---:|---:|---:|
| Sector Rotation | 1 rok | N/A | N/A | N/A | N/A | N/A | N/A |
| Sector Rotation | 3 roky | N/A | N/A | N/A | N/A | N/A | N/A |
| Sector Rotation | 5 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Sector Rotation | 10 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Sector Rotation | 20 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Sector Rotation | 30 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Aggressive Rotation | 1 rok | N/A | N/A | N/A | N/A | N/A | N/A |
| Aggressive Rotation | 3 roky | N/A | N/A | N/A | N/A | N/A | N/A |
| Aggressive Rotation | 5 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Aggressive Rotation | 10 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Aggressive Rotation | 20 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Aggressive Rotation | 30 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Combined Rotation | 1 rok | N/A | N/A | N/A | N/A | N/A | N/A |
| Combined Rotation | 3 roky | N/A | N/A | N/A | N/A | N/A | N/A |
| Combined Rotation | 5 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Combined Rotation | 10 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Combined Rotation | 20 let | N/A | N/A | N/A | N/A | N/A | N/A |
| Combined Rotation | 30 let | N/A | N/A | N/A | N/A | N/A | N/A |
| SPY Buy & Hold benchmark | 1 rok | N/A | N/A | N/A | N/A | N/A | N/A |
| SPY Buy & Hold benchmark | 3 roky | N/A | N/A | N/A | N/A | N/A | N/A |
| SPY Buy & Hold benchmark | 5 let | N/A | N/A | N/A | N/A | N/A | N/A |
| SPY Buy & Hold benchmark | 10 let | N/A | N/A | N/A | N/A | N/A | N/A |
| SPY Buy & Hold benchmark | 20 let | N/A | N/A | N/A | N/A | N/A | N/A |
| SPY Buy & Hold benchmark | 30 let | N/A | N/A | N/A | N/A | N/A | N/A |

## Jak jsou metriky definovány

- **Net Profit USD:** konečná equity minus počáteční equity.
- **Net Profit %:** kumulativní výnos po simulovaných transakčních nákladech.
- **MaxDD:** největší pokles equity od předchozího maxima; vykazuje se jako záporné procento.
- **CAGR:** anualizovaný složený výnos z přesného kalendářního rozpětí použité equity křivky.
- **Sharpe:** anualizovaný průměr denních výnosů dělený jejich směrodatnou odchylkou, násobený √252; bez odečtení risk-free sazby.
- **Sortino:** průměrný denní výnos dělený downside deviation z negativních denních výnosů, anualizováno √252.
- **Profit Factor:** realizovaný hrubý zisk / realizovaná hrubá ztráta, FIFO párování obchodů po započtení komisí u vstupu i výstupu. Nerealizované P&L otevřených pozic do PF nevstupuje.
- **Náklady:** výchozí 5 bps (0,05 %) z notionalu na každou stranu obchodu; lze nastavit CLI parametrem `--transaction-cost-bps`.

## Uživatelovy modelové výsledky — pouze neověřená hypotéza

V zadání byly uvedeny modelové (nikoli zde ověřené) hodnoty:

| Portfolio | CAGR (model) | Sharpe (model) | MaxDD (model) | Calmar (model) | Profit Factor (model) | Win Rate (model) |
|---|---:|---:|---:|---:|---:|---:|
| Sektorová rotace ETF | 14,80 % | 1,52 | −9,50 % | 1,55 | 3,45 | 62,0 % |
| Agresivní rotace Tech/Crypto/Leverage | 28,40 % | 1,18 | −18,20 % | 1,56 | 4,10 | 55,5 % |
| SPY Buy & Hold | 10,20 % | 0,72–0,85 | −23 % až −33 % | 0,35–0,45 | N/A | N/A |

**Tyto hodnoty nejsou výsledkem kódu ani slibem výkonnosti.** Nejsou k nim dodána surová data, konkrétní okno, přesné transakce, poplatky, časování signálů ani out-of-sample výstup. Používejte je pouze jako srovnávací hypotézu. Grid search musí být oddělen od testovacího období a musí zaznamenat výsledky walk-forward/OOS, jinak hrozí přeoptimalizování.

## Dostupnost historie

Nedostatek historie je pro dlouhé horizonty věcný problém. TQQQ a SOXL nebyly obchodovány před rokem 2010, QQQ nebyl dostupný před rokem 1999; BTC/ETH/SOL mají ještě kratší historie. Proto 20- a 30leté výsledky sektorových/agresivních portfolií nemohou být úplně investovatelnou simulací dnešního celého universe. Skript zaznamená skutečné pokrytí jednotlivých aktiv; analýza 30 let znamená test na dostupném historickém universe, nikoli předstírané použití dnešních ETF před jejich vznikem.

## Upozornění k interpretaci

ATR sizing nastavuje váhy podle ATR % a stropu váhy aktiva; automaticky nezaručuje vyšší Sharpe/Sortino nebo nižší MaxDD. Leveraged ETFs mají path dependency a mohou mít dlouhodobé ztráty; crypto obchoduje i o víkendech, kdežto benchmark SPY má burzovní kalendář. Výsledek závisí na synchronizaci barů, chybějících datech, adjustaci corporate actions, nákladech, slippage a proveditelné ceně exekuce.
