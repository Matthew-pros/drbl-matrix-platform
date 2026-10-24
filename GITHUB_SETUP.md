# Zveřejnění v novém GitHub repozitáři

**Tento projekt není propojený se starým `Matthew-pros/es_trading_dashboard`.** Dostupné operace připojeného GitHub konektoru neobsahují vytvoření nového repozitáře. Proto nelze poctivě uvést nový GitHub link, dokud se nový vzdálený repozitář nevytvoří.

## Varianta A — GitHub CLI

1. Na GitHubu vytvoř prázdný repozitář `drbl-matrix-platform` bez README/licence (například `https://github.com/new`).
2. V terminálu uvnitř tohoto rozbaleného adresáře spusť:

```bash
git init -b main
git add .
git commit -m "Initial DRBL Matrix Platform project"
gh auth login
gh repo create Matthew-pros/drbl-matrix-platform --public --source . --remote origin --push
```

Pokud jsi repozitář vytvořil pod jiným vlastníkem/názvem, nahraď `Matthew-pros/drbl-matrix-platform` správným `owner/name`.

## Varianta B — web GitHub

1. Vytvoř prázdný nový repozitář.
2. Ve svém počítači inicializuj Git a vytvoř commit (`git init -b main`, `git add .`, `git commit -m "Initial DRBL Matrix Platform project"`).
3. Přidej novou remote URL podle GitHub instrukcí (`git remote add origin https://github.com/OWNER/REPO.git`) a spusť `git push -u origin main`.

Nikde nevkládej token nebo heslo do zdrojových souborů. `.env`, lokální SQLite data a cache jsou ignorovány přes `.gitignore`.
