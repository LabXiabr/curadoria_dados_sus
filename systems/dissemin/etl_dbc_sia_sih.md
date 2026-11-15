# SIA/SIH — fonte de migração e recomposição

## Migração inicial

A fonte operacional para a transposição inicial é o PostgreSQL `bdsus`, que
já contém o resultado histórico do processamento DBC -> DBF -> CSV -> SQL.

Fluxo:

```text
PostgreSQL bdsus
  -> Bronze Parquet lossless
  -> QC COUNT PostgreSQL = Parquet
  -> Silver canônica
  -> QC externo TabNet
  -> somente depois: candidato à retirada PostgreSQL
```

Nenhuma tabela PostgreSQL é removida automaticamente.

## DBC

DBC não participa da migração inicial. Para competências ausentes, republicadas
ou futuras, a recomposição deve usar a ETL Wine existente do projeto.

O loader experimental baseado em microdatasus foi desativado.

## SIA PA / CNSPCN

Após a migração de PA e famílias APAC, CNSPCN pode ser recuperado para linhas
PA sem CNS usando a autorização:

- mesma UF;
- mesma autorização;
- competência exata preferida;
- busca até 3 meses antes/depois;
- menor distância mensal;
- empate só é aceito quando os candidatos concordam no mesmo CNS;
- a operação não pode alterar o número de linhas da PA;
- origem, subsistema, competência e distância são preservados.
