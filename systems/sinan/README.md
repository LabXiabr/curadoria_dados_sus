# SINAN — modelo canônico

SINAN é um conjunto de famílias por agravo com schemas heterogêneos. Não criar
uma tabela física única com milhares de colunas esparsas.

Silver:
- `fact_sinan_<agravo>`: fato específico de cada família;
- `vw_sinan_notificacao_core`: projeção comum;
- extensões específicas permanecem no fato do agravo.

O núcleo comum observado inclui data/ano/município/UF de notificação, agravo,
unidade notificadora, sexo, idade, residência e, quando presentes, início de
sintomas, investigação, classificação, evolução e encerramento.

Não presumir chave natural global no disseminável. Chave física: arquivo +
linha. Indicadores de duplicidade continuam atributos.

`TAB_SINANNET.zip` e `TAB_SINANONLINE.zip` são fontes distintas e
versionadas. Domínio específico usa agravo + campo + código na identidade.
