# DRBL Matrix Platform — nový samostatný projekt

Česká Streamlit aplikace pro výzkum a paper-trading přípravu strategie **DRBL (Dynamic Regime-Based Leverage)**. Projekt odděluje iniciační model ALM, samostatný provozní DRBL Matrix a kombinovaný model Combined. Je určen pro historické testy a read-only připojení k IB Gateway; objednávky neodesílá.

> **Důležité:** Starší číselné výkonnostní tabulky z diskuse nejsou v aplikaci považovány za ověřený backtest. Metriky se musí vypočítat z aktuálně stažených dat, přesně označit náklady a doložit trade logem. Historický výsledek negarantuje budoucí výnos.

## Co projekt implementuje

- Tři samostatné modely a oddělené stavy: ALM, DRBL Matrix, Combined.
- Aktiva SPY, QQQ, GLD, IBIT a BTC-USD. SPY → UPRO a QQQ → TQQQ jsou explicitní mapování; páku pro GLD/BTC je nutné zadat ručně. IBIT se nikdy nepákuje.
- Iniciační ALM pouze na SPY/QQQ, s úrovněmi propadu od dostupného historického maxima: 30 % → 15 % equity, 50 % → 20 %, 80 % → 50 %, permanentní hotovostní rezerva 15 %. Jednotlivé úrovně jsou vedeny odděleně; Combined přechází do provozní fáze po simulovaném (backtest) či brokerem potvrzeném (live návrh) prvním fillu.
- Měsíční rotace podle 12–1 momentum / 60denní anualizované sample volatility, s 8% hysterezí a plánováním na 28. den / poslední seanci před ním. Nepřítomnost skóre neznačí úspěšnou rotaci.
- Faktor oddělený pro každé aktivum: výchozí Turtle Soup/Darvas pro SPY/QQQ a Linear Regression Slope pro GLD/IBIT/BTC-USD. Faktor lze změnit na Keltner, LRS, SMA200, EMA200 nebo VWAP200.
- Režim A: 3× nástroj pouze při aktivním entry faktoru a současně ADX(14) > 25, RVOL(20/200) > 1.4 a ATR20% pod předchozím 90. percentilem. Režim B: základní 1× podklad při entry, když nejsou všechny podmínky pro páku splněny. Režim C: uzavření spravované pozice a hotovost.
- Backtest bez lookahead: signál po Close a fill na následujícím dostupném Open. Každý fill účtuje komisi a slippage; výstup obsahuje equity, drawdown, měsíční výnosy, trade log a souhrn nákladů.
- Yahoo Finance je vždy označeno jako HISTORICAL. IBKR provider je read-only a pouze historický, pokud není samostatně ověřen živý stream. Výchozí IB Gateway paper port je 4002.
- Uložení běhů do SQLite, CSV export trade logu a GitHub Actions CI.

## Instalace a spuštění

Python 3.11+:

```bash
python -m venv .venv
# Windows PowerShell: .venv\Scripts\Activate.ps1
# macOS/Linux:
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -e '.[dev]'
streamlit run app.py
```

## IB Gateway paper / read-only

1. Spusť IB Gateway v **Paper Trading** režimu a povol socket API pouze pro lokální klienty.
2. Zkopíruj `.env.example` na `.env` a nastav vlastní `IBKR_HOST`, `IBKR_PORT` (paper Gateway obvykle `4002`), `IBKR_CLIENT_ID`.
3. Tento projekt historická data z IBKR označuje jako `HISTORICAL`. Živý stream / typ feedu není jen z úspěšného history requestu odvozován.
4. `ENABLE_ORDER_SUBMISSION=false` je výchozí stav. Adaptér vytváří pouze order preview; v této verzi je zadávání objednávek záměrně neimplementováno.

## Výchozí pravidla faktorů

- **Turtle Soup / Darvas (SPY/QQQ):** breakout 40denního High s 5denní pauzou bez nových maxim; exit při Close pod předchozím 20denním Low. Reference vylučuje aktuální bar.
- **Keltner:** EMA(50) jako střed, horní pásmo = EMA50 + 2 × ATR(20); entry nad horním pásmem, exit pod EMA50.
- **Linear Regression Slope:** 100denní OLS slope nad Close; entry při slope > 0 a Close > SMA100 + 2 × population std; exit při slope < 0.
- **SMA200 / EMA200 / VWAP200:** samostatné srovnávací baseline faktory; vstup nad linií a exit pod ní.
- **Páka:** 3× pouze po potvrzení ADX, RVOL a ATR% filtru. ATR percentil je počítán pouze z předchozích barů, ne z aktuálního baru.
- **Rotace:** pouze při plánované události. Nový leader musí překonat incumbent score o více než 8 % podle deterministické definice v kódu. Když se leader změní, stará pozice se uzavře nejdříve na příštím Open; pokud nový faktor nemá entry, portfolio zůstane v cash.

Přesné vzorce a limity jsou v `STRATEGY_SPEC.md`.

## Náklady

Výchozí odhad: komise $0.0035 za akcii, minimum $0.35 za pokyn, slippage 10 bps na jednu stranu, cash interest 0 %. Tyto sazby jsou editovatelné modelové předpoklady, ne skutečný broker report. V UI lze testovat 0/5/10/25/50 bps. Hrubý výnos, komise, slippage a další poplatky jsou v reportu odděleny.

## Testy a kvalita

```bash
pytest -q
ruff check src app.py tests
mypy src
```

Burzovní kalendář pro USA používá `pandas_market_calendars`. Pokud tato knihovna není v lokálním prostředí instalována, testy kalendáře jsou přeskočeny a rotační datum v test-only režimu používá zjednodušený fallback všedního dne. Produkční běh má mít všechny zamčené závislosti nainstalované.

## Známá omezení před produkcí

- IBKR živý stream a detekce LIVE/DELAYED feedu nejsou zapojeny; pouze read-only historická data a order preview.
- Skutečné broker objednávky, IOC limit/VWAP exekuce, partial-fill lifecycle, skutečné fee reporty, margin/financing 3× pákových produktů a price/contract validation nejsou aktivovány.
- Historické řady ETF před vznikem instrumentu se nesimulují jako reálné obchodovatelné ceny. Nepoužívej historii QQQ/UPRO/TQQQ jako skutečnou obchodní historii před jejich vznikem bez explicitního indexového proxy modelu a financování páky.
- Data z Yahoo mají neupravené OHLC a oddělené Adjusted Close/Dividends/Splits; backtest musí výslovně hlídat, zda benchmark zahrnuje dividendy.
- Profit factor je počítán z párovaných realizovaných fillů trade logu; přechody a neuzavřené pozice mohou tuto metriku omezit. Všechny výsledky jsou modelové.
- Daňové dopady, brokerové kvalifikace kontraktů, evropské PRIIPs/UCITS přístupnosti a daňová optimalizace nejsou právní ani daňové doporučení.

## Vytvoření nového GitHub repozitáře

Tento adresář je samostatný projekt a není navázán na starý `es_trading_dashboard`. Dostupné akce propojeného GitHub konektoru umí vytvářet soubory/commity v existujícím repozitáři, ale neumí vytvořit nový repozitář. Proto se nový remote zde **nepředstírá**. Viz `GITHUB_SETUP.md` pro jednorázové vytvoření prázdného repozitáře a bezpečný push.


## TEMACD Volatility-Sized Rotace (nové)

Samostatná stránka **TEMACD Rotace** je dostupná v pages/06_TEMACD_Rotation.py. Strategie nabízí Sector Rotation, Aggressive Rotation a Combined Rotation; používá TEMACD, RSI, EMA3 filtr, ATR20 sizing, Top N, týdenní/měsíční rebalancování, náklady na každou stranu a benchmark SPY Buy & Hold. Signál se počítá na close dne t a simulovaná exekuce následuje na open dne t+1.

- Podrobné zadání pro dalšího kódovacího agenta: [TEMACD_ROTATION_AGENT_PROMPT.md](TEMACD_ROTATION_AGENT_PROMPT.md)
- Metodika a stav historických metrik: [PERFORMANCE_METRICS.md](PERFORMANCE_METRICS.md)
- Výpočet metrik za horizonty 1/3/5/10/20/30 let: python scripts/run_temacd_period_table.py --end 2026-10-24
- Jednorázový backtest a equity graf: python scripts/run_temacd_backtest.py --help

Metriky se nesmějí považovat za ověřené, dokud skript nespustíš nad historickými daty. Čísla CAGR/Sharpe/MaxDD/Profit Factor uvedená ve specifikaci uživatele jsou pouze modelové hypotézy. Yahoo Finance poskytuje historická data, nikoli garantovaný live feed; IBKR Gateway provider je v tomto projektu určen pro historická/read-only data a aplikace neodesílá živé objednávky.
