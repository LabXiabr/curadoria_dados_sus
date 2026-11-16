# SUS Lake / SUS Semântica — índice mestre

Status: vigente  
Data de consolidação: 2026-11-16

## Fonte de verdade

Este repositório é a fonte de verdade para:

- arquitetura do lake;
- contratos de schemas, campos, chaves e relacionamentos;
- semântica por sistema;
- regras de qualidade;
- ETLs e scripts de promoção;
- política de publicação;
- identidade longitudinal ERLEN_PID;
- projeções Gold/OMOP;
- decisões arquiteturais e pendências.

Os chats são histórico e rastreabilidade, não autoridade normativa.

O estado operacional de uma execução não fica congelado no Git:

- execução/checkpoints/markers: `suslake/state`;
- staging temporário: runtime do lake;
- dados persistentes: `suslake/raw`, `suslake/bronze`, `suslake/silver`.

## Estrutura conceitual

```text
SUS Lake / SUS Semântica
│
├── 00 Arquitetura
│   ├── Raw / Bronze / Silver
│   ├── staging/runtime
│   ├── PostgreSQL / DuckDB / Parquet
│   └── publicação
│
├── 01 Metadados e contratos
│   ├── schemas
│   ├── campos fonte -> canônico
│   ├── chaves
│   ├── relacionamentos
│   └── quality rules
│
├── 02 Referências temporais
│   ├── CNES
│   ├── SIGTAP
│   ├── território
│   └── domínios/layouts DATASUS
│
├── 03 Fatos
│   ├── SIA
│   ├── SIH
│   ├── CIH/CIHA
│   ├── SIM
│   ├── SINASC
│   ├── SINAN
│   ├── PNI
│   ├── PCE
│   ├── RESP
│   └── Painel Oncologia
│
├── 04 Identidade longitudinal
│   └── ERLEN_PID
│
├── 05 Gold
│   ├── clínico/PCDT/ML
│   ├── OMOP
│   └── indicadores
│
└── 06 Operação
    ├── ETL
    ├── CQ
    ├── promoção
    └── publicação
```

## Arquivos normativos principais

### Arquitetura e decisões

- `docs/modeling/DECISIONS_CURRENT.md` — decisões vigentes;
- `docs/modeling/DECISIONS_SUPERSEDED.md` — decisões substituídas;
- `docs/modeling/OPEN_ISSUES.md` — pendências e gates;
- `docs/modeling/CHAT_TRACEABILITY.tsv` — rastreabilidade histórica;
- `docs/adr/0001-storage-layers.md` — camadas e runtime;
- `docs/adr/0008-publicacao-suslake.md` — superfície pública.

### Contratos transversais

- `catalog/source_schema_contract.tsv`;
- `catalog/source_schema_ignore.tsv`;
- `catalog/source_field_map.tsv`;
- `catalog/field_dictionary.tsv`;
- `catalog/fields.tsv`;
- `catalog/keys.tsv`;
- `catalog/relationships.tsv`;
- `catalog/quality_rules.tsv`;
- `catalog/tables.tsv`.

### Sistemas

- `systems/sia/`;
- `systems/sih/`;
- `systems/cih/`;
- `systems/ciha/`;
- `systems/cnes/`;
- `systems/sim/`;
- `systems/sinasc/`;
- `systems/sinan/`;
- `systems/painel_oncologia/`;
- `systems/pce/`;
- `systems/pni/`;
- `systems/resp/`;
- `systems/identity/`;
- `systems/omop/`.

### Operação e CQ

- `ops/build-source-field-inventory.py`;
- `ops/qc-source-schema-coverage.py`;
- `ops/qc-model-contracts.py`;
- `ops/qc-sih-source-staging-live.py`;
- `ops/sih-promote-staging-bronze.py`.

## Regra de retomada

Ao retomar o projeto:

1. ler este índice;
2. ler `DECISIONS_CURRENT.md`;
3. ler `OPEN_ISSUES.md`;
4. verificar `git status`, branch/PR e últimos commits;
5. verificar markers/estado real em `suslake/state`;
6. executar os CQs pertinentes antes de alterar ou promover dados.

Se um chat antigo divergir do Git consolidado, prevalece o Git, exceto se uma nova decisão explícita for tomada e registrada.
