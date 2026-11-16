# Produtos derivados SIA: CEAF e oncologia

## Duas finalidades

O lake mantém duas interpretações separadas:

1. **canônica**: relações factuais APAC usam mesma UF + mesma competência + autorização, com PA restrita a `PA_DOCORIG IN ('P','S')`;
2. **reprodutibilidade legado**: o comportamento do ETL `PAAM/PAAQ/PAAR` é documentado, inclusive o fallback para uma tabela detalhe cujo `dense_rank` de competência é `rk_comp(PA)+1` quando não existe detalhe na mesma competência.

O fallback legado não é promovido a regra clínica/relacional do lake.

## Procedimentos

O PostgreSQL legado converteu códigos de procedimento para inteiros em vários períodos, removendo o zero inicial. Assim:

- legado `6...` corresponde canonicamente a grupo SIGTAP `06...` (CEAF/AM);
- legado prefixo `30402`–`30408` corresponde a `030402`–`030408` (AQ);
- legado prefixo `30401`/`30409` corresponde a `030401`/`030409` (AR).

Os filtros canônicos são aplicados ao código de 10 dígitos reconstruído.

## Junção de detalhes

O ETL legado executa dois enriquecimentos:

- por autorização;
- por autorização + procedimento principal (`AP_PRIPAL`).

A Silver preserva ambos como regras declaradas e registra competência PA, competência detalhe, arquivo/tabela de origem e método de pareamento.

## Identidade

`NU_CNSPCN`, `CNSPCN` e `AP_CNSPCN` são identificadores pseudonimizados da fonte. A Silver os projeta em `id_pessoa_fonte_pseudo`; a ligação longitudinal posterior usa `id_pessoa_erlen` e mantém proveniência separada.

## OMOP

CEAF pode alimentar `DRUG_EXPOSURE` somente após mapeamento farmacológico validado do procedimento. AQ/AR entram conservadoramente como `PROCEDURE_OCCURRENCE`; campos específicos de medicamento, estádio e histologia permanecem preservados até mapeamento semântico explícito.
