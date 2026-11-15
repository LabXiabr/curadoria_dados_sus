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

## Próxima etapa

O backfill temporal somente é promovido após inventário das competências Raw CNES
disponíveis e execução do QC de chaves por competência.
