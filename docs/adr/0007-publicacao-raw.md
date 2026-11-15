# ADR 0007 — Projeção pública do Raw oficial

Status: aceito

## Decisão

Os artefatos Raw oficiais permanecem canônicos em `suslake/raw/`. Para
distribuição pública, os arquivos autorizados são projetados em:

```text
/dados/abertos/raw/
```

Como o Apache publica `/dados/abertos/` sob `/files/`, a URL é:

```text
https://dados.labx.ia.br/files/raw/
```

Não existe uma nova camada de dados. `/dados/abertos/raw/` é apenas uma
superfície de publicação dos mesmos artefatos Raw.

## Hardlinks

A projeção usa hardlinks, não novo download e não cópia. O arquivo canônico e
o arquivo publicado apontam para o mesmo inode e ocupam os mesmos blocos no
filesystem. Remover o hardlink público não remove o Raw enquanto o link
canônico continuar existente.

Se origem e destino estiverem em filesystems diferentes, o processo falha em
vez de copiar silenciosamente os dados.

## Política e catálogo

A allowlist versionada está em:

```text
catalog/raw_publication.tsv
```

O inventário concreto é gerado em:

```text
/dados/abertos/raw/catalog.tsv
```

O catálogo público registra dataset, arquivo, tamanho, SHA-256, fonte oficial,
URL pública e instante da projeção.

O diretório `/files/repos/curadoria_dados_sus/` contém código, políticas e
documentação do projeto; não substitui o inventário dos artefatos efetivamente
publicados.

## Primeira publicação

Inicialmente são projetados:

- Base Territorial DATASUS;
- POPSVS;
- SIGTAP.

Outros sistemas são acrescentados à allowlist quando seus layouts Raw e
caminhos canônicos estiverem estabilizados no lake.

## Segurança operacional

O bloqueio de `/files/suslake/raw/` pode permanecer. A publicação ocorre por
`/files/raw/`, evitando que caminhos operacionais, temporários ou artefatos
não catalogados do lake sejam expostos por acidente.

O HTTP é somente leitura. O pipeline valida HEAD e HTTP Range em pelo menos um
arquivo de cada dataset projetado.
