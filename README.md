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

## Raw oficial para download

Os artefatos Raw selecionados são publicados sem duplicação de disco por
hardlinks em:

```text
/dados/abertos/raw/
https://dados.labx.ia.br/files/raw/
```

A allowlist fica em `catalog/raw_publication.tsv` e o inventário concreto
gerado fica em `/dados/abertos/raw/catalog.tsv`.

Publicação completa:

```bash
./ops/publish-raw-artifacts.py
```

Publicação seletiva do CNES após o QC global:

```bash
./ops/publish-raw-artifacts.py --dataset cnes
```

O snapshot mensal CNES só é publicado quando o respectivo
`state/cnes/qc_global_AAAAMM.ok` estiver validado.

Isso não cria nova camada: os arquivos continuam sendo Raw. O caminho público
é apenas uma projeção dos mesmos inodes preservados em `suslake/raw/`.

Política completa: `docs/adr/0007-publicacao-raw.md`.

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


### Contexto territorial municipal

A carga territorial materializa uma referência corrente com uma linha por
município ativo:

```text
silver/reference/municipio_contexto/current.parquet
```

Ela combina município, código IBGE de 7 dígitos, UF, região, Região de Saúde,
Macrorregião de Saúde, microrregião IBGE, região metropolitana/RIDE,
Território da Cidadania, PNDR, divisão administrativa e DSEI. Os indicadores
municipais confirmados na fonte incluem capital, Amazônia Legal e semiárido.
`IN_FRONTZN` é preservado com nome semântico conservador até confirmação
documental de seu significado exato no snapshot corrente.

A Silver conformada para análise fica em:

```text
silver/reference/dim_territorio/current.parquet
```

A chave `co_territorio_key` identifica o menor território resolvido com
segurança (`MUN:<IBGE7>` ou `RA_DF:<IBGE11>`). Para drill passando por
Macrorregião de Saúde usa-se uma chave de Região de Saúde dentro da Macro,
pois a Região de Saúde canônica pode atravessar Macrorregiões (caso Central
de Rondônia). Classificações como DSEI, microrregião IBGE,
região metropolitana, PNDR e Território da Cidadania são hierarquias
alternativas, não níveis obrigatórios dessa cadeia.

O CNES Silver usa integridade referencial lógica validada por QC:
`fact_* -> dim_estabelecimento -> dim_territorio`. Parquet não possui FK
física. O contrato completo está em
`docs/adr/0006-silver-territorio-cnes.md`.

O pipeline CNES também cria o catálogo privado
`silver/suslake.duckdb`, com views `cnes.vw_*_drill` que enriquecem os
fatos virtualmente sem duplicar a geografia nas tabelas factuais.


### CNES Parquet público e histórico

A Bronze completa continua canônica e protegida em `suslake/bronze/cnes/`.
Um subconjunto próprio para referência é projetado por hardlink em
`/dados/abertos/bronze/cnes/`, disponível em
`https://dados.labx.ia.br/files/bronze/cnes/`.

A Silver homologada é promovida por competência e o subconjunto de dimensões
e relações de referência é projetado em
`/dados/abertos/silver/cnes/`, disponível em
`https://dados.labx.ia.br/files/silver/cnes/`.

Profissionais, equipes e vínculos integram a superfície pública CNES, em
coerência com a consulta pública do próprio SCNES. Assim, a publicação de
referência mantém juntos `dim_profissional`, `fact_profissional_vinculo`,
`fact_equipe` e `bridge_estabelecimento_equipe_profissional`, além dos
objetos de estabelecimento, serviço, equipamento e leito.

Após o QC global:

```bash
python3 ops/cnes-promote-silver-snapshot.py --competencia 202610
./ops/cnes-publish-reference.sh 202610
```

A Bronze mensal em Parquet passa a ser a fonte relacional canônica dos dados
abertos CNES. O plano para retirar tabelas equivalentes do PostgreSQL está em
`systems/cnes/postgresql_retirement.md`.


Inventário da cobertura temporal do lake e das projeções públicas:

```bash
./ops/cnes-inventory-history.py
```

Inventário somente leitura das tabelas PostgreSQL candidatas à retirada:

```bash
./ops/cnes-audit-psql-retirement.sh
```


Inventário das competências CNES disponíveis no FTP oficial:

```bash
./ops/cnes-list-remote-history.sh
```

Planejamento do backfill Raw/Bronze, sem baixar nada:

```bash
./ops/cnes-backfill-bronze.sh --from AAAAMM --to AAAAMM
```

Para executar de fato, acrescentar `--execute`. O backfill histórico Silver
fica separado enquanto a regionalização histórica não estiver versionada.

Execução isolada:

```bash
python3 etl/parquet_duckdb/reference/build_municipio_contexto.py
```


### Corte histórico CNES

A série `BASE_DE_DADOS_CNES` é considerada oficial para backfill a partir de
`201706`. Competências anteriores são tratadas como legado PostgreSQL/DBC e
seguem `systems/cnes/legacy_pre201706.md`.
