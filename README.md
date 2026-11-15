# Curadoria de Dados SUS

Projeto público de Curadoria de Dados (*Data Stewardship*) do ecossistema LabX.ia.br
para dados abertos do SUS.

Escopo técnico:

- aquisição e versionamento de fontes oficiais;
- preservação de dados brutos e proveniência;
- transformação relacional para Parquet/DuckDB;
- documentação de layouts, domínios, chaves e relacionamentos;
- controle de qualidade e rastreabilidade temporal;
- preparação de camadas semânticas para análise epidemiológica, dados abertos,
  OMOP e coortes/PCDT.

A Curadoria de Dados é tratada aqui como função técnica dentro da Governança de Dados.
O projeto não substitui a governança estratégica/institucional.

## Camadas

- **Raw**: artefato oficial original e imutável.
- **Bronze**: representação relacional fiel à fonte, em Parquet.
- **Silver**: modelo semântico/temporal, sem obrigar materialização de fatos gigantes.
- **Gold**: produtos analíticos, indicadores oficiais, OMOP e coortes.

## Implementações

- `etl/parquet_duckdb/`: ETL canônica atual.
- `etl/psql/`: código provisório/legado da transposição PostgreSQL -> Parquet.
- `systems/`: contratos semânticos, layouts, domínios, relações e QC por sistema.
- `catalog/`: catálogo transversal da curadoria.

Dados volumosos não são versionados em Git.

## Acesso público aos Parquet

- Endpoint: `https://dados.labx.ia.br/files/`.
- Transporte: HTTPS público, somente leitura, com HTTP Range.
- O catálogo DuckDB local para DBeaver é gerado por `ops/build-duckdb-public-catalog.py`.
- As regras de descoberta ficam em `catalog/endpoints.tsv` e `catalog/datasets.tsv`.
- O SQL operacional gerado não é versionado; ele reflete os Parquet publicados no momento da execução.

Exemplo:

```bash
python3 ops/build-duckdb-public-catalog.py --database ~/duckdb/bureta.duckdb
```
