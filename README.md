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

## SIGTAP completa e temporal

A Bronze histórica completa é construída competência a competência com QC independente Raw→Bronze. A Silver temporal só inicia quando toda competência Raw canônica estiver homologada para o mesmo ZIP selecionado.

Execução completa na bureta:

```bash
cd /dados/abertos/repos/curadoria_dados_sus
git switch develop
git pull --ff-only origin develop
./ops/sigtap-complete.sh
```

A política de volatilidade e reconstrução lossless está em `systems/sigtap/temporal_policy.md`.

## Referencias territoriais e demograficas

A geografia de referencia do lake e independente de CNES/SIA/SIH.

### Base territorial DATASUS

Fonte principal para municipio, UF, regiao, regioes de saude e demais
classificacoes territoriais usadas pelo DATASUS/TABNET.

```bash
./ops/territorio-complete.sh --year 2026
```

Raw:

```text
raw/reference/territorio/year=2026/snapshot=AAAAMM/<zip oficial>
```

Bronze: todas as tabelas CSV do snapshot.

Silver: uma `current.parquet` por tabela em
`silver/reference/territorio/<tabela>/`. Carregar snapshot historico nao
regride a referencia corrente.

### Regionalizacao de saude corrente

O conjunto especifico do Portal de Dados Abertos do SUS e mantido em paralelo
para Regiao de Saude e Macrorregiao de Saude e serve tambem para QC da base
territorial.

```bash
./ops/regionalizacao-saude-complete.sh
```

Divergencias entre as duas fontes devem ser reportadas; nenhuma das fontes
sobrescreve silenciosamente a outra.

### Populacao detalhada POPSVS

Fonte principal para populacao por municipio, ano, sexo e idade:

```bash
./ops/popsvs-complete.sh --from 2000 --to 2025
```

Saida Silver:

```text
silver/reference/populacao_idade_sexo/ano=AAAA/part-000.parquet
```

O projeto `LabXiabr/tabnet-populacao` permanece como extracao independente
para conferir totais municipais do TabNet.

Politica de fontes: `systems/reference/source_policy.md`.

## CNES

A fonte Raw preferencial do CNES e o snapshot oficial
`BASE_DE_DADOS_CNES_AAAAMM.ZIP`. A Bronze completa e local/privada.

```bash
./ops/cnes-base-complete.sh --competencia latest
```

Antes da primeira carga, aplicar `ops/apache/labx-suslake-private.conf`.

### CEP Brasil

`CEP_BRASIL.ZIP` e versionado por SHA-256 e convertido para referencias
especificas do SCNES:

```bash
./ops/cnes-cep-complete.sh
```
