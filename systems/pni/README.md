# PNI — contrato de fonte

A ETL legado reconhece `PNI/DADOS/` e gera schemas `pni_<subsistema>`. Foram declarados `pni_cpni` e `pni_dpni`, mas eles não aparecem nos snapshots `information_schema` de bureta/pipeta fornecidos em 2026-11-16.

Por isso a modelagem preserva a fonte e a nomenclatura, mas não presume grão person-level.

Antes da Silver devem ser validados:
- grão de CPNI/DPNI;
- presença de identificador pseudonimizado de pessoa;
- código de imunobiológico, dose, data, estabelecimento e território;
- sobreposição entre subsistemas.

Somente uma fonte person-level validada poderá alimentar OMOP `DRUG_EXPOSURE` para vacinação.
