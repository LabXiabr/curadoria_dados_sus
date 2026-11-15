# SINASC — modelo canônico

Eras:
- 1994-1995: DNR/ANT;
- 1996+: DN, com evolução de layout;
- preliminares, quando usados, separados dos definitivos.

`fact_sinasc_nascimento` conforma as eras sem apagar o schema original.
`NUMERODN` é identificador candidato quando presente; a chave física
permanece arquivo + linha até QC histórico.

Âncora temporal: data de nascimento. Residência da mãe e ocorrência são papéis
territoriais distintos. `CODESTAB` liga ao CNES pelo mês do evento quando
disponível.

Os pacotes auxiliares até 1995 e 1996+ permanecem separados e versionados.
