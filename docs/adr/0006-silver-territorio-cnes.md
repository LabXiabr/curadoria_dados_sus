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

## Hierarquia principal de drill

A hierarquia analítica principal é:

```text
Região
  -> UF
    -> Macrorregião de Saúde
      -> Região de Saúde
        -> Município
          -> RA-DF
```

A dimensão é achatada: a linha do menor território resolvido contém também os
atributos dos níveis superiores. Isso permite `ROLLUP`, `GROUPING SETS` e
consultas ad hoc sem percorrer uma cadeia de tabelas.

Para evitar colisões de códigos locais entre UFs, a dimensão também expõe
chaves qualificadas:

- `REGIAO:<co_regiao>`;
- `UF:<co_uf>`;
- `MACRO_SAUDE:<co_uf>:<co_macrorregiao_saude>`;
- `REG_SAUDE:<co_uf>:<co_regiao_saude>`;
- `MUN:<IBGE7>`;
- `RA_DF:<IBGE11>`.

Consultas nacionais devem preferir essas chaves quando precisarem identificar
univocamente um nível, ainda que os nomes continuem disponíveis para exibição.

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
silver/suslake.duckdb
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

## Pendência DF

A Base Territorial corrente não resolve ainda a crosswalk dos códigos
operacionais CNES `53xxxx` para as RAs. A próxima evolução deve incorporar uma
fonte oficial de RA, produzir a crosswalk versionada e só então promover
estabelecimentos do DF de `MUN:5300108` para `RA_DF:<IBGE11>`.
