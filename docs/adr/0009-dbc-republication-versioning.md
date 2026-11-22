# ADR 0009 — Versionamento de DBC republicado pelo DATASUS

Status: accepted

## Contexto

Arquivos DBC do DATASUS podem ser republicados mantendo o mesmo nome de arquivo.
Assim, nome + sistema + série + competência não identificam necessariamente uma
versão física imutável.

Durante a migração de acervos legados, um DBC externo pode divergir do arquivo
atualmente publicado no FTP mesmo quando ambos são válidos em momentos distintos.

## Decisão

O Raw canônico em:

`raw/dissemin/dbc/<caminho relativo ao FTP>/<arquivo>.dbc`

representa a versão corrente validada contra o FTP oficial.

Versões históricas divergentes não são sobrescritas nem descartadas. Elas são
preservadas em:

`raw/dissemin/dbc/_legacy/<origem>/<snapshot>/<caminho relativo ao FTP>/<arquivo>.dbc`

Toda comparação destrutiva usa SHA-256.

Um arquivo legado só pode ser removido de mídia externa quando a política
operacional explicitamente autorizar a remoção e houver evidência persistida da
cópia preservada correspondente. A igualdade com a versão FTP atual é um gate
mais forte e continua sendo usada quando aplicável.

## Consequências

- `filename` não é identificador de versão;
- SHA-256 passa a integrar a proveniência Raw;
- a versão atual do FTP nunca deve ser substituída silenciosamente por uma cópia
  histórica divergente;
- republicações podem ser estudadas e auditadas;
- processos Bronze/Silver devem registrar o SHA-256 ou a versão Raw de origem
  quando o DBC puder ter sido republicado.
