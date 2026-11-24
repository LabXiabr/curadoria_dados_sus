# SINAN — modelo canônico

SINAN é um conjunto de famílias por agravo com schemas heterogêneos. Não criar uma tabela física única com milhares de colunas esparsas.

Há dois estados de fonte independentes:
- `FINAIS`: dados consolidados por agravo;
- `PRELIM`: dados preliminares, preservados em namespace próprio e nunca usados para sobrescrever FINAIS.

Silver:
- `fact_sinan_<agravo>` para FINAIS;
- `fact_sinan_prelim_<agravo>` para PRELIM quando necessário;
- `vw_sinan_notificacao_core` como projeção comum;
- extensões específicas permanecem no fato do agravo.

O grão é uma notificação/registro, não uma pessoa longitudinal. O registro é person-bearing e pode representar uma pessoa naquele contato/notificação; a mesma pessoa pode aparecer em múltiplas notificações e agravos.

A ligação longitudinal é feita pelo ERLEN_PID em `identity.bridge_pessoa_registro`, com atributos sociodemográficos e do contato assistencial, sem alterar o fato original.

O núcleo comum observado inclui data/ano/município/UF de notificação, agravo, unidade notificadora, sexo, idade, residência e, quando presentes, início de sintomas, investigação, classificação, evolução e encerramento.

Não presumir chave natural global no disseminável. Chave física: arquivo + linha. Indicadores de duplicidade continuam atributos.

`TAB_SINANNET.zip` e `TAB_SINANONLINE.zip` são fontes distintas e versionadas. Domínio específico usa agravo + campo + código na identidade.

No Gold OMOP, uma notificação pode alimentar `CONDITION_OCCURRENCE` e atributos específicos podem alimentar `OBSERVATION`/`MEASUREMENT`, somente com pessoa resolvida e mapeamento semântico do agravo.
