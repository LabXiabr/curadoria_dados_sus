# SIA — modelo canônico

## Séries históricas

SIA mantém repositórios físicos distintos conforme a organização oficial do FTP:

- `199407_200712`;
- `200801_`.

Raw, Bronze e Silver preservam essa separação. Uma análise longitudinal que atravesse 2007/2008 deve usar união lógica explícita entre as séries, sem mover os arquivos para um único repositório.

## Bronze e partições físicas

A Bronze preserva cada família disseminada separadamente. Uma partição lógica é
`sistema + subsistema + UF + competência` e corresponde ao `UNION ALL` de
todas as fontes físicas da mesma partição. Sufixos como `a/b/c` ou `_1/_2`
não criam fatos semânticos distintos.

PA é o principal fato de produção. AB/ABO/ACF/AD/AM/AMP/AN/AQ/AR/ATD/BI/PS/SAD
mantêm grãos próprios.

## PA_DOCORIG

`PA_DOCORIG` representa o instrumento efetivamente utilizado:

- `C`: BPA-C;
- `I`: BPA-I;
- `P`: APAC principal;
- `S`: APAC secundária;
- `A`: RAAS Atenção Domiciliar;
- `B`: RAAS Psicossocial.

O SIGTAP informa os instrumentos permitidos na competência; ele é usado como
controle de compatibilidade e não para substituir `PA_DOCORIG`.

BPA-C é produção agregada e não deve ser forçada a grão pessoa/evento.
BPA-I é produção individualizada e **não é filho APAC**.

## APAC

Somente PA com `PA_DOCORIG IN ('P','S')` participa do relacionamento com as
famílias APAC.

A entidade de ligação usa:

`UF + competência + autorização`

A relação é potencialmente N:M porque várias linhas PA e várias linhas de
detalhe podem compartilhar a mesma autorização. Não se presume 1:1.

A janela +/-3 meses é exclusiva do enriquecimento `nu_cnspcn`; não redefine
o relacionamento factual APAC, que usa a mesma competência.

## nu_cnspcn

`nu_cnspcn` em PA é enriquecimento local, não campo nativo da Bronze PA.
A Bronze nativa o exclui quando a origem é PostgreSQL enriquecido.

Na Silver, a recuperação usa mesma UF + mesma autorização e procura até três
meses antes/depois. A competência de menor distância vence; em empate só há
imputação quando os candidatos concordam no mesmo CNS. A proveniência deve
registrar subsistema, competência de origem, distância e método.

## Silver

- `fact_sia_pa`;
- `fact_sia_<subsistema>`;
- views semânticas de PA para BPA-C, BPA-I, APAC e RAAS;
- `vw_sia_evento_core` como projeção comum, sem UNION destrutiva.

Referências CNES, SIGTAP, território e TAB_SIA são temporais.
