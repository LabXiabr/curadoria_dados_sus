# Decisões substituídas

Este arquivo mantém histórico para evitar que decisões antigas reapareçam como se fossem vigentes.

## Superfície pública paralela

### Antigo

```text
/dados/abertos/raw/
/dados/abertos/bronze/
/dados/abertos/silver/
```

como projeções públicas paralelas à lake canônica.

### Vigente

Uma única árvore persistente:

```text
/dados/abertos/suslake/{raw,bronze,silver}
```

Publicação seletiva ocorre dentro da própria camada, por exemplo `cnes_reference` ou `raw/public`.

## /files/suslake totalmente privado

### Antigo

Houve fase em que se propôs bloquear integralmente `/files/suslake/` e publicar somente raízes paralelas.

### Vigente

`/files/suslake/` é default-deny com allowlist explícita. Subconjuntos autorizados podem ser públicos dentro da árvore.

## PostgreSQL como Bronze definitiva

### Antigo

PostgreSQL era tratado em alguns fluxos como base Bronze persistente/serving.

### Vigente

Para o SUS Lake histórico, PostgreSQL existente é fonte física rápida de migração. Bronze canônica é Parquet reconstruído conforme semântica DATASUS.

PostgreSQL só pode ser aposentado após os CQs definidos.

## qt_registro_sql como contagem de verdade

### Antigo

Metadado usado em alguns inventários como número de registros.

### Vigente

É metadado potencialmente obsoleto. Contagem autoritativa é `count(*)` real ou CQ equivalente.

## PA + BI + PS como produção somável

### Antigo

Em experimentações iniciais houve risco de somar famílias de SIA.

### Vigente

PA é fato canônico de produção; demais famílias têm papéis próprios e não são somadas sem contrato explícito.

## BI como filho APAC

### Antigo

BI chegou a ser tratado genericamente junto a famílias APAC.

### Vigente

BI = BPA-I e não é filho APAC.

## +/-3 meses como relação APAC

### Antigo

A janela de recuperação de CNSPCN poderia ser confundida com relacionamento factual.

### Vigente

+/-3 competências é apenas enriquecimento de identificador pseudonimizado. Relação APAC usa mesma competência.

## AIH/segmento RD diretamente como OMOP Visit

### Antigo

Foi formulado que uma AIH lógica gera uma visita OMOP sem explicitar o gate de identidade.

### Vigente

AIH lógica é candidata a visita. `VISIT_OCCURRENCE` só é criada após ERLEN resolver `person_id`. Segmentos RD nunca são visitas independentes apenas por serem segmentos.

## CNSPCN como CNS nominal

### Antigo

Nomenclaturas legadas podem sugerir CNS real.

### Vigente

CNSPCN e variações são identificadores pseudonimizados de fonte. O contrato evita rotulá-los como CNS nominal/reversível.

## PID sem namespace/proveniência

### Antigo

Alguns produtos legados reutilizam `nu_usuario` com significados dependentes de `tp_nu_usuario`.

### Vigente

O legado é preservado, mas a identidade canônica é namespaceada/opaca em `id_pessoa_erlen` e a proveniência fica separada.

## ETL definitiva baseada apenas no PostgreSQL

### Antigo

Migração PSQL -> Parquet foi considerada suficiente como pipeline futuro.

### Vigente

PSQL -> Parquet é aceleração histórica. A fonte/reconstrução definitiva continua vinculada aos artefatos DATASUS e ETL própria DBC/Wine, com versionamento de republicações.
