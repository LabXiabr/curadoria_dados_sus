# Política temporal do CNES

Status: aceito

## Princípio

O CNES é uma fonte mensal. Nenhuma relação observada em uma única competência
é promovida automaticamente a invariante histórica.

A competência integra toda chave Silver histórica.

## Chaves

- estabelecimento: `competencia + CO_UNIDADE`;
- identificador público: `competencia + CO_CNES`;
- equipe: `competencia + CO_MUNICIPIO + CO_AREA + SEQ_EQUIPE`;
- INE: preservado como `CO_EQUIPE`, sem substituir a chave relacional quando ausente;
- profissional: `competencia + CO_PROFISSIONAL_SUS`;
- vínculo profissional: `competencia + CO_UNIDADE + CO_PROFISSIONAL_SUS + CO_CBO + IND_VINCULACAO` e demais componentes da chave efetiva da fonte;
- fatos/bridges: sempre incluem `competencia` mais a chave natural da tabela fonte.

## Current

`silver/cnes/<objeto>/current.parquet` representa somente a competência
homologada corrente.

O arquivo pode ser substituído atomicamente quando uma competência mais nova
for homologada.

## Histórico

A forma canônica para materialização histórica é:

```text
silver/cnes/<objeto>/competencia=AAAAMM/part-000.parquet
```

Não se fabrica SCD2 a partir dos snapshots. Alterações de estado são derivadas
comparando competências consecutivas.

Para objetos muito grandes, especialmente profissionais e carga horária,
a história Silver pode ser materializada por demanda. Raw + Bronze mensal
permanecem a fonte de reconstrução.

## Regras

1. `CO_UNIDADE <-> CO_CNES` é validado por competência; não assumir relação
   global sem QC histórico.
2. Geografia é resolvida usando a referência territorial vigente registrada no build.
3. A crosswalk DF -> RA é versionada pela fonte IBGE e pela competência CNES.
4. Views `current` nunca misturam competências.
5. Queries longitudinais devem declarar explicitamente a competência ou intervalo.

## Promoção do snapshot homologado

Após `qc_global_AAAAMM.ok`, `ops/cnes-promote-silver-snapshot.py` cria por
hardlink a partição histórica de cada objeto Silver. O histórico é imutável:
se uma partição já existir com inode diferente, a promoção falha em vez de
sobrescrever.

## PostgreSQL

A Bronze mensal em Parquet é a representação relacional canônica dos dados
abertos CNES. O PostgreSQL é tratado como legado/cache durante a transição.
A retirada de tabelas segue `systems/cnes/postgresql_retirement.md`.

## Próxima etapa

Inventariar e backfilar as competências históricas necessárias, executar os
QCs por competência e só então retirar do PostgreSQL as tabelas Bronze
redundantes.


## Backfill histórico em duas etapas

O backfill histórico é deliberadamente separado:

1. **Raw + Bronze + QCs de base** podem ser carregados para qualquer competência
   oficial disponível, pois são fiéis ao lote mensal e independem de
   regionalização histórica.
2. **Silver histórica** só deve ser promovida quando a referência territorial
   usada estiver explicitamente identificada. Enquanto a história da Base
   Territorial estiver `deferred`, não se deve interpretar Região de Saúde,
   Macrorregião ou demais classificações correntes como se fossem históricas.

`ops/cnes-list-remote-history.sh` inventaria as competências disponíveis no
FTP oficial. `ops/cnes-backfill-bronze.sh` planeja ou executa somente o
backfill Raw/Bronze.

Atributos nativos do CNES (estabelecimento, tipo, natureza, serviços,
equipamentos, leitos, equipes, profissionais e vínculos) permanecem
mensais. A geografia derivada deve carregar a proveniência da referência
territorial utilizada.
