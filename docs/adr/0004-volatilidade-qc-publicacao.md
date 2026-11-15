# ADR 0004 — Volatilidade das fontes, snapshots Bronze e publicacao homologada

Status: aceito

## Contexto

Fontes DATASUS podem ser republicadas retroativamente.

Exemplos:

- SIA/SIH: uma mesma competencia pode mudar por reapresentacao, glosa, acerto
  financeiro ou outra retificacao muitos meses depois;
- SIM/SINASC/SINAN: podem existir dados preliminares e posteriores consolidacoes;
- outras fontes podem republicar o mesmo caminho remoto com bytes diferentes.

O objetivo operacional e duplo:

1. preservar a memoria da fonte e permitir reproducao historica;
2. fazer com que a consulta padrao represente o dado oficial corrente e seja
   homologada por CQ externo, especialmente TabNet quando aplicavel.

## Decisao

### 1. Raw e append-only por conteudo

O caminho canonico em `raw/dissemin/publicos/<caminho FTP>` representa a ultima
versao observada daquele caminho remoto.

Quando o conteudo muda:

- a versao anterior nao e perdida;
- cada conteudo e identificado por SHA-256;
- versoes anteriores ficam em `raw/dissemin/_versions/`;
- um manifesto registra `first_seen_at`, `last_seen_at`, bytes, MDTM remoto,
  SHA-256 e estado remoto.

Raw responde a pergunta: "o que exatamente foi observado na fonte em cada momento?".

### 2. Bronze tambem preserva revisoes

Cada SHA-256 Raw que for transformado gera, no maximo, uma revisao Bronze imutavel.

Layout logico recomendado:

```text
bronze/<sistema>/<subtipo>/
  uf=<UF>/
    competencia=<AAAAMM>/
      revision=<sha12>/
        part-000.parquet
```

Quando UF/competencia nao se aplicarem, as particoes sao adaptadas ao sistema.

Toda revisao Bronze carrega proveniencia minima:

- `_source_path`;
- `_source_sha256`;
- `_source_bytes`;
- `_source_ftp_mtime`;
- `_first_seen_at`;
- `_bronze_built_at`;
- `_schema_version`.

A revisao Bronze nao e sobrescrita.

### 3. Manifestos selecionam a revisao corrente

Nao se duplica o dataset inteiro para cada fotografia.

Manifestos pequenos selecionam a revisao ativa por `source_key`.

Estados:

- `observed_current`: ultima revisao observada no FTP;
- `structural_ok`: parse e CQ estrutural aprovados;
- `official_current`: ultima revisao homologada por CQ externo;
- `superseded`: revisao historica substituida.

A consulta padrao usa `official_current`.

Uma consulta de reproducao pode selecionar um snapshot/manisfesto anterior
(`as_of`) sem depender do arquivo que hoje esta vigente no FTP.

### 4. CQ externo e gate de publicacao

Quando houver TabNet correspondente, a revisao nao se torna `official_current`
somente porque apareceu no FTP.

O gate inclui, conforme o sistema e a definicao do tabulador:

- numero de registros/eventos;
- quantidade aprovada;
- valor aprovado/total;
- totais anuais e/ou por competencia;
- totais por UF quando apropriado;
- outras metricas especificas do sistema.

O contrato de CQ registra:

- sistema e metrica;
- periodo e recorte geografico;
- URL/definicao TabNet;
- assinatura dos parametros da tabulacao;
- instante da consulta;
- valor oficial;
- valor calculado no lake;
- diferenca absoluta e relativa;
- tolerancia;
- resultado.

A ausencia ou indisponibilidade temporaria do TabNet nao apaga uma revisao.
Ela permanece `observed_current`/pendente, enquanto a query padrao continua
apontando para o ultimo `official_current` homologado.

### 5. Silver nao precisa duplicar toda a historia

Silver e materializada, por padrao, somente para o conjunto
`official_current`.

Cada build Silver registra:

- `bronze_snapshot_id`;
- `built_at`;
- `qc_snapshot_id`;
- versao do codigo/contrato.

Silver pode ser substituida atomicamente quando uma nova revisao oficial e
homologada.

Para reproducao historica, a fonte de verdade e Raw + Bronze versionado +
manifesto/snapshot. Uma Silver historica pode ser reconstruida quando necessario.

### 6. Publicacao atomica

Uma nova revisao segue:

```text
FTP observado
  -> Raw versionado
  -> Bronze revision imutavel
  -> CQ estrutural
  -> CQ TabNet/externo
  -> official_current
  -> rebuild Silver current
  -> publicacao atomica
```

Falha em qualquer gate nao remove a versao oficial anterior.

## Consequencias

- consultas padrao permanecem atinentes ao dado oficial homologado;
- republicacoes retroativas nao destroem evidencia anterior;
- o custo de historico concentra-se nas competencias/arquivos realmente alterados;
- Silver continua simples e otimizada para consumo corrente;
- reproducao de resultados antigos fica possivel sem manter varias copias completas
  da Silver;
- diferencas temporarias FTP x TabNet ficam explicitamente registradas, em vez de
  serem tratadas como erro silencioso.
