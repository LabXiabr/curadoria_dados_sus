# ADR 0001 - Camadas lógicas e tiers físicos

## Decisão

Raw, Bronze e Silver são camadas lógicas.

O armazenamento canônico volumoso fica em:

`/dados/abertos/suslake` na bureta, sobre o HDD de maior capacidade.

O NVMe não é associado obrigatoriamente à Silver. Ele é um hot tier para:

- PostgreSQL serving;
- DuckDB temp/spill;
- caches;
- índices/metadados;
- materializações de alta reutilização.

A Bronze PostgreSQL é transitória e deve ser removida somente após Parquet + QC.
