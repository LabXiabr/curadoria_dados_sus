# Painel Oncologia — fonte derivada oficial

Os schemas `painel_oncologia__po_br` e `painel_oncologia_po` são tratados como variantes físicas da mesma família PO.

O grão observado é person-bearing, com identificador pseudonimizado `CNS_PAC`, datas de diagnóstico/tratamento, CNES de diagnóstico/tratamento, município/UF de residência e atendimento, diagnóstico, estádio e tratamento.

`CNS_PAC` é projetado na Silver como `id_pessoa_fonte_pseudo` e pode alimentar o ERLEN_PID. Não é tratado como CNS nominal.

A fonte é preservada separadamente das derivações SIA AQ/AR; concordância entre Painel Oncologia e SIA é CQ/integração, não deduplicação automática.

Silver: `fact_painel_oncologia`. Gold OMOP: somente após identidade e mapeamento semântico validados.
