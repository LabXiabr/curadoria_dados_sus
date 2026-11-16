# Gold OMOP

## Papel no SUS Lake

OMOP é uma camada Gold derivada da Silver, nunca substitui a Bronze/Silver. A Silver preserva os códigos DATASUS, seus grãos e referências temporais; o Gold OMOP cria uma visão clínica longitudinal padronizada somente quando os requisitos de pessoa, evento e vocabulário estiverem satisfeitos.

## Identidade

`PERSON.person_id` é surrogate interno derivado de `identity.dim_pessoa_erlen`. CNSPCN/AP_CNSPCN/CNS_PAC são identificadores pseudonimizados da fonte e não são usados diretamente como `person_id`.

A ponte de identidade e o Gold OMOP são privados por padrão.

## Hospitalar

SIH RD é segmentado por cobrança. OMOP `VISIT_OCCURRENCE` representa a internação lógica, portanto os segmentos RD da mesma `n_aih` são consolidados no Gold antes de criar a visita. SP gera procedimentos vinculados a essa visita.

## Ambulatorial

SIA BPA-C permanece fora do OMOP person-level.

BPA-I, APAC e RAAS podem gerar eventos OMOP quando a pessoa estiver resolvida. O destino depende do domínio clínico do procedimento e do mapeamento de vocabulário.

## Medicamentos / CEAF

A derivação equivalente ao legado PAAM usa PA + AM e produz `gold/clinical/ceaf_medication_event`.

Quando o procedimento SIGTAP representa medicamento e existe mapeamento farmacológico validado, o destino principal é `DRUG_EXPOSURE`. Diagnósticos/medidas complementares podem gerar `CONDITION_OCCURRENCE`, `MEASUREMENT` ou `OBSERVATION`.

## Oncologia

PAAQ (PA + AQ) e PAAR (PA + AR) são produtos clínicos derivados.

- quimioterapia: `PROCEDURE_OCCURRENCE` como destino conservador;
- radioterapia: `PROCEDURE_OCCURRENCE`;
- medicamentos antineoplásicos só viram `DRUG_EXPOSURE` quando o campo e o conceito farmacológico tiverem semântica validada;
- estádio, histologia e outros atributos permanecem na Silver/Gold clínico e podem alimentar `OBSERVATION`/`MEASUREMENT` conforme contrato específico.

## Vocabulários

SIGTAP, CID e demais códigos fonte são sempre preservados em `*_source_value`. O preenchimento de `*_concept_id` exige crosswalk versionado e validado; ausência de conceito padrão não autoriza inventar mapeamento.

## Registros sem pessoa

Dados agregados, como BPA-C e PCE, permanecem em Gold analítico próprio, fora do CDM person-level.
