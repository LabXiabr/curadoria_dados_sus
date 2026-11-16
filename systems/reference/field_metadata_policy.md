# Política de metadados de atributos

## Objetivo

A modelagem distingue quatro níveis para não confundir observação física com semântica validada:

1. **inventário físico observado**: schema, campo, posições, tipos e quantidade de tabelas onde o campo aparece;
2. **layout/rotulagem oficial**: metadados DATASUS provenientes de DEF/CNV/DBD/DBF e demais documentos versionados;
3. **mapeamento fonte -> canônico**: `catalog/source_field_map.tsv`;
4. **dicionário canônico**: `catalog/field_dictionary.tsv`, com rótulo, descrição, papel semântico, referência, sensibilidade e domínio OMOP.

## Regra de preservação

Todo atributo de origem é preservado na Bronze mesmo que ainda não possua nome canônico ou rótulo validado.

Campo não mapeado recebe estado `unmapped_preserved`; ele não é descartado e não recebe semântica inventada.

## Inventário físico

`ops/build-source-field-inventory.py` gera o inventário compacto a partir de `information_schema.columns` de bureta e pipeta. O resultado operacional fica em `state/metadata/` e não precisa ser versionado a cada nova tabela.

Os snapshots fornecidos em 2026-11-16 mostraram diferenças físicas de tipos entre hosts/competências; tipo PostgreSQL observado é metadado físico, não autoridade sobre largura/semântica DATASUS.

## Rótulo e descrição

Rótulos e descrições só são preenchidos quando sustentados por contrato canônico, documentação DATASUS ou curadoria explícita. Ausência é registrada, não inferida.

## Relações

FKs são lógicas em Parquet. O contrato de relacionamento fica em `catalog/relationships.tsv`; CQ deve demonstrar que o join não multiplica fatos indevidamente e deve reportar órfãos por competência.
