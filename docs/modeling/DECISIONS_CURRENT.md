# Decisões vigentes

Status: fonte normativa consolidada  
Data: 2026-11-16

## 1. Arquitetura física

A árvore persistente canônica é:

```text
/dados/abertos/suslabx/
├── raw/
├── bronze/
└── silver/
```

`state`, `staging`, `work` e `logs` são runtime e devem sair da árvore persistente após as execuções que ainda dependem dos caminhos atuais.

Não criar uma camada física `gold/` dentro de `suslabx` neste momento. Gold é camada lógica/derivada e será materializada conforme o produto exigir.

## 2. Fonte e migração

- Não usar microdatasus.
- A ETL própria baseada em DBC/Wine permanece referência de reconstrução da fonte.
- O PostgreSQL `bdsus` existente é usado como fonte física rápida para a migração histórica.
- PostgreSQL não é autoridade semântica sobre tipos/larguras DATASUS.
- Antes de aposentar dados PostgreSQL: Raw/versionamento + Bronze Parquet + CQ de linhas + CQ externo/TabNet quando aplicável.
- `qt_registro_sql` de metadados não é contagem autoritativa; usar `count(*)` real quando necessário.

Split canônico atual:

- competência < 202000: `bureta`;
- competência >= 202000: `pipeta`.

### Séries históricas / repositórios

A unidade de repositório lógico segue a separação publicada no FTP DATASUS, e não apenas o nome do sistema.

Regra geral:

- pastas/séries FTP distintas permanecem repositórios físicos distintos em Raw, Bronze e Silver;
- não concatenar eras históricas em um mesmo diretório Parquet;
- eventual continuidade temporal entre eras é uma view/união lógica explícita, com proveniência da série;
- o catálogo de datasets deve registrar cada série separadamente.

Aplicação atual:

- SIA `199407_200712` separado de SIA `200801_`;
- SIH `199201_200712` separado de SIH `200801_`.

A mesma regra deve ser aplicada aos demais sistemas quando o FTP oficial publicar séries/pastas históricas distintas.

## 3. Camadas

### Raw

Artefato original/oficial preservado com hash e histórico de republicação.

### Staging

Fotografia física intermediária. Exemplo atual: PostgreSQL -> Parquet SIH.
Staging não é Bronze definitiva.

### Bronze

Representação lógica fiel à fonte:

- preserva todos os campos de origem;
- preserva proveniência física;
- reconstrói larguras/zeros à esquerda por contrato DATASUS;
- não introduz ERLEN_PID;
- multipartições físicas formam uma partição lógica por `UNION ALL`.

### Silver

Camada semântica/temporal:

- nomes canônicos;
- chaves e relações;
- CNES/SIGTAP/território temporais;
- enriquecimentos explicitamente versionados;
- identidade longitudinal em objetos privados separados;
- não destrói o grão original sem declaração explícita.

## 4. Metadados

Todo campo observado é preservado na Bronze mesmo sem semântica conhecida.

Metadados são separados em:

1. observação física;
2. layout/documentação oficial;
3. mapeamento fonte -> canônico;
4. dicionário canônico com rótulo, descrição, papel semântico, referência, sensibilidade e possível domínio OMOP.

FKs em Parquet são lógicas e validadas por CQ, não constraints físicas.

## 5. Referências temporais

CNES, SIGTAP, território e demais domínios são referências temporais de primeira classe.

Regra geral: resolver o fato contra a referência aplicável à competência/data do evento. Não aplicar silenciosamente a dimensão corrente ao passado.

Memória histórica territorial completa pode ser construída depois dos fatos, desde que os fatos preservem chaves e âncoras temporais suficientes.

## 6. CNES

- `CO_UNIDADE`: chave relacional interna opaca;
- `CO_CNES`: identificador público CNES;
- território separado por `co_territorio_key`;
- hard gates de integridade entre fatos CNES, estabelecimento e território;
- CNES canônico completo privado por padrão;
- projeções públicas seletivas dentro da própria árvore:
  - `bronze/cnes_reference/`;
  - `silver/cnes_reference/`.

## 7. SIA

PA é o fato canônico de produção ambulatorial; BI/PS e demais famílias não são somadas indiscriminadamente à PA.

`PA_DOCORIG`:

- C = BPA-C;
- I = BPA-I;
- P = APAC principal;
- S = APAC secundária;
- A = RAAS AD;
- B = RAAS Psicossocial.

BPA-C é agregado e não deve ser forçado a pessoa/evento.

BPA-I é individualizado e não é filho APAC.

Relações APAC canônicas:

- PA somente P/S;
- mesma UF;
- mesma competência;
- mesma autorização;
- relação potencialmente N:M.

`0000000000000` pode ser estruturalmente válido em produção não autorizada e não deve ser tratado universalmente como erro.

### CNSPCN

`CNSPCN`, `NU_CNSPCN`, `AP_CNSPCN`, `CNS_PAC` e variações são identificadores pseudonimizados da fonte, não CNS nominal.

Em PA, `nu_cnspcn` pode ser enriquecimento local e não campo nativo da Bronze.

A recuperação local de PA usa:

- mesma UF;
- mesma autorização;
- janela até +/-3 competências;
- competência mais próxima;
- empate só é imputado quando os candidatos concordam no mesmo pseudônimo;
- proveniência obrigatória.

Essa janela não redefine o relacionamento factual APAC, que continua mesma competência.

## 8. CEAF e oncologia

Produtos derivados compatíveis com ETL histórica:

- PAAM = PA + AM -> CEAF;
- PAAQ = PA + AQ -> oncologia/quimioterapia;
- PAAR = PA + AR -> oncologia/radioterapia.

No contrato canônico, procedimentos são texto de 10 dígitos:

- CEAF: grupo `06`;
- AQ: `030402` a `030408`;
- AR: `030401` e `030409`.

O fallback temporal legado de `dense_rank + 1` é mantido para reprodutibilidade, mas não é regra relacional canônica.

CEAF pode alimentar OMOP `DRUG_EXPOSURE` somente após mapeamento farmacológico validado.

AQ/AR entram conservadoramente como `PROCEDURE_OCCURRENCE`; campos específicos de medicamentos/estádio/histologia só mudam de domínio após validação.

## 9. SIH

Grãos:

- AIH lógica: `n_aih`;
- segmento RD: `n_aih + dt_saida`;
- chave técnica do segmento: `remessa + sequencia`;
- SP: ato profissional ligado a exatamente um segmento RD por `sp_naih + sp_dtsaida`.

RD segmento -> SP é 1:N.

A AIH lógica é uma **candidata a visita**, mas não é OMOP antes do ERLEN_PID.

Ordem:

1. conformar RD/SP na Silver;
2. derivar AIH lógica;
3. ERLEN_PID resolver `id_pessoa_erlen`;
4. somente então criar OMOP `VISIT_OCCURRENCE`;
5. SP pode criar `PROCEDURE_OCCURRENCE` ligado à pessoa/visita resolvida.

Internações diferentes da mesma pessoa compartilham `person_id`, mas não são colapsadas em uma única visita.

## 10. Identidade longitudinal / ERLEN_PID

Identidade é separada do fato.

- identificador pseudonimizado da fonte: `id_pessoa_fonte_pseudo`;
- identidade longitudinal canônica: `id_pessoa_erlen`;
- ligação registro -> pessoa: `bridge_pessoa_registro`;
- chave técnica do registro: `id_registro_fonte`.

Nunca sobrescrever identificador original.

ERLEN_PID:

- record linkage/entity resolution, não classificação multiclasse;
- precisão > recall;
- incertos podem permanecer sem vínculo;
- processamento por blocos exclusivos;
- checkpoints e retomada;
- reaproveitamento incremental de identidades;
- PID opaco, sem concatenar atributos;
- proveniência, execução, regra, confiança e erro preservados.

Convenção operacional histórica de proveniência deve ser preservada onde aplicável:

- vazio = CNS original de 15 dígitos nunca alterado;
- C = CNS real recuperado deterministicamente;
- M = CNS real atribuído por modelo;
- G = PID de grupo longitudinal;
- S = PID de episódio isolado multi-registro;
- U = PID para demais casos conforme contrato vigente do ERLEN.

A codificação exata e namespace definitivo permanecem responsabilidade do contrato ERLEN, não do fato clínico.

## 11. SIM, SINAN e SINASC

SIM DO: registro de óbito person-bearing. O registro não é por si só identidade longitudinal.

SINAN: uma linha é uma notificação person-bearing; uma pessoa pode ter várias notificações e agravos.

SINASC: registro person-bearing do recém-nascido; identidade materna e identidade do RN são papéis distintos.

Todos podem ser ligados posteriormente pelo ERLEN conforme atributos disponíveis e política específica.

## 12. PCDT / ML

SIA/CEAF/ONCO, SIH e SIM podem enriquecer coortes PCDT e modelos longitudinais.

SIH fornece internações, diagnósticos, procedimentos e desfechos hospitalares.
SIM fornece óbito e causas.

Esses eventos são sinais clínicos/assistenciais para regras/modelos, não chaves de identidade.

## 13. OMOP

OMOP é Gold derivado da Silver após identidade suficiente.

- `PERSON.person_id`: surrogate interno derivado de `id_pessoa_erlen`;
- SIH AIH lógica resolvida -> `VISIT_OCCURRENCE`;
- SP -> `PROCEDURE_OCCURRENCE`;
- CEAF validado -> `DRUG_EXPOSURE`;
- SIM -> `DEATH`;
- SINAN -> `CONDITION_OCCURRENCE`/observações conforme mapeamento;
- CNES -> `CARE_SITE`/`PROVIDER`;
- território -> `LOCATION`.

Sempre preservar `*_source_value`. `concept_id` padrão exige crosswalk versionado; não inventar mapeamento.

Dados agregados não são forçados ao OMOP person-level.

## 14. Publicação

A URL pública é sob `/files/suslabx/`.

A árvore é default-deny; apenas datasets autorizados são liberados.

Raw seletivo pode ser projetado em `suslabx/raw/public/`.

Não recriar raízes permanentes paralelas `/dados/abertos/raw`, `bronze` ou `silver`.

## 15. Regra de merge/promocão

Alteração de modelagem só é promovida quando os CQs pertinentes passam.

Para a migração SIH atual:

1. overnight termina;
2. CQ PostgreSQL real ↔ staging Parquet;
3. dry-run staging -> Bronze;
4. merge do PR;
5. promoção efetiva;
6. Silver;
7. CQ semântico/relacional;
8. identidade/Gold/publicação conforme gate específico.
