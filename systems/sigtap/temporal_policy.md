# SIGTAP Silver temporal

## Objetivo

Comprimir a repetição mensal da SIGTAP sem perder nenhum estado observado na Bronze homologada.

## Unidade de identidade

Cada tabela usa a chave natural registrada em `systems/sigtap/keys.tsv`. O cadastro cobre todas as 41 tabelas da estrutura atual; chaves históricas adicionais permanecem no registro para compatibilidade.

## Volatilidade

- `_source_competencia`, `_source_zip`, `_source_sha256` e `_ingested_at` são proveniência de ETL e não participam do estado semântico.
- `dt_competencia` é um campo temporal da fonte e não participa do hash semântico, pois sua alteração mensal criaria falsa volatilidade.
- `dt_competencia` é preservada em `_source_dt_competencias`, alinhada a `_observed_competencias`; portanto não é descartada.
- Todo outro campo oficial, inclusive descrições e valores, participa do hash semântico. Qualquer mudança real abre um novo estado temporal.

## Intervalos

Um intervalo só agrega observações consecutivas **entre snapshots em que aquela tabela existe**. Assim:

- ausência de uma competência inteira da fonte não é interpretada como exclusão;
- ausência de uma linha em uma competência disponível encerra o intervalo;
- reaparecimento posterior abre novo intervalo, mesmo com o mesmo hash semântico;
- mudança de multiplicidade também abre novo intervalo.

Campos principais:

- `valid_from_competencia` / `valid_to_competencia`: intervalo inclusivo;
- `_snapshot_count`: snapshots agregados;
- `_multiplicity`: multiplicidade por snapshot no intervalo;
- `_observed_competencias`: competências efetivamente agregadas;
- `_source_dt_competencias`: `dt_competencia` alinhada às competências;
- `_semantic_hash`: hash somente dos atributos semânticos;
- `_is_current`: alcança a última competência SIGTAP homologada globalmente.

## Completude e QC

A Silver só é construída se toda competência Raw canônica possuir marker de QC Raw→Bronze apontando para o mesmo ZIP canônico.

Para cada tabela, o processo reconstrói logicamente o multiconjunto de linhas oficiais a partir da Silver e compara hashes e multiplicidades com toda a Bronze. Qualquer divergência bloqueia `silver_complete.ok`.

A proveniência por competência é preservada em `silver/sigtap/_snapshots.parquet`.
