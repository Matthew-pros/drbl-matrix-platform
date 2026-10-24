# DRBL Matrix Platform — nový samostatný projekt

Česká Streamlit aplikace pro výzkum a paper-trading přípravu strategie **DRBL (Dynamic Regime-Based Leverage)**. Projekt odděluje samostatný ALM, DRBL Matrix a model Combined. V Combined je Matrix výchozí provozní strategie, nad ní běží pravidlová risk-off vrstva a krizový ALM starter je omezen na SPY/QQQ. Projekt podporuje bezplatná historická data Yahoo Finance pro Streamlit Cloud a read-only historická data přes IBKR Gateway pro vlastní VPS; skutečné objednávky neodesílá.

> **Důležité:** Starší číselné výkonnostní tabulky z diskuse nejsou v aplikaci považovány za ověřený backtest. Metriky se musí vypočítat z aktuálně stažených dat, přesně označit náklady a doložit trade logem. Historický výsledek negarantuje budoucí výnos.

## Co projekt implementuje

- Tři samostatné modely a oddělené stavy: ALM, DRBL Matrix, Combined.
- Aktiva SPY, QQQ, GLD, IBIT a BTC-USD. SPY → UPRO a QQQ → TQQQ jsou explicitní mapování; páku pro GLD/BTC je nutné zadat ručně. IBIT se nikdy nepákuje.
- Iniciační ALM pouze na SPY/QQQ, s úrovněmi propadu od maxima v dostupné historii: 30 % → 15 % equity, 50 % → 20 %, 80 % → 50 %, hotovostní rezerva minimálně 15 %. V modelu Combined navíc výchozí krizový starter 10 % equity při drawdownu alespoň 15 % a aktivním risk-off režimu. Před starterem se nejprve zavře běžná Matrix pozice; aktivní krizová držba a historicky vyplněné ALM úrovně se evidují odděleně. Provedení se zapisuje až po simulovaném fillu.
- Měsíční rotace podle 12–1 momentum / 60denní anualizované sample volatility, s 8% hysterezí a plánováním na 28. den / poslední seanci před ním. Nepřítomnost skóre neznačí úspěšnou rotaci.
- Faktor oddělený pro každé aktivum: výchozí Turtle Soup/Darvas pro SPY/QQQ a Linear Regression Slope pro GLD/IBIT/BTC-USD. Faktor lze změnit na Keltner, LRS, SMA200, EMA200 nebo VWAP200.
- Režim A: 3× nástroj pouze při aktivním entry faktoru a současně ADX(14) > 25, RVOL(20/200) > 1.4 a ATR20% pod předchozím 90. percentilem. Režim B: základní 1× podklad při entry, když nejsou všechny podmínky pro páku splněny. Režim C: uzavření spravované Matrix pozice a hotovost.
- Pravidlová risk-off vrstva sleduje VIX, trend SPY/QQQ vůči SMA200, průlom předchozích 20denních minim, rychlý růst VIX a extrémní denní rozpětí/pokles. Výchozí prahy jsou nastavitelné v sidebaru. Jde o konzervativní denní klasifikátor, nikoli implementaci proprietárního RAAM/FAA modelu ani spolehlivý intradenní detektor flash crashů.
- Backtest bez lookahead: signál po Close a fill na následujícím dostupném Open. Každý fill účtuje komisi a slippage; výstup obsahuje equity, drawdown, měsíční výnosy, trade log a souhrn nákladů.
- Yahoo Finance (`yfinance`) je vždy označeno jako HISTORICAL. IBKR provider je read-only a pouze historický, pokud není samostatně ověřen živý stream. Pro VIX používá Yahoo ticker `^VIX`; v IBKR se kvalifikuje jako index VIX/CBOE. Výchozí IB Gateway paper port je 4002. IBKR může vrátit méně historie, než je požadováno; ALM drawdown proto vychází jen z fakticky dostupných barů.
- Dashboard umožňuje volitelně zaznamenat **simulovaný fill** do lokálního stínového portfolia pro sledování dalšího stavu. Toto tlačítko nikdy neodesílá pokyn brokerovi.
- Uložení běhů do SQLite, CSV export trade logu a GitHub Actions CI.

## Nasazení na Streamlit Community Cloud

Jako výchozí soubor pro deployment zvol **`app.py`** v kořeni repozitáře. Ostatní `pages/`, `src/`, `requirements.txt` a `pyproject.toml` musí zůstat součástí stejného repozitáře.

Na Streamlit Cloud nech v levém panelu zdroj **Yahoo Finance · bezplatná historická data**. `yfinance` už je v závislostech. Jde o neplacený zdroj historických dat, nikoli garantovaný real-time feed; dostupnost i rozsah historie mohou být omezené.

## Vlastní VPS + IBKR Gateway

Na VPS spusť IB Gateway/TWS a povol socket API na privátním rozhraní. Zkopíruj `.env.example` jako `.env`, nastav `DATA_SOURCE=ibkr`, `IBKR_HOST`, `IBKR_PORT` (paper obvykle `4002`, live se liší podle instalace) a `IBKR_CLIENT_ID`. Aplikaci pak spusť z kořenového adresáře jako `streamlit run app.py`. Zdroj lze v sidebaru přepnout i ručně. Nedávej Gateway/API port přímo do internetu; zabezpeč přístup firewallem a používej VPN/SSH tunel.

IBKR provider si vyžádá až 20 let denních dat, pokud jsou dostupná, ale dostupná historie závisí na instrumentu a oprávněních. Před použitím ALM ověř, jak daleko historie konkrétního instrumentu sahá: jeho drawdown se měří jen od prvního vráceného baru. Dokumentace IBKR uvádí, že požadavek historických barů se řídí délkou `durationStr` a dostupností dat. [IBKR: Historical Bars](https://www.interactivebrokers.com/docs/tws-api/doc/md/historical-bars).

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

- IBKR živý stream a detekce LIVE/DELAYED feedu nejsou zapojeny; pouze read-only historická data a order preview. UI tlačítko zaznamenává lokální simulovaný fill, nikoli brokerovou exekuci.
- Risk-off filtr vyhodnocuje denní bary. Není to intradenní kill switch, neumí garantovat výstup před gapem a nesmí se považovat za ochranu proti ztrátě.
- Skutečné broker objednávky, IOC limit/VWAP exekuce, partial-fill lifecycle, skutečné fee reporty, margin/financing 3× pákových produktů a price/contract validation nejsou aktivovány.
- Historické řady ETF před vznikem instrumentu se nesimulují jako reálné obchodovatelné ceny. Nepoužívej historii QQQ/UPRO/TQQQ jako skutečnou obchodní historii před jejich vznikem bez explicitního indexového proxy modelu a financování páky.
- Yahoo provider pro backtest používá `auto_adjust=True` pro konzistentní upravení OHLC o splity/dividendy. Přesto je potřeba validovat cenovou bázi benchmarku, mezerová data a corporate actions; jiný provider může vracet odlišnou historii.
- Profit factor je počítán z párovaných realizovaných fillů trade logu; přechody a neuzavřené pozice mohou tuto metriku omezit. Všechny výsledky jsou modelové.
- Daňové dopady, brokerové kvalifikace kontraktů, evropské PRIIPs/UCITS přístupnosti a daňová optimalizace nejsou právní ani daňové doporučení.

## Vytvoření nového GitHub repozitáře

Tento adresář je samostatný projekt a není navázán na starý `es_trading_dashboard`. Dostupné akce propojeného GitHub konektoru umí vytvářet soubory/commity v existujícím repozitáři, ale neumí vytvořit nový repozitář. Proto se nový remote zde **nepředstírá**. Viz `GITHUB_SETUP.md` pro jednorázové vytvoření prázdného repozitáře a bezpečný push.

## TEMACD Volatility-Sized sektorová a beta rotace

Aplikace obsahuje samostatnou sekci **TEMACD Rotace** a spustitelný CLI backtest `scripts/run_temacd_backtest.py`. Modul je oddělený od ALM/DRBL/Combined a nepřebírá jejich pozice ani stav.

**Universe:** core/defenzivní ETF `SPY, QQQ, XLK, XLY, XLI, XLV, XLF, XLE, XLP, XLU`; agresivní satelity `TQQQ, SOXL, SMH, BTC-USD, ETH-USD, SOL-USD`. Chybějící nebo krátká historie aktiva se oznámí a aktivum se vynechá; benchmark SPY je povinný.

**Signály:** EMA1/EMA2/EMA3 mají výchozí období `10/30/120`; dlouhodobá způsobilost vyžaduje Close > EMA3. TEMACD = TEMA(Close, 30) − TEMA(Close, 80), signal = EMA(TEMACD, 15), histogram = TEMACD − signal. Vstupní kandidáti musí mít kladný histogram a Close nad EMA3. Pořadí je dáno kombinací normalizovaného RSI(14) a normalizovaného TEMACD histogramu. Denní výstup se vyhodnotí při bearish histogram crossu nebo Close pod EMA3. Kód a uživatelské rozhraní umožňují upravit parametry.

**ATR sizing:** ATR(20) / Close je procento volatility. Neomezená váha je `target_risk / ATR_pct`, výchozí target risk je 1 % equity na pozici; poté se uplatní strop 35 % na aktivum. Pokud součet váh přesáhne 100 %, poměrné váhy se znormalizují na 100 %; zbytek hotovosti při nižším součtu zůstává neinvestovaný. Tím se snižuje cílová váha aktiv s vyšší ATR%, ale zlepšení Sharpe/Sortino se **nepředpokládá** — musí být ověřeno backtestem.

**Rebalancování a náklady:** týdenní nebo měsíční (výchozí) rotace Top N; pokud je způsobilých méně než N aktiv, zbytek zůstává v hotovosti. Signál používá Close(t), simulovaný fill je na Open(t+1). Každý nákup/prodej je zatížen procentním nákladem; výchozích 5 bps na stranu odpovídá 0,05 % z notionalu. To je modelový náklad a nemusí odpovídat všem instrumentům, zejména kryptoměnám nebo leveraged ETF.

### Samostatný CLI backtest

```bash
python scripts/run_temacd_backtest.py --start 2018-01-01 --end 2026-10-01 --top-n 3 --rebalance monthly
```

Před spuštěním se ujisti, že máš nainstalované závislosti (`pip install -e '.[dev]'`). Skript stáhne denní historická data přes `yfinance`, přidá výchozí dvouletý warm-up před začátkem vyhodnocení a vytvoří `metrics.json`, `equity.csv`, `trades.csv`, `rebalance_log.csv`, `weights.csv` a `equity_vs_spy.html` ve složce `outputs/temacd`. Změnit lze i `--transaction-cost-bps 5`, `--target-risk-pct 1`, `--max-weight-pct 35`, `--ema-fast 10 --ema-mid 30 --ema-slow 120 --macd-fast 30 --macd-slow 80 --macd-signal 15`.

### IBKR crypto data

Pro tickerové mapování `BTC-USD`, `ETH-USD`, `SOL-USD` IBKR provider používá TWS API kontrakt `secType=CRYPTO`, defaultně burzovní cestu `PAXOS`. Cesta se může lišit dle účtu a oprávnění; lze ji přenastavit pomocí `IBKR_CRYPTO_EXCHANGE`. Dostupnost konkrétní kryptoměny a historických barů ověř podle svého IBKR účtu. Oficiální zdroje: [TWS API – Cryptocurrency Contracts](https://www.interactivebrokers.com/docs/tws-api/contracts/cryptocurrency) a [IBKR – podporované kryptoměny](https://www.interactivebrokers.com/lib/cstools/faq/content/182856890).

## TEMACD Volatility-Sized Rotation

Specifikace určená pro implementačního LLM agenta je v [`TEMACD_ROTATION_AGENT_PROMPT.md`](TEMACD_ROTATION_AGENT_PROMPT.md). Obsahuje definice TEMACD, weekly/monthly rotaci, ATR sizing s limity koncentrace, samostatné sektorové/agresivní/kombinované varianty, volitelnou risk-off vrstvu, walk-forward grid search a akceptační testy.

Pro vygenerování skutečných historických metrik za 1/3/5/10/20/30 let spusť:

```bash
python scripts/run_temacd_period_table.py --end 2026-10-24 --warmup-years 3
```

Tabulky, data coverage, metadata a equity grafy se uloží do `outputs/temacd_periods/`. Bez připojení ke zdroji historických dat nelze důvěryhodně vyplnit metriky; viz [`PERFORMANCE_METRICS.md`](PERFORMANCE_METRICS.md). Uvedené referenční hodnoty v uživatelském zadání jsou proto označené jako neověřené ilustrativní hypotézy.