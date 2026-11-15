# Retirada do Bronze CNES do PostgreSQL

Status: planejado; nenhuma exclusão automática.

## Autoridade dos dados

A representação relacional fiel do snapshot oficial CNES passa a ser:

```text
suslake/bronze/cnes/<tabela>/competencia=AAAAMM/part-000.parquet
```

O PostgreSQL deixa de ser a camada Bronze canônica. Pode continuar temporariamente como cache/compatibilidade para aplicações legadas.

## Temporalidade

O Raw preserva o ZIP oficial mensal. A Bronze preserva cada tabela mensal em Parquet. A Silver homologada é promovida por competência com hardlink:

```text
silver/cnes/<objeto>/current.parquet
silver/cnes/<objeto>/competencia=AAAAMM/part-000.parquet
```

O hardlink histórico impede que a troca atômica futura de `current.parquet` apague o snapshot anterior e não duplica blocos no disco.

## Condições para retirar uma tabela PostgreSQL

Uma tabela PostgreSQL só pode ser retirada quando:

1. todas as competências necessárias estiverem presentes no Raw;
2. cada competência tiver `qc_bronze_AAAAMM.ok`;
3. o número de linhas da Bronze for lossless em relação ao CSV do ZIP;
4. chaves relevantes tiverem QC aprovado;
5. dependências de aplicações, views, jobs e consultas SQL tiverem sido inventariadas;
6. houver uma consulta DuckDB/Parquet equivalente documentada;
7. a exclusão for explicitamente autorizada.

Nenhum script deste projeto executa `DROP` automático de tabelas CNES.

## Inventário PostgreSQL

`ops/cnes-audit-psql-retirement.sh` gera inventário somente leitura das tabelas candidatas e das tabelas de outros sistemas que apenas contêm `CO_CNES`/`CO_UNIDADE`.

Tabelas de produção como SIA/SIH/CIHA que tenham `CO_CNES` não são classificadas automaticamente como CNES e não devem ser removidas por este processo.

## Uso como referência

Para fatos de produção e notificação, a preferência é:

- join temporal por competência quando o atributo CNES for volátil;
- `CO_CNES` como identificador público do estabelecimento;
- `CO_UNIDADE` somente em relações internas do próprio CNES;
- dimensões Silver públicas para consumo analítico;
- Bronze mensal para auditoria, reconstrução e atributos não promovidos à Silver.
