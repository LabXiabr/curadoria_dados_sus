# ADR 0006 — Dimensão territorial conformada e drill Silver

Status: aceito

## Decisão

A hierarquia territorial reutilizável pertence à camada **Silver**.

A Silver mantém uma dimensão territorial conformada e larga em:

```text
silver/reference/dim_territorio/current.parquet
```

A chave analítica canônica é `co_territorio_key`. Ela representa o menor
território resolvido com segurança:

- `MUN:<IBGE7>`: município;
- `RA_DF:<IBGE11>`: Região Administrativa do Distrito Federal, somente quando
  o código territorial oficial estiver resolvido.

A crosswalk CNES-DF -> RA usa o produto oficial "Localidades do Brasil" do
IBGE. Os códigos operacionais CNES do DF são conciliados por nome normalizado
(com aliases explícitos documentados) e resultam em `RA_DF:<IBGE11>`.
Nenhuma RA é inferida do prefixo de `CO_UNIDADE`.

## Hierarquia de saúde: dimensão não estrita

Macrorregião de Saúde e Região de Saúde não formam uma hierarquia pai-filho
estrita em todo o Brasil. Rondônia é um caso oficial: a Região de Saúde
Central contém municípios alocados tanto na Macrorregião I quanto na
Macrorregião II.

Por isso a Silver preserva dois conceitos:

- `co_regiao_saude_key = REG_SAUDE:<UF>:<REGSAUD>`: identifica a Região de
  Saúde canônica, independentemente da Macrorregião;
- `co_regiao_saude_drill_key =
  REG_SAUDE_DRILL:<UF>:<MACRO>:<REGSAUD>`: identifica o ramo hierárquico
  utilizado quando o usuário navega passando pela Macrorregião.

O caminho de drill estrito é:

```text
Região
  -> UF
    -> Macrorregião de Saúde
      -> Região de Saúde dentro da Macro (REG_SAUDE_DRILL)
        -> Município
          -> RA-DF
```

Também é válido agregar diretamente:

```text
Região -> UF -> Região de Saúde canônica -> Município
```

A dimensão é achatada: a linha do menor território resolvido contém os
atributos e as duas chaves. Isso permite `ROLLUP`, `GROUPING SETS` e
consultas ad hoc sem inventar uma relação pai-filho que não existe na fonte.

Chaves qualificadas:

- `REGIAO:<co_regiao>`;
- `UF:<co_uf>`;
- `MACRO_SAUDE:<co_uf>:<co_macrorregiao_saude>`;
- `REG_SAUDE:<co_uf>:<co_regiao_saude>`;
- `REG_SAUDE_DRILL:<co_uf>:<co_macrorregiao_saude>:<co_regiao_saude>`;
- `MUN:<IBGE7>`;
- `RA_DF:<IBGE11>`.

O QC exige uma única Região de Saúde e uma única Macrorregião por município,
mas aceita que uma Região de Saúde canônica atravesse Macrorregiões.

Microrregião IBGE, Região Metropolitana/RIDE, DSEI, PNDR e Território da
Cidadania são classificações/hierarquias alternativas. Não devem ser
interpretadas como níveis intermediários obrigatórios da hierarquia principal.

## Relações Silver

O encadeamento canônico é:

```text
fact_estabelecimento_*
        |
        | co_unidade_key
        v
dim_estabelecimento
        |
        | co_territorio_key
        v
dim_territorio
```

`CO_UNIDADE` permanece chave relacional interna opaca do CNES. `CO_CNES`
permanece o identificador público do estabelecimento.

## Integridade referencial

Parquet não implementa chave estrangeira física. DuckDB, ao consultar Parquet
externo, também não transforma esses relacionamentos em constraints persistentes.

A integridade referencial é, portanto, um **contrato Silver validado por QC**:

1. fatos com `CO_UNIDADE` devem resolver em `dim_estabelecimento`;
2. `dim_estabelecimento.co_territorio_key` não pode ser nulo;
3. toda `co_territorio_key` de estabelecimento deve existir em
   `dim_territorio`;
4. duplicidade da chave da dimensão territorial bloqueia a construção;
5. falha nesses gates impede a publicação da Silver corrente.

Esse mecanismo é equivalente operacionalmente a uma FK para o lakehouse, mas
não deve ser descrito como constraint física do Parquet.

## Desnormalização e uso de disco

`dim_territorio` é a fonte canônica dos atributos territoriais.

`dim_estabelecimento` mantém também atributos territoriais largos para
facilitar consultas simples e inspeção ad hoc. Essa duplicação é deliberada e
aceitável porque:

- a dimensão de estabelecimentos é muito menor que os fatos principais;
- Parquet comprime bem colunas repetitivas/categóricas;
- reduz joins em consultas exploratórias;
- a fonte canônica continua explicitamente identificada.

Os fatos de serviço, equipamento e leito **não** recebem cópia materializada de
toda a geografia. O enriquecimento ocorre por views DuckDB, evitando multiplicar
o custo de disco nos fatos maiores.

## Views DuckDB

O pipeline cria um catálogo privado em:

```text
silver/suslabx.duckdb
```

As principais views são:

- `cnes.dim_territorio`;
- `cnes.dim_estabelecimento`;
- `cnes.vw_estabelecimento_drill`;
- `cnes.vw_servico_drill`;
- `cnes.vw_equipamento_drill`;
- `cnes.vw_leito_drill`.

As views referenciam os Parquet Silver; não materializam cópia dos fatos.

Exemplo:

```sql
SELECT
    no_regiao,
    sg_uf,
    no_macrorregiao_saude,
    no_regiao_saude,
    no_municipio,
    count(DISTINCT co_cnes_key) AS estabelecimentos
FROM cnes.vw_estabelecimento_drill
GROUP BY ROLLUP (
    no_regiao,
    sg_uf,
    no_macrorregiao_saude,
    no_regiao_saude,
    no_municipio
);
```

## Fronteira Silver / Gold

Pertencem à Silver:

- dimensões conformadas;
- chaves analíticas;
- relacionamentos semânticos;
- atributos hierárquicos;
- views reutilizáveis sem regra de indicador.

Pertencem à Gold:

- indicadores;
- métricas oficiais;
- cubos/materializações agregadas orientadas a produto;
- coortes e produtos analíticos específicos.

## RA do Distrito Federal

A referência de RA é o produto IBGE "Localidades do Brasil" de 2022. A seleção
das RAs usa `CD_UF=53` e `CD_LOCALIDADE` com 11 dígitos, regra específica
do produto para o Distrito Federal.

A bridge `bridge_localidade_cnes_ra_df` concilia os códigos operacionais
`53xxxx` do CNES com a RA por nome normalizado e aliases explícitos. O
pipeline bloqueia a Silver se alguma localidade DF usada na competência ficar
sem correspondência única. `CO_UNIDADE` nunca é usado para inferir RA.

## Profissionais

O dicionário oficial do CNES define `TB_DADOS_PROFISSIONAL_SUS` como a tabela
de profissionais e `CO_PROFISSIONAL_SUS` como sua chave primária. A Silver,
portanto, materializa `dim_profissional` diretamente dessa fonte e exige
unicidade e não nulidade de `co_profissional_sus_key` como hard gate.

`TB_CARGA_HORARIA_SUS` contém `CO_UNIDADE`, `CO_PROFISSIONAL_SUS`,
`CO_CBO`, vínculo e carga horária. Ela alimenta
`fact_profissional_vinculo`, que se relaciona a `dim_estabelecimento` por
`co_unidade_key` e ao profissional por `co_profissional_sus_key`.
