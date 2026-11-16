# SIM — modelo canônico

DORES/DO é a série canônica geral de declarações de óbito. DOF/DOE/DOI/DOM e outras famílias especializadas são preservadas na Bronze, mas não são somadas à DO sem análise de sobreposição.

Silver:
- `fact_sim_obito` a partir de DO;
- views/subconjuntos fetal, infantil, materno e causas externas;
- preliminares em namespace separado, nunca sobrescrevendo definitivos.

O grão de `fact_sim_obito` é uma declaração/registro de óbito e, no contrato canônico, representa uma pessoa falecida naquele evento. Isso não transforma o número da declaração em identificador longitudinal.

A identidade longitudinal é atribuída em `identity.bridge_pessoa_registro` pelo ERLEN_PID, usando apenas atributos permitidos e preservando regra, execução, confiança e erro estimado. O fato SIM original não é sobrescrito.

Âncora temporal: `dt_obito`. Residência e ocorrência são papéis territoriais distintos. `codestab` liga ao CNES pelo mês do evento quando aplicável.

No Gold OMOP, após identidade resolvida, o evento alimenta `DEATH`; a causa básica permanece como source value e só recebe concept_id quando houver crosswalk versionado.

Domínios CID-10/CID-9 e CNV de tabulação permanecem versionados.
