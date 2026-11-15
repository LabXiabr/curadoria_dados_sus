# ETL DBC SIA/SIH

Fonte do novo ETL: `raw/dissemin/publicos/<caminho FTP>`.

Bronze:

```text
bronze/<sia|sih>/<subsistema>/uf=<UF>/competencia=<AAAAMM>/sha256=<SHA>/part-000.parquet
```

Todas as colunas DBC são lidas como texto. Proveniência e número físico da linha são preservados.

Silver:

```text
silver/<sia|sih>/fact_<sistema>_<subsistema>/uf=<UF>/competencia=<AAAAMM>/part-000.parquet
```

A Silver mantém a mesma contagem da Bronze e projeta campos canônicos de `catalog/datasus_canonical_fields.tsv` e `catalog/fields.tsv`.

CNES, SIGTAP e território não são denormalizados no fato; serão ligados por views temporais.

Pilotos:

```bash
./ops/dissemin-system-complete.sh --system SIA --subsystem PA --uf AC --from 202601 --to 202601 --max-files 1
./ops/dissemin-system-complete.sh --system SIH --subsystem RD --uf AC --from 202601 --to 202601 --max-files 1
```
