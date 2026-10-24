# Zadání pro Python LLM agenta: TEMACD Volatility-Sized sektorová a beta rotace

## Účel a zásady

Implementuj v projektu `drbl-matrix-platform` samostatnou, modulární a objektově orientovanou výzkumnou strategii **TEMACD Volatility-Sized Sector & Beta Rotation**. Nesmí nahradit ani tiše změnit původní strategie ALM, DRBL Matrix a Combined. Strategie smí být v první fázi pouze pro historický backtest, analýzu a paper-trading náhledy; automatické odesílání živých objednávek není součástí zadání.

Výsledky musí být vytvořené z historických denních OHLCV dat. Nikdy nevkládej do výstupů vymyšlené či projektované výkonnostní metriky. Každý výsledek musí uvádět období, zdroj dat, datum stažení, konfiguraci, transakční náklady, dostupnost jednotlivých aktiv a upozornění na omezení dat.

## 1. Investiční univerzum

### Core / sektorové ETF

`SPY`, `QQQ`, `XLK`, `XLY`, `XLI`, `XLV`, `XLF`, `XLE`, `XLP`, `XLU`.

### Agresivní / satellite aktiva

`TQQQ`, `SOXL`, `SMH`, `BTC-USD`, `ETH-USD`, `SOL-USD`.

Podporuj tři samostatně reportované varianty:

1. **Sector Rotation** — výběr pouze z Core universe.
2. **Aggressive Rotation** — výběr pouze z Aggressive universe.
3. **Combined Rotation** — výběr ze sjednoceného univerza.

SPY Buy & Hold je benchmark, nikoli automaticky povolený kandidát ve variantě Aggressive Rotation. Pokud některé aktivum v části historie ještě neexistovalo nebo nemá dostatek validních dat, nesmí se synteticky doplnit nulovou cenou ani zpětně předstírat jeho dostupnost.

Upozorni na **survivorship bias**: seznam tvoří dnešní existující symboly, ne úplný historický vesmír včetně zaniklých ETF. Pro závěry o robustnosti nabídni alternativní benchmarky/proxy, ale vždy jasně označ, kdy jde o proxy a ne skutečnou historii fondu.

## 2. Denní data a exekuce

- Primární zdroj pro nasazení na Streamlit Community Cloud: Yahoo Finance přes `yfinance` (historická denní data; bez garance živého feedu).
- Produkční alternativou na VPS může být IBKR Gateway API pro historické/aktuální tržní údaje. Backtest musí zachovat stejný datový kontrakt bez ohledu na provider.
- Používej souvislé OHLCV řady, kontroluj duplicitní index, pořadí dat, neplatné nebo nekladné ceny, prázdné odpovědi, split/adjustment události a chybějící data.
- Pro total-return backtest musí být zacházení s dividendami a splity konzistentní mezi aktivy a benchmarkem. Nepoužívej `Adj Close` jako `Close` a současně nezměněné `Open/High/Low`; buď stáhni a používej konzistentně dividendově/splitově upravené OHLC, nebo explicitně modeluj dividendy a corporate actions. Uváděj, jaká varianta byla použita.
- Všechny indikátory pro signál v den `t` počítej výhradně z dat dostupných nejpozději při Close dne `t`.
- Signál vypočtený na Close `t` se v denním backtestu exekuuje nejdříve na Open `t+1`. Žádná exekuce za stejnou Close cenu, ze které vznikl signál.
- Pokud pro plánovaný ticker na exekučním Open chybí cena, nesimuluj fill. Zaloguj odmítnutý/skipped příkaz a zachovej konzervativní ocenění portfolia.
- Poplatky ve výchozím nastavení `0,05 %` z notionalu **na každou stranu** (buy i sell). Slippage nastav jako samostatný parametr (výchozí 0 bps pro základní reprodukovatelný scénář, následně proveď citlivostní analýzu např. 2, 5 a 10 bps na každou stranu). Nezaměňuj komisi a slippage.
- V základní verzi drž volnou hotovost s výnosem 0 %, pokud není výslovně nastavena a historicky doložena jiná cash-yield série. Nesmíš automaticky vložit výnos Treasury do období, kde pro něj nejsou data.

## 3. Indikátory TEMACD

Všechny indikátory se počítají pro každé aktivum samostatně.

### EMA trendový filtr

Výchozí parametry: `EMA1=10`, `EMA2=30`, `EMA3=120`. Dlouhodobý filtr dovolí otevřít long pozici jen tehdy, když `Close > EMA3`. Pokud EMA3 ještě není validní, aktivum je nezpůsobilé.

### Triple EMA MACD

Definuj jednoznačně:

- `TEMA(x, n) = 3*EMA(x,n) - 3*EMA(EMA(x,n),n) + EMA(EMA(EMA(x,n),n),n)`.
- `TEMACD = TEMA(Close, fast) - TEMA(Close, slow)`.
- `Signal = EMA(TEMACD, signal_period)` (signal MA může být parametrizovatelná; výchozí je EMA).
- `Histogram = TEMACD - Signal`.

Výchozí parametry `fast=30`, `slow=80`, `signal=15`. Fast musí být menší než Slow. EMA fast/mid/slow a TEMACD parametry musí být konfigurovatelné per asset; počáteční výchozí parametry jsou společné, dokud není k dispozici reprodukovatelný grid search.

Rozlišuj **býčí stav** (`Histogram > 0`) a **nový býčí cross** (histogram přešel z `<=0` na `>0`). Pro rotaci na měsíčním/weekly okně nepoužívej nutně jen cross přesně v den rebalancování, protože by bylo příliš snadné vyřadit trendové aktivum, které crosslo o několik dní dřív. Použij konfigurovatelné `cross_lookback` (výchozí 21 obchodních seancí pro měsíční a 5 pro týdenní rotaci), pokud je v tomto okně potvrzen býčí cross a histogram zůstává kladný. Porovnej tuto variantu také s jednodušším filtrem `Histogram > 0`.

### RSI

Výchozí `RSI(14)`. Ošetři nulovou ztrátu a nulový zisk tak, aby RSI neobsahoval nekonečna nebo tiché chyby.

### ATR

Výchozí `ATR(20)` s Wilderovým vyhlazením. Použij True Range:

`TR_t = max(High_t - Low_t, abs(High_t - Close_(t-1)), abs(Low_t - Close_(t-1)))`

`ATR_pct_t = ATR_t / Close_t`.

ATR a cena musí být ze stejné cenové báze. ATR není přímo zárukou maximální ztráty ani stop-loss; je to proxy pro rozsah pohybu.

## 4. Momentum skóre a výběr Top N

Výchozí rebalancování je měsíční, alternativně týdenní. Rozhodnutí vzniká na poslední obchodní seanci příslušného období a fill se provádí na Open následující seance.

Aktivum se kvalifikuje, pokud současně:

1. Má dostatek validních dat pro všechny indikátory.
2. `Close > EMA3`.
3. Histogram TEMACD je kladný a splňuje nastavenou podmínku čerstvého býčího crossu / testovaného bullish-state modelu.
4. ATR% je validní, konečné a větší než nula.

Výchozí skóre musí být srovnatelné napříč aktivy. Použij konfigurovatelné váhy, výchozí 50/50:

- komponenta RSI: `RSI/100`.
- komponenta histogramu normalizovaná cenou: `tanh((Histogram/Close)*100)` převést z rozsahu `[-1,1]` do `[0,1]`.
- `score = w_RSI*RSI_component + w_Hist*Histogram_component`, `w_RSI+w_Hist=1`.

Zaznamenávej skóre komponent, pořadí, důvod způsobilosti i důvod odmítnutí každého symbolu. Vyber Top N dle skóre (výchozí `Top 3`). Pokud podmínky splňují méně než N aktiv, zbylá váha zůstane v cash; nedoplňuj ji automaticky slabšími kandidáty.

## 5. ATR volatility sizing a portfolio limity

Výchozí parametry:

- ATR period: 20.
- Risk unit na pozici: `1,0 %` equity.
- Max. cílová váha jednoho aktiva: `35 %` equity.
- Max. gross exposure: `100 %` equity, bez páky účtu.
- Short pozice nejsou povolené.

Výpočet pro každého vybraného kandidáta:

`raw_weight_i = target_risk / ATR_pct_i`

`capped_weight_i = min(raw_weight_i, max_asset_weight)`

Pokud součet vah přesahuje 100 %, proporcionálně zmenši všechny cílové váhy na maximální gross exposure 100 %. Pokud součet nedosahuje 100 %, zbytek je hotovost. Každou cílovou váhu, ATR%, výpočet raw weight, cap a případný renormalizační faktor zapisuj do `weights.csv`.

Tento vzorec je aproximace volatility targeting, ne exaktní risk parity: ATR je rozsah OHLC, není volatilita výnosů ani ztrátová hranice. V reportu porovnej také variantu sizingu dle 20denní annualizované volatility denních výnosů. Neprováděj normalizaci způsobem, který po přepočtu poruší 35% limit.

Dodatečné pojistky:

- Max. váha jednoho symbolu 35 %.
- Max. společná váha pákových ETF (`TQQQ`, `SOXL`) — výchozí 20 % kombinovaně; tento limit musí být konfigurovatelný a samostatně reportovaný.
- Max. společná váha krypto (`BTC-USD`, `ETH-USD`, `SOL-USD`) — výchozí 25 % kombinovaně.
- Nealokuj více než 100 % equity, nedovol zápornou hotovost a nikdy nevyužívej implicitní margin.
- Tyto skupinové stropy aplikuje před finálním gross-capem; zaznamenávej aktivní limity.
- Přidej scénář bez těchto dodatečných group capů jako ablation test, aby bylo vidět, zda skutečně přispívají k výsledku.

## 6. Risk-on / transition / risk-off režim

Přidej volitelnou tržní režimovou vrstvu jako nezávislý risk overlay, nikoli jako tvrzení, že RAAM/FAA jsou implementované, pokud nejsou definovány jejich přesné vzorce.

Výchozí transparentní klasifikátor:

- `RISK_ON`: SPY Close nad SMA200, SMA200 trend se nezhoršuje a VIX pod konfigurovatelnou hranicí.
- `TRANSITION`: SPY pod SMA200, VIX rychle roste, nebo se zhoršuje šířka/počet kvalifikovaných aktiv.
- `RISK_OFF`: SPY pod SMA200 a potvrzený stresový signál, např. VIX >= 30 nebo významný nárůst VIX; hranice je nastavitelná a musí se ověřit out-of-sample.

Když VIX data nejsou k dispozici, režim musí umět přepnout do degradovaného režimu jen podle SPY trendu a tento fakt zapsat jako varování; nesmí potichu předstírat, že VIX byl použit.

Požadované výchozí chování:

- RISK_ON: běžná rotace s ATR sizingem, stále v rámci všech capů.
- TRANSITION: neotevírat novou expozici v pákových ETF, snížit `target_risk` (výchozí 50 % normálu) a běžné pozice řídit stop pravidly.
- RISK_OFF: neotvírat nové pákové pozice; cílově přesunout běžné portfolio do cash dle příštího povoleného exekučního Open. Parametr `exit_on_risk_off` musí být explicitně zapnutelný a jeho efekt reportován.
- Po návratu z RISK_OFF vyžaduj stabilizaci (např. 2 po sobě jdoucí zavírací ceny SPY nad SMA200) nebo býčí TEMACD potvrzení; zabraň každodennímu přepínání režimů pomocí hysteresis/cooldown.

Srovnej risk overlay ON vs OFF. Pravidla nesmí používat budoucí data ani intradenní informace nedostupné v den rozhodnutí.

## 7. Exit logika

Na denní bázi po Close kontroluj:

- nový bearish TEMACD cross (histogram z `>0` na `<=0`), nebo
- Close pod EMA3, nebo
- aktivovaný risk-off overlay.

Signál z Close se vykoná nejdříve na následujícím Open. Omez falešné signály volitelným potvrzením, ale veškeré varianty musí být parametrizované a porovnávané na holdout datech. Neoznačuj hodnoty `30` a `80` za univerzální crossover hranici; jde o výchozí periody TEMACD Fast/Slow, pokud není specifikován jiný normalizovaný signál.

## 8. Grid search a výběr robustních parametrů

Nepoužívej optimalizaci na celém backtestu a následné vykázání téhož období jako nezávislého výsledku.

- Definuj rozumnou konečnou mřížku pro EMA Fast/Mid/Slow, TEMACD Fast/Slow/Signal, Top N, rebalancování, `target_risk`, group caps, cross lookback a risk overlay.
- Zajisti logicky validní parametry (`fast < slow`, EMA periody > 1, váhy v mezích).
- Použij walk-forward: tréninkové období, validační období, následné out-of-sample okno; posunuj okna chronologicky.
- Penalizuj vysokou citlivost parametrů, vysokou koncentraci a velké transakční náklady. Nevybírej jen nejvyšší CAGR.
- Robustní kandidáty vyhodnoť podle mediánu out-of-sample Sharpe/Sortino, MaxDD, Calmar, churnu, turnoveru a stability přes několik oken/režimů.
- Zaveď korektní benchmark a baseline varianty: SPY Buy & Hold, Core equal-weight / momentum bez ATR, TEMACD bez risk overlay a TEMACD s ATR sizingem.
- Zveřejni kompletní grid výsledky nebo alespoň CSV všech kandidátů; uveď, zda metriky jsou in-sample, validation nebo out-of-sample.

## 9. Výkonnostní metriky

Pro každý horizont `1, 3, 5, 10, 20, 30` kalendářních let a pro varianty Sector Rotation, Aggressive Rotation, Combined Rotation a SPY Buy & Hold vypočítej:

- Starting equity a ending equity.
- Net Profit v USD a Net Profit % po komisích a modelovaném slippage.
- CAGR z přesného kalendářního času mezi první a poslední equity observation.
- Max Drawdown jako zápornou procentní hodnotu (peak-to-trough).
- Sharpe Ratio, annualizováno `sqrt(252)`, s jasně uvedeným risk-free předpokladem (výchozí 0 %).
- Sortino Ratio s target daily return 0 % a výslovně uvedenou konvencí downside deviation.
- Profit Factor = součet čistých realizovaných zisků / absolutní hodnota čistých realizovaných ztrát, podle FIFO párování nákupů/prodejů včetně komisí. Pokud nejsou uzavřené ziskové/ztrátové cykly, vrať `N/A`, ne smyšlené číslo.
- Win rate a počet uzavřených FIFO matched slices/round-trips jako doplňkové metriky.
- Turnover, počet buy/sell exekucí, celkové komise, celkové slippage a dobu strávenou v cash.
- Volatilitu equity a Calmar Ratio jako doplňkové metriky.

Net Profit musí vycházet ze skutečného počátečního kapitálu a finální equity; CAGR a benchmark mají používat totožné časové okno. Výnosy po komisích nesmí odečítat komisí podruhé. Benchmark SPY Buy & Hold musí pracovat se stejnou cenovou bází a obdobnými transakčními náklady při vstupu.

## 10. Požadované výstupy

Skript `scripts/run_temacd_period_table.py` musí:

1. Stáhnout celou historii potřebnou pro 30letý horizont + warm-up (default 3 roky) z Yahoo Finance; uložit cache a audit metadat.
2. Spustit všechna tři portfolia a SPY benchmark pro všech šest horizontů.
3. Vytvořit konzistentní výsledkovou tabulku `outputs/temacd/period_metrics.csv` a `period_metrics.md`.
4. Vytvořit `equity_vs_spy_<variant>_<years>y.html` a surová equity CSV.
5. Uložit trade FIFO detail, `trades.csv`, `rebalance_log.csv`, `weights.csv`, `data_coverage.csv` a kompletní konfiguraci do JSON.
6. Pro každé rebalancování zaznamenat ATR%, raw/capped/final weight, RSI, TEMACD histogram, trend stav, market regime, vybraný rank a důvod, proč ostatní kandidáti nebyli vybráni.
7. Vypočítat ablation scénáře: bez ATR (equal-weight), bez risk overlay, s/bez group capů, weekly vs monthly a alternativní model slippage.
8. Nezobrazovat projektované hodnoty jako skutečně naměřený backtest. Pokud horizont nebo data nejsou k dispozici, výsledek označit `N/A` a uvést důvod.

## 11. Testy a akceptační kritéria

Doplň testy na:

- ATR výpočet a vyšší ATR% => nižší raw váha.
- 35% cap, skupinové limity a max 100% gross exposure.
- žádné look-ahead (změna budoucích dat nesmí změnit indikátory a váhy minulosti).
- signál z Close `t` se exekuuje nejdříve na Open `t+1`.
- bez ceny na exekučním Open nedojde k fillu.
- komise i slippage se počítají na každou stranu.
- správné FIFO párování realizovaného P&L a PF.
- jednotlivé horizonty mají přesné kalendářní cut-offy a stejné počáteční equity.
- chybějící historická aktiva nejsou doplňována falešnými daty.
- žádná záporná hotovost, short pozice nebo expozice nad limitem.

Na konci spusť testy, type checks a lint, oprav všechny chyby. Dokumentuj neověřené externí integrace (Yahoo Finance/IBKR) odděleně od unit testů.

## 12. Důležitá interpretace

Uživatelský brief obsahuje ilustrativní/modelové hodnoty typu Sector CAGR 14,8 %, Aggressive CAGR 28,4 %, Sector MaxDD −9,5 % a Aggressive MaxDD −18,2 %. Tyto hodnoty **nejsou potvrzeným výsledkem**, pokud nejsou spojeny s konkrétním obdobím, surovými daty, konfigurací, náklady a výstupy backtestu. V reportu je proto můžeš uvést pouze jako `user-supplied illustrative figures — unverified`, nikoliv jako naměřenou historickou výkonnost.