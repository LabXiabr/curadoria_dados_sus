# Catálogo DuckDB público

O catálogo local do DBeaver referencia os Parquet publicados em https://dados.labx.ia.br/files/; nenhum dado volumoso é copiado para o Git ou para o arquivo DuckDB.

O contrato está em catalog/endpoints.tsv e catalog/datasets.tsv. O gerador percorre apenas os caminhos declarados, descobre os Parquet visíveis no autoindex HTTP e cria views com listas explícitas de URLs.

Gerar o SQL:

    python3 ops/build-duckdb-public-catalog.py

Aplicar diretamente ao catálogo local (feche/desconecte o DBeaver antes para evitar lock do arquivo):

    python3 ops/build-duckdb-public-catalog.py --database ~/duckdb/bureta.duckdb

Se o CLI duckdb não estiver disponível na bequer, execute no DBeaver o arquivo gerado:

    sql/duckdb/generated/public_catalog.sql

Objetos criados:
- catalogo.endpoints
- catalogo.datasets
- catalogo.views_disponiveis
- schemas sim, sigtap, sia, sih, ciha, cnes, sinasc e sinan
- views somente para conjuntos realmente publicados

SIA/SIH e outros sistemas podem permanecer sem views até que seus Parquet sejam publicados sob o caminho declarado no manifesto. Uma nova execução reconcilia automaticamente o catálogo.
