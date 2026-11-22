# SUSLake — referências, relacionamentos e QC

## Fonte PostgreSQL canônica

- `bureta/bdsus`: competências anteriores a 2020.
- `pipeta/bdsus`: competências de 2020 em diante.
- Sobreposições entre hosts não são consideradas fontes equivalentes.

## Tabelas multipartidas

Um DBC físico permanece uma unidade de proveniência.

Quando um subsistema/UF/competência possui múltiplos DBCs, a relação
lógica é o `UNION ALL` das partes.

Exemplo validado:

- `PAMG2604a.dbc`
- `PAMG2604b.dbc`
- `PAMG2604c.dbc`

## SIA PA

`PA_DOCORIG` identifica o instrumento efetivamente usado.

- C: BPA-C
- I: BPA-I
- P: APAC principal
- S: APAC associada/secundária
- A: RAAS atenção domiciliar
- B: RAAS atenção psicossocial

O SIGTAP temporal define os instrumentos permitidos para o procedimento.

APAC especializada relaciona-se a PA apenas para
`PA_DOCORIG IN ('P','S')`, usando autorização + UF + competência.

BI não é tratado como tabela APAC. A relação BI <-> PA/I permanece
pendente de definição de chave estrutural.

`nu_cnspcn` é enriquecimento local e não campo original SIA/PA.

## Representação física PostgreSQL

Algumas cargas PostgreSQL perderam zeros à esquerda de identificadores.

Exemplo:

- PostgreSQL: `301010064`
- DATASUS/SIGTAP: `0301010064`

A bronze definitiva deverá restaurar tipos/formatos lógicos segundo o
layout original DATASUS.

## SIH RD -> SP

`n_aih` identifica a AIH lógica, mas uma internação prolongada pode
produzir múltiplos registros RD.

Chaves validadas:

- AIH lógica: `n_aih`
- segmento semântico RD: `n_aih + dt_saida`
- segmento técnico: `remessa + sequencia`

Relacionamento:

- RD segmento -> SP = 1:N

Validações:

- AC/201204
- MG/202604

Em MG/202604:

- 130.769 segmentos RD
- 1.980.823 registros SP
- zero SP sem segmento RD
- zero divergências de internação, CNES, sequência ou remessa

## Metadados de carga

`qt_registro_sql` é informativo e não deve ser usado como autoridade
sobre tabela vazia. A existência é determinada por `st_existe_sql` e a
completude por contagem real.
