# PCE — modelo canônico

Os schemas observados `pce__pce`, `pce_pce` e `pce_br` são variantes físicas do Programa de Controle da Esquistossomose.

O inventário observado contém predominantemente contagens (`qt_*`) por competência e território/localidade. Portanto o contrato atual é agregado, não person-level.

Bronze preserva todos os atributos e tipos de origem. Silver proposta: `fact_pce_monitoramento`, com grão territorial-temporal declarado pela combinação de competência e identificadores territoriais disponíveis.

PCE não é carregado para OMOP person-level. Indicadores permanecem Gold analítico.
