# Política de domínios e metadados auxiliares DATASUS

Status: desenho canônico inicial.

DBC/DBF de produção não são autossuficientes. DEF, CNV, DBD e tabelas DBF dos
pacotes auxiliares são fontes canônicas de domínio/layout e permanecem
preservadas mesmo após materialização de dimensões Silver.

## Raw

```text
raw/reference/datasus_auxiliary/system=<SISTEMA>/source=<source_id>/sha256=<SHA256>/<artefato>
```

Nome remoto não identifica conteúdo. Registrar SHA-256 e data de observação.

## Bronze

Extrair todos os membros. DBF/CSV/TXT tabular vira Parquet lossless. DEF/CNV/
DBD permanecem também como original; estruturas parseadas são adicionais.
Registrar membro, encoding, formato, tamanho, hash e parser utilizado.

## Silver

Produtos reutilizáveis:

- `reference.datasus_domain`: código/rótulo versionado;
- `reference.datasus_layout_field`: campo, posição/tipo/rótulo e domínio
  quando explicitamente extraível.

Chave conceitual: `system + source_id + domain_id + code + intervalo + source_sha256`.
Não propagar rótulo corrente retroativamente.

## Regras temporais

Pacote com intervalo explícito só rotula fatos daquele intervalo. Pacote
corrente é snapshot móvel: cada hash novo cria versão. Data observada não é
automaticamente data jurídica de vigência.

Para SIA/SIH desde 2008, SIGTAP mensal é referência semântica preferencial de
`co_procedimento`. TAB_SIA/TAB_SIH permanecem para compatibilidade, TabWin,
reconstrução e QC. Antes da SIGTAP, usar o pacote histórico do período.

CID/CBO externos podem enriquecer a Silver, mas não substituem silenciosamente
conversões específicas DATASUS.

## Metadados canônicos

Snapshot baseado em `LabXiabr/bd_geral` commit
`a216d754ce7a0322e965f29242ad35bd5d4882d8`, complementado pelo catálogo
FTP do `ftpsus_navegador`. O navegador mantém nomes físicos, anexa metadados
e só extrai enumerações quando há pares código-rótulo explícitos; essa
postura conservadora é adotada aqui.


## Aquisição operacional

`ops/acquire-datasus-auxiliary.py` lê `catalog/auxiliary_sources.tsv`,
baixa o artefato com progresso visível, calcula SHA-256 e grava manifesto dos
membros de ZIP. Pacotes rolling só são baixados novamente com `--refresh`.
Diretórios marcados como `discover` geram listagem para curadoria posterior.

A aquisição não interpreta automaticamente DEF/CNV/DBD. Primeiro preserva e
inventaria; o parser Bronze será específico por formato e validado contra os
membros reais.
