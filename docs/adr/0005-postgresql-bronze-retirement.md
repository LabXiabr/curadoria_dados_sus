# ADR 0005 — Aposentadoria do Bronze PostgreSQL e liberacao da pipeta

Status: aceito

## Objetivo

Remover progressivamente do PostgreSQL as copias analiticas que passam a ter
representacao canonica no SUS Lake, liberando a pipeta para computacao do ERLEN
e do ambiente ANA.

A Bronze persistente passa a ser Parquet no SUS Lake. PostgreSQL permanece
somente quando houver necessidade explicita de serving, aplicacao transacional,
materializacao de alta reutilizacao ou outro workload que justifique banco
relacional.

## Contexto legado

O processamento historico distribuiu tabelas DBC entre:

- pipeta: competencias >= 2020;
- bureta: competencias < 2020.

As tabelas lista_dissemin_dbc_* registram, entre outros, origem DBC, URL,
competencia, schema/tabela SQL, existencia SQL, bytes e registros SQL/DBC.
Esses metadados devem ser usados para auditar a migracao antes de qualquer DROP.

## Gate obrigatorio por tabela/competencia

Uma tabela PostgreSQL so pode ser removida quando todos os itens abaixo forem
verdadeiros:

1. Raw canonico existe no lake e possui identidade SHA-256 registrada;
2. republicacoes/volatilidade da fonte estao preservadas;
3. Bronze Parquet correspondente foi construida;
4. contagem Bronze e equivalente a fonte/DBC e ao inventario legado aplicavel;
5. CQ estrutural esta aprovado;
6. CQ externo oficial esta aprovado quando houver referencia, especialmente
   TabNet para SIA/SIH/SIM/SINASC/SINAN;
7. a revisao consta como official_current quando a fonte for volatil;
8. existe registro persistente do DROP planejado com servidor, schema, tabela,
   competencia, bytes, linhas, Raw SHA, Bronze e identificador do CQ.

Falha ou ausencia de qualquer gate bloqueia o DROP.

## Ordem recomendada

Prioridade de liberacao da pipeta:

1. SIA;
2. SIH;
3. SIM/SINASC/SINAN;
4. CIH/CIHA;
5. demais familias DBC migradas e homologadas.

SIA/SIH recebem prioridade por volume e por volatilidade/reprocessamento
retroativo.

## Manifesto de aposentadoria

O lake deve manter um manifesto auditavel com pelo menos:

- sistema;
- subsistema;
- competencia;
- servidor legado;
- database;
- schema;
- tabela;
- bytes SQL;
- registros SQL;
- DBC de origem;
- Raw SHA-256;
- Bronze path/revision;
- Bronze rows;
- QC id/status;
- official_current;
- drop_eligible;
- dropped_at;
- resultado do DROP.

O manifesto e preservado mesmo depois da remocao fisica da tabela SQL.

## Execucao

O DROP e sempre executado por lote pequeno e explicitamente homologado.

Apos cada lote:

- verificar retorno do PostgreSQL;
- verificar espaco liberado no host;
- atualizar o manifesto;
- executar consultas de regressao no lake;
- nao apagar Raw ou Bronze como consequencia do DROP.

Nao e necessario manter uma copia PostgreSQL Bronze apenas como backup.

## Destino da pipeta

A capacidade liberada e destinada prioritariamente a:

- ERLEN: agentes/LLMs locais para consulta e relatorios analiticos;
- inferencia com modelos locais, incluindo Qwen quando selecionado;
- DuckDB e workloads analiticos temporarios;
- conversao/geracao dos atuais paineis R Shiny para artefatos HTML no ambiente ANA;
- caches e materializacoes descartaveis.

Os dados canonicos permanecem na bureta/SUS Lake; a pipeta pode consumir Parquet
remotamente ou por cache local sem reassumir o papel de arquivo mestre.
