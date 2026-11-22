# ADR 0001 - Camadas lógicas e tiers físicos

Status: aceito; revisado em 2026-11-16

## Decisão

Raw, Bronze e Silver são as três camadas persistentes do SUSLabX.

A árvore persistente em `/dados/abertos/suslabx` contém somente:

```text
/dados/abertos/suslabx/
├── raw/
├── bronze/
└── silver/
```

Diretórios operacionais não são camadas do lake e não devem permanecer nessa
árvore final.

## Runtime

Estado, staging, work e logs são runtime do pipeline. O destino operacional é
configurável e deve ficar fora de `/dados/abertos/suslabx`, por exemplo:

```text
/dados/suslabx_runtime/
├── state/
├── staging/
├── work/
└── logs/
```

A migração dos diretórios runtime existentes só ocorre depois que processos
ativos que usam os caminhos antigos forem encerrados. Não se move staging/state
durante uma execução.

## Semântica das camadas

### Raw

Artefato oficial original, imutável por conteúdo e identificado por SHA-256.
Republicações são preservadas conforme ADR 0003/0004.

### Bronze

Representação relacional lógica fiel à fonte.

Uma fonte física (DBC/DBF/tabela PostgreSQL de migração) permanece identificável
por proveniência. Quando uma partição lógica possui vários arquivos físicos,
ela é definida como `UNION ALL` de todas as partes.

A árvore também preserva as séries históricas separadas pelo FTP oficial. Assim,
duas pastas/eras publicadas separadamente pelo DATASUS não são fundidas em um
mesmo repositório físico Parquet. Continuidade entre séries é declarada em
Silver por view/união lógica, mantendo a série de origem.

A migração PostgreSQL -> Parquet passa por staging. A saída do staging só é
promovida a Bronze após CQ e reconstrução explícita de representações DATASUS
que tenham sido alteradas pela tipagem PostgreSQL, como zeros à esquerda.

### Silver

Modelo semântico e temporal: chaves de negócio, relacionamentos, normalização,
enriquecimentos e referências CNES/SIGTAP/território compatíveis com o período.

Silver não deve alterar o grão da Bronze sem que essa transformação seja
explicitamente declarada.

## Tiers físicos

O HDD de maior capacidade mantém as camadas persistentes. NVMe é hot tier para
PostgreSQL serving, DuckDB temp/spill, caches, índices/metadados e
materializações de alta reutilização.

A Bronze PostgreSQL é transitória e só pode ser retirada após os gates do
ADR 0005.
