# Streamlit deployment — diagnostika a opravy

## Prokázaná chyba při startu

Před opravou obsahoval `app.py` prvek `st.number_input(..., format="%.3%")`. Streamlit tento formát nepodporuje a při renderování vyhazoval `StreamlitInvalidNumberFormatError`; kvůli tomu se UI nedostalo ani k úvodnímu zobrazení. Opraveno na validní vstup procent hotovosti (0 až 10 % p.a.) převedený do interního desetinného formátu.

## Proč se start zdržoval

Původní hlavní skript spouštěl při každém prvním renderu synchronní stahování celé dostupné historie od roku 1990 pro mnoho symbolů. To zahrnovalo Yahoo Finance síťové požadavky ještě před zobrazením dashboardu. Nyní první render nevykonává žádné síťové požadavky. Data se stahují až po kliknutí na **Načíst / obnovit data**.

## Co bylo upraveno

- Yahoo Finance historie se stahuje dávkově pro více symbolů a každá žádost má timeout 12 sekund a maximálně dva pokusy.
- Když jeden symbol selže, ostatní úspěšné historie zůstanou dostupné a chyba konkrétního symbolu se zobrazí v aplikaci.
- Parquet cache se považuje za zastaralou po šesti hodinách; tlačítko obnovy vynutí nový download.
- Streamlit Cloud instaluje jen runtime závislosti. IBKR knihovna a vývojové nástroje nejsou nutné pro Yahoo režim; na VPS je IBKR dostupné přes `requirements-vps.txt` nebo extra `.[ibkr]`.
- Backtest používá seance SPY jako kalendář portfolia, ne sjednocení kalendáře s víkendovými kryptoměnovými bary.
- Combined backtest nezamění obyčejný Matrix nákup za potvrzenou krizovou ALM tranši.
- Přidané smoke testy ověřují, že počáteční vykreslení nevolá datový provider, a unit testy pokrývají batch download, timeout a vynucené obnovení cache.

## Deployment

- Main file path musí být `app.py` v kořenové složce.
- Po novém commitu Streamlit Cloud obvykle provede redeploy; pokud zůstane starý obraz aplikace, zvol v nabídce aplikace **Reboot app**.
- Při potížích s instalací závislostí zkontroluj Deploy logs. Při chybě uživatelského kódu zkontroluj Runtime logs. První otevření nyní má zobrazit dashboard bez čekání na historická data; stahování se spustí až po tlačítku.
- Žádná z těchto oprav neznamená, že byl zde proveden skutečný živý test Yahoo Finance nebo IBKR. CI testuje UI start bez sítě a syntetické výpočty.
