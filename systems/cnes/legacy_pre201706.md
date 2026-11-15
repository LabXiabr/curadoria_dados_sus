# CNES histórico anterior à série BASE_DE_DADOS_CNES

Status: em migração.

## Corte de arquitetura

O Portal CNES documenta a disponibilidade do download da Base de Dados por
competência a partir de 06/2017. Portanto:

- `201706+`: fonte preferencial `BASE_DE_DADOS_CNES_AAAAMM.ZIP`;
- `<201706`: não usar a série BASE_DE_DADOS_CNES como fonte canônica, mesmo
  que nomes anteriores apareçam em listagem FTP;
- o histórico anterior deve ser reconstruído a partir do legado já preservado
  no PostgreSQL e/ou arquivos DBC/TXT oficiais que originaram essas tabelas.

## Evidência local

O inventário PostgreSQL contém tabelas CNES mensais anteriores a 201706,
inclusive famílias como `pf<UF><AAMM>`. Elas devem ser tratadas como um
formato legado separado, com mapeamento explícito de tabela/UF/competência.

## Destino

A migração do legado pré-201706 deve produzir Parquet canônico separado por
família, UF e competência, por exemplo:

```text
bronze/cnes_legacy/<familia>/uf=SP/competencia=201501/part-000.parquet
```

Não misturar esses arquivos diretamente com as 109 tabelas do layout moderno
sem uma etapa de conformação, pois os schemas são diferentes.

## Regras para retirada do PostgreSQL legado

Uma tabela antiga só pode ser removida do PostgreSQL após:

1. exportação lossless para Parquet;
2. contagem de linhas equivalente;
3. hash/manifest da exportação;
4. identificação de família, UF e competência;
5. inventário de dependências;
6. homologação explícita.

Nenhum DROP é automático.
