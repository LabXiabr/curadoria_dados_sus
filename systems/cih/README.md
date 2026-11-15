# CIH — modelo canônico

CIH é a era anterior da comunicação hospitalar disseminada mensalmente.
`fact_cih_cr` preserva competência, CNES/CNPJ, residência, município de
internação, procedimento, datas, diagnósticos e desfecho.

A chave física é arquivo + linha; não inventar identificador de internação
quando a fonte não o fornece.

A integração longitudinal com CIHA é feita por
`vw_cih_ciha_evento_core`, preservando `source_system` e schema de origem.
O material canônico observa CR em 200801-201104.
