# Identidade longitudinal — ERLEN_PID

## Objetivo

A camada de identidade liga registros de diferentes sistemas sem alterar o grão nem os atributos originais dos fatos Silver.

Dois conceitos são distintos:

1. **identificador pseudonimizado da fonte** — valores como CNSPCN, AP_CNSPCN, NU_CNSPCN, CNS_PAC e variações. Eles são tratados como identificadores pseudonimizados, nunca como CNS nominal/reversível;
2. **identificador longitudinal ERLEN** — chave pseudonimizada produzida pelo ERLEN_PID para representar a melhor hipótese de mesma pessoa entre registros.

## Objetos privados da Silver

`dim_pessoa_erlen`: uma linha por identidade longitudinal ERLEN vigente.

`bridge_pessoa_registro`: liga uma linha/fato de origem a `id_pessoa_erlen`, preservando sistema/schema/tabela/arquivo/registro de origem, identificador pseudonimizado da fonte, método/regra, execução, confiança, erro estimado e estado da atribuição.

Esses objetos são privados por padrão. A publicação de fatos não implica publicação da ponte de identidade.

## Fontes com identificador pseudonimizado explícito

SIA e Painel Oncologia podem carregar identificador pseudonimizado em campos como CNSPCN, AP_CNSPCN, NU_CNSPCN e CNS_PAC.

O valor original é preservado na Bronze. Na Silver, a projeção canônica é `id_pessoa_fonte_pseudo`.

## Fontes sem identificador explícito confiável

SIM, SINAN, SIH, CIH/CIHA e outras fontes podem participar de resolução determinística/probabilística por características sociodemográficas e do contato assistencial. A atribuição nunca sobrescreve o registro original.

Em SIM, o registro canônico de DO representa um óbito/pessoa no grão da fonte. Em SINAN, uma linha representa uma notificação e é person-bearing; várias notificações podem corresponder à mesma pessoa. Portanto, 'uma linha = uma pessoa' só é assumido onde o contrato específico do schema/agravo tiver sido validado.

## Gold / OMOP

`OMOP.PERSON.person_id` é um surrogate interno derivado de `id_pessoa_erlen`, e não o CNSPCN da fonte.

Registros sem identidade longitudinal aceitável permanecem disponíveis na Silver, mas não são forçados para uma pessoa OMOP fictícia. Políticas de episódio isolado devem ser declaradas pelo ERLEN e carregadas com proveniência.
