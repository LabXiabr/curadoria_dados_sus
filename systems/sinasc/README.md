# SINASC — modelo canônico

Eras:
- 1994-1995: DNR/ANT;
- 1996+: DN, com evolução de layout;
- preliminares, quando usados, separados dos definitivos.

`fact_sinasc_nascimento` conforma as eras sem apagar o schema original. `NUMERODN` é identificador candidato do registro quando presente; a chave física permanece arquivo + linha até CQ histórico.

O registro é person-bearing para o recém-nascido. A identidade da mãe e a identidade do recém-nascido são papéis distintos e nunca são unificadas por inferência.

A ligação ERLEN do recém-nascido só é materializada quando a política específica de nascimento estiver validada. Dados maternos permanecem atributos/papel relacionado, não `person_id` do recém-nascido.

Âncora temporal: data de nascimento. Residência da mãe e ocorrência são papéis territoriais distintos. `CODESTAB` liga ao CNES pelo mês do evento quando disponível.

Os pacotes auxiliares até 1995 e 1996+ permanecem separados e versionados.

No Gold OMOP, o nascimento pode preencher atributos de `PERSON` e gerar `OBSERVATION`/`MEASUREMENT` somente após identidade do recém-nascido resolvida.
