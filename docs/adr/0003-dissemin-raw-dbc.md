# ADR 0003 — Raw DBC do DATASUS: espelho de caminhos, deduplicacao e memoria de republicacoes

Status: aceito

## Contexto

O acervo DBC legado foi reunido em:

- `raw/dissemin/dbc/_legacy/from_home`;
- `raw/dissemin/dbc/_legacy/from_sdb`.

O objetivo do Raw e preservar os artefatos originais do DATASUS, inclusive arquivos
que deixaram de ser disseminados, sem obrigar todos os sistemas a participar da ETL.

A versao historica `bdsus_lista_ftp_dbc2sql_20261018_v12.sh` usa
`qt_bytes_ftp + dt_ftp + hr_ftp` para detectar arquivos novos/republicados,
reconsulta `SIZE` em execucoes longas e valida bytes antes da carga. O antigo
arquivo mestre, contudo, e plano e identifica o arquivo principalmente pelo basename.

## Decisao

### 1. O Raw DBC preserva a arvore relativa do FTP

Raiz canonica:

```text
/dados/abertos/suslake/raw/dissemin/publicos/
```

Uma URL como:

```text
ftp://ftp.datasus.gov.br/dissemin/publicos/SIASUS/200801_/Dados/PAAC2401.dbc
```

mapeia para:

```text
raw/dissemin/publicos/SIASUS/200801_/Dados/PAAC2401.dbc
```

Nao sera adotado diretorio unico/flat para o novo Raw.

### 2. Identidade de arquivo

A identidade definitiva do conteudo local e SHA-256.

O fingerprint remoto e usado para decidir se e necessario baixar:

1. caminho relativo no FTP;
2. tamanho remoto;
3. data/hora remotas quando disponibilizadas.

Tamanho ou data isoladamente nao certificam identidade.

Quando o fingerprint remoto mudar:

1. baixar para arquivo temporario;
2. calcular SHA-256;
3. se o SHA-256 for igual ao arquivo canonico, atualizar somente metadados;
4. se for diferente, preservar a versao anterior e publicar a nova de forma atomica.

### 3. Memoria de republicacoes

O caminho canonico representa a ultima versao observada daquele caminho FTP.

Conteudos anteriores, quando o mesmo caminho for republicado com SHA-256 diferente,
sao preservados em:

```text
raw/dissemin/_versions/<caminho-relativo>/<nome>@<sha256>.dbc
```

A expectativa e que esse volume seja pequeno em relacao ao acervo total.

### 4. Arquivos removidos do FTP

Um arquivo que desaparece do servidor nao e apagado localmente.

Ele permanece no caminho original e o manifesto registra `remote_missing` e
`last_seen_at`. Isso e especialmente importante para fontes historicas como
`CMD/DadosSISAB`.

### 5. Deduplicacao

Antes de excluir qualquer arquivo em `_legacy`:

- gerar/integrar manifestos SHA-256;
- identificar duplicatas entre `from_home` e `from_sdb`;
- mapear o arquivo para um caminho canonico do FTP quando possivel;
- usar hardlink quando origem e destino estao no mesmo filesystem;
- verificar SHA-256 e tamanho;
- somente entao remover o nome legado redundante.

Arquivos unicos ou sem origem conhecida nunca sao descartados automaticamente.

### 6. Raw e ETL sao politicas independentes

A inclusao no backup Raw nao implica inclusao em ETL.

A politica por fonte esta em `systems/dissemin/source_policy.tsv`.

Exemplos:

- SIA/SIH/SIM/SINASC/SINAN/CIH/CIHA: Raw + candidatos a ETL;
- ESUSNOTIFICA/SISCAN/PCE: Raw, mas fora da ETL DBC geral;
- CNES DBC de `dissemin/publicos/CNES/200508_/Dados`: preservar como arquivo
  historico/secundario; o pipeline corrente CNES usa
  `ftp://ftp.datasus.gov.br/cnes/BASE_DE_DADOS_CNES_AAAAMM.ZIP`.

## Consequencias

- elimina risco de colisao por basename;
- mantem proveniencia 1:1 com a fonte;
- permite reconstruir o acervo mesmo quando diretorios deixam de existir;
- evita duplicacao fisica durante a migracao por hardlinks;
- separa backup de fonte de decisao de modelagem/ETL;
- permite evoluir o antigo `bdsus_lista_ftp_dbc2sql` para consumir o Raw canonico
  sem manter um segundo arquivo mestre plano.
