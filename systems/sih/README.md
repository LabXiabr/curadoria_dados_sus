# SIH — modelo canônico

## Princípios

A Bronze preserva uma representação lógica fiel ao DATASUS por fonte física.
Quando uma partição lógica `sistema + subsistema + UF + competência` vier em
mais de um DBC/tabela física, a partição lógica é a união `UNION ALL` dessas
fontes; o particionamento físico não altera o grão semântico.

RD, SP, RJ e ER possuem grãos distintos. CH e CM permanecem
`metadata_only_needs_curation` até que sua semântica seja documentada.

## RD — AIH e segmento

`N_AIH` identifica a AIH lógica, mas não é chave de linha universal.

Uma AIH pode produzir vários registros RD, inclusive em permanências prolongadas.
O grão de `fact_sih_rd` é **um segmento RD**.

Chaves validadas:

- AIH lógica: `n_aih`;
- segmento, chave semântica: `n_aih + dt_saida`;
- segmento, chave técnica da fonte: `remessa + sequencia`.

A unicidade das duas chaves de segmento é avaliada no contexto
`UF + competência`.

## SP — atos profissionais

O grão de `fact_sih_sp` é **um ato/registro profissional**.

Cada registro SP deve resolver exatamente um segmento RD por:

`sp_naih + sp_dtsaida -> n_aih + dt_saida`

A chave técnica de segmento em SP também é `remessa + sequencia`.

O relacionamento validado é:

`RD_segment 1:N SP_professional_act`

Em AC/201204 e MG/202604 houve correspondência integral dos registros SP aos
segmentos RD e consistência de data de internação, CNES, remessa e sequência.

## Silver

- `fact_sih_rd`: um segmento RD;
- `fact_sih_sp`: um ato/registro profissional;
- `fact_sih_rj`: uma linha RJ, até modelagem adicional;
- `fact_sih_er`: uma linha ER, até modelagem adicional;
- `vw_sih_evento_core`: projeção comum, sem destruir os grãos.

A Silver preserva os campos de origem e acrescenta chaves/atributos resolvidos.
Referências CNES, SIGTAP, território e TAB_SIH são temporais e devem corresponder
à competência/data aplicável; dimensões correntes não são aplicadas
retroativamente de forma silenciosa.

## Migração PostgreSQL

A fotografia PostgreSQL -> Parquet é staging, não Bronze definitiva.
Antes da promoção, campos DATASUS de largura fixa que perderam zeros à esquerda
por tipagem PostgreSQL são reconstruídos conforme contrato explícito em
`systems/sih/fixed_width_fields.tsv`.

A contagem PostgreSQL == Parquet é necessária, mas não suficiente para homologar
a Bronze.
