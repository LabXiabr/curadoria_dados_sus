# Cobertura de schemas BDSUS — revisão 2026-11-16

Fontes utilizadas: snapshots de `information_schema.columns` fornecidos para bureta e pipeta.

Resumo observado:

- 216 schemas distintos no total, incluindo catálogos PostgreSQL e schemas locais/derivados;
- 193 schemas com prefixos de fontes disseminadas/assistenciais relevantes;
- 193/193 cobertos pelos padrões de `catalog/source_schema_contract.tsv`;
- 0 schemas de fonte observados sem contrato;
- `pni_cpni` e `pni_dpni` foram declarados como fontes esperadas e já possuem contrato, mas não estavam presentes nos dois snapshots fornecidos.

Famílias cobertas: CIH, CIHA, CNES DBC histórico, Painel Oncologia, PCE, PNI, RESP, SIA (incluindo histórico e AN/SAD), SIH (incluindo 1992-2007 e CH/CM/ER), SIM, SINAN FINAIS/PRELIM, SINASC, SISCAN, SISPRENATAL e ESUSNOTIFICA.

Aliases físicos entre bureta e pipeta são tratados como variantes da mesma fonte (por exemplo `simdofet__*` vs `sim_dofet_*`, `sinanfinais__*` vs `sinan_finais_*`, `resp__resp` vs `resp_resp`).

O CQ automatizado de cobertura deve falhar se surgir schema novo que não esteja classificado como fonte ou como schema local/derivado.
