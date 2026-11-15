# SIA — modelo canônico

Bronze preserva cada família disseminada separadamente. PA é o principal fato
de produção; AB/ABO/ACF/AD/AM/AMP/AN/AQ/AR/ATD/BI/PS/SAD mantêm grãos próprios.

Silver:
- `fact_sia_pa`;
- `fact_sia_<subsistema>`;
- `vw_sia_evento_core` como projeção comum, sem UNION destrutiva.

Chave física: arquivo + linha. Autorização/APAC é chave de negócio candidata,
dependente de QC por subsistema/competência.

Referências: CNES da competência, SIGTAP procedimento+competência, território
as-of e TAB_SIA compatível com o período. PA possui eras 1994-2007 e 2008+;
mudanças físicas/semânticas não são uniformizadas silenciosamente.
