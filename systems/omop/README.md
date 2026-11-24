# Gold OMOP

## Papel no SUSLabX

OMOP é uma camada Gold derivada da Silver, nunca substitui a Bronze/Silver. A Silver preserva os códigos DATASUS, seus grãos e referências temporais; o Gold OMOP cria uma visão clínica longitudinal padronizada somente quando os requisitos de pessoa, evento e vocabulário estiverem satisfeitos.

## Identidade

`PERSON.person_id` é surrogate interno derivado de `identity.dim_pessoa_erlen`. CNSPCN/AP_CNSPCN/CNS_PAC são identificadores pseudonimizados da fonte e não são usados diretamente como `person_id`.

A ponte de identidade e o Gold OMOP são privados por padrão.

## Hospitalar

SIH RD é segmentado por cobrança. Antes do ERLEN_PID, a Silver preserva os segmentos RD e materializa uma **AIH lógica candidata a visita**, sem criar ainda `VISIT_OCCURRENCE`, porque OMOP exige `person_id`.

O ERLEN_PID liga AIH/SIH, SIM e demais fatos person-bearing a `id_pessoa_erlen`. Somente depois dessa resolução a AIH lógica pode gerar `VISIT_OCCURRENCE`. Assim, vários segmentos RD da mesma `n_aih` continuam pertencendo à mesma internação lógica, e várias internações da mesma pessoa passam a compartilhar o mesmo `person_id` sem serem colapsadas em uma única visita.

SP gera `PROCEDURE_OCCURRENCE` somente depois que o segmento RD pai estiver ligado à AIH lógica e esta estiver ligada à pessoa.

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

## PCDT e enriquecimento longitudinal

A camada Gold/ML pode enriquecer coortes PCDT usando eventos longitudinais resolvidos pelo ERLEN_PID. SIH fornece internações, diagnósticos, procedimentos e desfechos hospitalares; SIM fornece óbito e causas. Esses sinais são atributos/eventos para modelos e regras PCDT, não chaves de identidade. A identidade é resolvida antes da projeção OMOP e preserva proveniência/confiança.
