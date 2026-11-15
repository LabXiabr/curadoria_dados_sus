-- Exemplos de drill territorial CNES Silver.
-- Catalogo: /dados/abertos/suslake/silver/cnes/cnes.duckdb

-- 1. Drill principal: Regiao -> UF -> Macro -> Regiao de Saude -> Municipio.
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
)
ORDER BY 1,2,3,4,5;

-- 2. Classificacao alternativa: DSEI.
SELECT
    sg_uf,
    no_dsei,
    count(DISTINCT co_cnes_key) AS estabelecimentos
FROM cnes.vw_estabelecimento_drill
GROUP BY 1,2
ORDER BY 1,2;

-- 3. Servicos por Regiao de Saude, sem materializar geografia no fato.
SELECT
    sg_uf,
    no_regiao_saude,
    count(*) AS registros_servico,
    count(DISTINCT co_cnes_key) AS estabelecimentos
FROM cnes.vw_servico_drill
GROUP BY 1,2
ORDER BY 1,2;

-- 4. Menor territorio resolvido.
SELECT
    co_territorio_key,
    tp_territorio,
    no_municipio,
    no_ra,
    count(DISTINCT co_cnes_key) AS estabelecimentos
FROM cnes.vw_estabelecimento_drill
GROUP BY 1,2,3,4
ORDER BY 1;
