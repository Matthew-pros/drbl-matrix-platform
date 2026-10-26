# DRBL — konsolidovaná pravidla

## 1. Oddělené modely

- **ALM:** pracuje jen se základním SPY/QQQ. Nákupy jsou stupňové na základě drawdownu od dosavadního ATH; nejde o tržní příkaz uskutečněný v čase signálu, ale o cílové doporučení. Tier 30 % → 15 % equity, 50 % → 20 %, 80 % → 50 %, se stropem celkové alokace 85 % equity a min. 15 % hotovosti. Jednotlivé neprovedené úrovně se sledují samostatně. Nepřidávej GLD/BTC do ALM.
- **DRBL Matrix:** počíná v hotovosti, měsíčně vybírá jednoho leadera a každý den vyhodnocuje jeho denní faktor. Nikdy automaticky nespouští ALM.
- **Combined:** nejdřív ALM; po prvním skutečně potvrzeném fillu v produkci (nebo fillu simulovaném backtestem) přechází do DRBL.

## 2. Měsíční rotace

Pro SPY, QQQ, GLD, IBIT a BTC-USD se skóre počítá jako 12–1 momentum dělené 60denní anualizovanou sample volatilitou:

`momentum = (Close[t-22] - Close[t-252]) / Close[t-252]`

`annualized_vol = std(daily_simple_returns[-60:], ddof=1) * sqrt(252)`

`score = momentum / annualized_vol`

Pokud je volatilita nulová nebo neúplná, skóre je nedostupné. Leader se vyhodnocuje na poslední obchodní seanci nejpozději 28. kalendářního dne měsíce. Pokud není incumbent, vybere se nejvyšší dostupné skóre. Jinak se změna dovolí pouze, pokud `challenger > incumbent + abs(incumbent) * 0.08`. Žádné skóre = žádná dokončená rotace. Když se leader nemění, negeneruje se obchod.

## 3. Denní faktory

- **Turtle Soup / Darvas (SPY/QQQ, default):** Close na/přes maximum High z předchozích 40 barů, s potvrzením, že předchozích pět barů netvořilo nová maxima; exit Close <= minimum Low z předchozích 20 barů. Reference nezahrnuje aktuální bar.
- **Keltner:** middle EMA(50), ATR(20), upper = middle + 2 × ATR. Entry Close > upper; exit Close < middle.
- **LRS (GLD/IBIT/BTC default):** OLS slope 100 denních Close; upper = SMA(100) + 2 × population std (ddof=0). Entry slope > 0 a Close > upper; exit slope < 0.
- **SMA200 / EMA200 / VWAP200:** srovnávací možnost. Entry při Close nad odpovídající linií, exit pod ní.

## 4. Páková matice

- **A / 3×:** aktivní entry a ADX(14) > 25 a RVOL = SMA(volume,20)/SMA(volume,200) > 1.4 a ATR%(20) <= předchozí 90. percentil ATR%. SPY→UPRO, QQQ→TQQQ. Páka pro GLD/BTC vyžaduje explicitně nastavený broker-validní ticker. IBIT se nikdy nepákuje. Target 85% equity, cash reserve 15%.
- **B / 1×:** entry aktivní, ale chybí některá potvrzovací podmínka nebo filtr není dostupný; použije základní instrument na target 85% equity.
- **C / cash:** exit aktivní; target 0, uzavřít spravovanou pozici a hotovost.
- Když není entry ani exit, zachovat pozici. Při změně leadera zavřít starý ticker; pokud nový leader nemá entry, zůstat v hotovosti. Více držených pozic nebo nejednoznačný instrument = REVIEW.

## 5. ALM drawdown úrovně

Drawdown `dd = (ATH - Close) / ATH`. Vyhodnocují se pouze SPY a QQQ a při dosažení nového tieru se doporučí přírůstek podle neprovedeného tieru. Vstup do Combined režimu se v ostrém provozu smí zaznamenat až po brokerově potvrzeném fillu. Backtest používá simulovaný fill na další dostupné Open.

## 6. Exekuce a náklady

- Signál po Close(t), simulovaný fill na Open(t+1).
- Komise se účtuje na každý nákup i prodej, včetně minima za pokyn.
- Slippage na nákup zvyšuje fill cenu; na prodeji ji snižuje.
- Cash interest je default 0 %.
- Yahoo Finance = HISTORICAL; žádné předstírání live dat. IBKR v této verzi = read-only historie a order preview.


## 6. TEMACD sektorová a beta rotace

TEMACD je samostatný výzkumný modul a nenahrazuje ALM ani DRBL Matrix.

- **Core universe:** SPY, QQQ, XLK, XLY, XLI, XLV, XLF, XLE, XLP, XLU.
- **Agresivní universe:** TQQQ, SOXL, SMH, BTC-USD, ETH-USD, SOL-USD.
- **Signál:** TEMA-MACD Fast 30 / Slow 80 / Signal 15; EMA1/EMA2/EMA3 10/30/120; RSI(14); ATR(20); způsobilost pouze při close nad EMA3 a kladném TEMACD histogramu.
- **Rotace:** Top N podle kombinace RSI a normalizovaného TEMACD histogramu; měsíční výchozí perioda, volitelně týdenní.
- **ATR sizing:** surová váha = cílový risk / ATR%; limit na aktivum 35 %; součet váh nejvýše 100 %; nealokovaná část zůstává v cash.
- **Náklady a exekuce:** signál na Close(t), simulace na Open(t+1), 0,05 % per side jako výchozí transakční náklad; žádné look-ahead.
- **Výstup:** equity vs. SPY Buy & Hold, metriky, obchody po nákladech, rebalanční log, ATR% a zvolené váhy.
- **Metriky na 1/3/5/10/20/30 let:** spustí scripts/run_temacd_period_table.py; nepodložené výsledky se nezobrazují jako skutečné. Dlouhá období musí vykázat dostupnost jednotlivých tickerů; aktuální ETF/crypto universe neexistoval po celých 30 let.
- **Dokumentace:** TEMACD_ROTATION_AGENT_PROMPT.md a PERFORMANCE_METRICS.md.

Neověřené modelové metriky (CAGR, Sharpe, MaxDD, Profit Factor) z uživatelského návrhu se nepoužívají jako backtestové výsledky. Ziskovost, drawdown a rizikové poměry musí být vypočteny na přesných historických datech s náklady a následně ověřeny out-of-sample.


## 7. Výchozí SPY/QQQ faktor — přesné 40/20 pravidlo

Výchozí faktor pro SPY a QQQ je `BREAKOUT_40_20`, jak vyžaduje původní zadání:

- Entry: Close(t) ≥ maximum High z předchozích 40 obchodních barů, bez aktuálního baru.
- Exit: Close(t) ≤ minimum Low z předchozích 20 obchodních barů, bez aktuálního baru.
- Signál vyhodnocený na Close se v backtestu vykoná nejdříve na Open následující seance.

`TURTLE_SOUP` zůstává samostatným volitelným faktorem s pětiseanční pauzou bez nových maxim. Nelze ho zaměňovat za výchozí pravidlo 40/20.
