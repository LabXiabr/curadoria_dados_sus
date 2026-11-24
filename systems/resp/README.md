# RESP — Registro de Eventos em Saúde Pública

`resp__resp` e `resp_resp` são aliases físicos da mesma família disseminada.

O registro é person-bearing, porém contém papéis potencialmente distintos (gestante, feto/recém-nascido). A Silver não deve colapsar esses papéis em uma única pessoa sem validação.

Silver: `fact_resp_evento` preserva o registro fonte. A ponte ERLEN usa `entity_role` para indicar qual entidade está sendo ligada.

Campos territoriais, datas, resultados laboratoriais e desfechos permanecem no fato; domínios são versionados quando disponíveis.

OMOP é candidato a CONDITION/OBSERVATION/MEASUREMENT somente após validação do papel da pessoa e semântica dos campos.
