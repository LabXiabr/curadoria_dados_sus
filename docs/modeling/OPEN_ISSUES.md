# Pendências e gates abertos

Status: consolidado em 2026-11-16

Este arquivo registra pendências arquiteturais/semânticas. Estado minuto a minuto de jobs fica em `suslabx/state`, não aqui.

## P0 — bloquear promoção/merge se falhar

### SIH histórico atual

- aguardar `OVERNIGHT_DONE`;
- executar `ops/qc-sih-source-staging-live.py`;
- validar PostgreSQL bureta/pipeta ↔ staging Parquet;
- executar dry-run de `ops/sih-promote-staging-bronze.py`;
- somente então mesclar/promover;
- depois validar RD/SP e construir Silver.

### Working tree local da bureta

O checkout principal contém commit e alterações locais anteriores ao PR.
Não fazer reset/pull destrutivo enquanto o overnight depender desse checkout.
Após encerramento: reconciliar alterações locais com a branch/PR.

## P1 — modelagem ainda incompleta

### SIH

- validar historicamente unicidade de `n_aih + dt_saida` e `remessa + sequencia` em toda a série;
- definir semântica completa de CH/CM;
- validar RJ/ER para identidade e eventual Gold;
- definir materialização de `vw_sih_aih_logica`.

### ERLEN_PID

- consolidar contrato definitivo de namespaces/IDs;
- integrar convenção histórica de `tp_nu_usuario`;
- formalizar ponte para fatos além de PAAM/PAAQ/PAAR;
- revisar identificadores 99 historicamente imputados;
- manter processamento por blocos exclusivos, checkpoint e retomada;
- iniciar com 4 workers/1 CPU por worker em evolução paralela; considerar 6 apenas após CQ de RAM/I/O.

### OMOP

- materializar Gold apenas depois de pessoa/visita resolvida;
- versionar crosswalks de SIGTAP/CID para vocabulários padrão;
- validar domínios de CEAF, oncologia, vacinação e SINAN;
- definir tratamento de source_concept_id/concept_id quando não houver conceito padrão.

## P1 — referências temporais

### Território

- memória histórica completa ainda pendente;
- preservar join por município + competência/data e último snapshot homologado aplicável;
- concluir RA-DF quando necessário.

### CNES

- manter cobertura histórica desde 201706 como baseline oficial atual;
- revisar schemas DBC históricos quando forem necessários para períodos anteriores;
- preservar distinção CO_UNIDADE/CO_CNES.

### SIGTAP

- manter temporalidade por competência;
- completar domínios/relacionamentos ainda ambíguos de DEF/CNV/DBF sem inferir tipo/largura apenas pelo layout TabNet.

## P1 — SIA

- escalar reconstrução Bronze completa;
- validar PA_DOCORIG x instrumento SIGTAP historicamente;
- validar relações PA/APAC por subsistema e competência;
- separar claramente regra canônica de CEAF/ONCO da compatibilidade com ETL legada;
- manter recuperação CNSPCN com proveniência e sem conflito.

## P2 — demais sistemas

- PNI CPNI/DPNI: validar grão e person-level antes de OMOP;
- RESP: distinguir papéis gestante/feto/RN;
- Painel Oncologia: validar semântica e sobreposição com SIA AQ/AR;
- PCE: manter como agregado, salvo nova evidência;
- SINAN: mapear agravo por agravo para Gold;
- SINASC: validar política ERLEN específica para RN e mãe;
- SISCAN, SISPRENATAL e ESUSNOTIFICA: curadoria antes de inferir identidade/OMOP.

## P2 — publicação/runtime

- remover definitivamente raízes antigas vazias `/dados/abertos/raw|bronze|silver` após CQ;
- migrar `state/staging/work/logs` para runtime fora de `suslabx` depois que nenhuma execução depender dos caminhos atuais;
- decidir destino de `parquet_catalog.tsv` após identificar produtores/consumidores;
- revisar `benchmark` versus `benchmark_mylena` sem tocar no diretório da Mylena sem necessidade.

## P2 — aposentadoria PostgreSQL

Só considerar DROP/aposentadoria após:

- Raw/versionamento disponível;
- Bronze Parquet homologada;
- contagens fonte = Parquet;
- CQ lógico;
- CQ TabNet/externo quando aplicável;
- cobertura temporal confirmada;
- estratégia de republicação definida.
