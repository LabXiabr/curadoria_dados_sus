#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import subprocess
from pathlib import Path

def die(msg: str, code: int = 2) -> None:
    print(f"ERRO: {msg}")
    raise SystemExit(code)

def qs(v: str | Path) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def duck(sql: str, *, header: bool = True) -> str:
    cmd=["duckdb"]
    if header:
        cmd += ["-csv"]
    else:
        cmd += ["-csv","-noheader"]
    cmd += ["-c",sql]
    p=subprocess.run(cmd,text=True,capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return p.stdout

def scalar(sql: str) -> str:
    return duck(sql,header=False).strip()

def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f".partial.{os.getpid()}")
    tmp.write_text(text,encoding="utf-8")
    os.replace(tmp,path)

def main() -> int:
    ap=argparse.ArgumentParser(
        description="CQ relacional SIH RD -> territorio/CNES/SIGTAP + consulta pesada"
    )
    ap.add_argument("--lake-root",default="/dados/abertos/suslabx")
    ap.add_argument("--min-territory",type=float,default=0.95)
    ap.add_argument("--min-sigtap",type=float,default=0.95)
    ap.add_argument("--min-cnes-current",type=float,default=0.90)
    args=ap.parse_args()

    lake=Path(args.lake_root).resolve()
    rd_glob=lake/"bronze"/"sih"/"200801_"/"rd"/"**"/"*.parquet"
    territorio=lake/"silver"/"reference"/"dim_territorio"/"current.parquet"
    cnes=lake/"silver"/"cnes"/"dim_estabelecimento"/"current.parquet"
    sigtap=lake/"silver"/"sigtap"/"tb_procedimento"/"temporal.parquet"
    required=[territorio,cnes,sigtap]
    missing=[str(x) for x in required if not x.is_file()]
    if missing:
        die("dimensoes persistidas ausentes: "+", ".join(missing),20)

    # Contratos minimos: falha cedo se colunas esperadas nao existirem.
    describe=duck(
        f"DESCRIBE SELECT * FROM read_parquet({qs(str(rd_glob))}, "
        "hive_partitioning=true, union_by_name=true);"
    )
    cols={r["column_name"].lower() for r in csv.DictReader(describe.splitlines())}
    required_rd={"n_aih","cnes","proc_rea","munic_res","munic_mov","competencia","uf"}
    absent=sorted(required_rd-cols)
    if absent:
        die("RD sem campos esperados: "+",".join(absent),21)

    latest=scalar(
        f"SELECT max(lpad(cast(competencia as varchar),6,'0')) "
        f"FROM read_parquet({qs(str(rd_glob))}, hive_partitioning=true, union_by_name=true);"
    )
    if not latest:
        die("RD Bronze vazio",22)

    state=lake/"state"/"sih"
    state.mkdir(parents=True,exist_ok=True)
    ts=dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report=state/f"qc_dimensions_{ts}.csv"
    heavy=state/f"heavy_fact_dimensions_{ts}.csv"

    cardinality_sql=f"""
SELECT 'territorio_municipio' relation,
       count(*)-count(DISTINCT trim(cast(co_municipio as varchar))) duplicates
FROM read_parquet({qs(territorio)})
WHERE tp_territorio='MUNICIPIO'
UNION ALL
SELECT 'cnes_current',
       count(*)-count(DISTINCT trim(cast(co_cnes_key as varchar)))
FROM read_parquet({qs(cnes)})
WHERE co_cnes_key IS NOT NULL AND trim(cast(co_cnes_key as varchar))<>''
UNION ALL
SELECT 'sigtap_procedimento_competencia',
       count(*)-count(DISTINCT trim(cast(co_procedimento as varchar)) || '|' || competencia)
FROM (
  SELECT co_procedimento, unnest(_observed_competencias) AS competencia
  FROM read_parquet({qs(sigtap)})
);
"""
    cardinality=list(csv.DictReader(duck(cardinality_sql).splitlines()))
    dup_bad=[r for r in cardinality if int(r["duplicates"])!=0]
    for r in cardinality:
        print(f"CARDINALITY {r['relation']} duplicates={r['duplicates']}")
    if dup_bad:
        die(
            "dimensao viola many-to-one: "
            + ",".join(f"{r['relation']}={r['duplicates']}" for r in dup_bad),
            23,
        )

    # As dimensoes sao tratadas como many-to-one. A consulta mede cobertura
    # sem permitir multiplicacao silenciosa de linhas.
    coverage_sql=f"""
WITH
rd AS (
  SELECT
    lpad(cast(competencia as varchar),6,'0') AS competencia,
    upper(cast(uf as varchar)) AS uf,
    trim(cast(n_aih as varchar)) AS n_aih,
    trim(cast(cnes as varchar)) AS cnes,
    trim(cast(proc_rea as varchar)) AS proc_rea,
    trim(cast(munic_res as varchar)) AS munic_res,
    trim(cast(munic_mov as varchar)) AS munic_mov
  FROM read_parquet({qs(str(rd_glob))}, hive_partitioning=true, union_by_name=true)
),
terr AS (
  SELECT trim(cast(co_municipio as varchar)) AS co_municipio
  FROM read_parquet({qs(territorio)})
  WHERE tp_territorio='MUNICIPIO'
),
sig AS (
  SELECT
    trim(cast(co_procedimento as varchar)) AS co_procedimento,
    _observed_competencias
  FROM read_parquet({qs(sigtap)})
),
est AS (
  SELECT trim(cast(co_cnes_key as varchar)) AS co_cnes_key
  FROM read_parquet({qs(cnes)})
),
metrics AS (
  SELECT
    'territorio_residencia_full_history' AS relation,
    count(*) FILTER (WHERE r.munic_res<>'')::BIGINT AS eligible,
    count(*) FILTER (WHERE r.munic_res<>'' AND t.co_municipio IS NOT NULL)::BIGINT AS matched
  FROM rd r
  LEFT JOIN terr t ON t.co_municipio=r.munic_res

  UNION ALL

  SELECT
    'territorio_estabelecimento_full_history',
    count(*) FILTER (WHERE r.munic_mov<>'')::BIGINT,
    count(*) FILTER (WHERE r.munic_mov<>'' AND t.co_municipio IS NOT NULL)::BIGINT
  FROM rd r
  LEFT JOIN terr t ON t.co_municipio=r.munic_mov

  UNION ALL

  SELECT
    'sigtap_proc_rea_exact_competencia',
    count(*) FILTER (WHERE r.proc_rea<>'')::BIGINT,
    count(*) FILTER (
      WHERE r.proc_rea<>'' AND s.co_procedimento IS NOT NULL
    )::BIGINT
  FROM rd r
  LEFT JOIN sig s
    ON s.co_procedimento=r.proc_rea
   AND list_contains(s._observed_competencias,r.competencia)

  UNION ALL

  SELECT
    'cnes_latest_snapshot_only',
    count(*) FILTER (WHERE r.cnes<>'')::BIGINT,
    count(*) FILTER (WHERE r.cnes<>'' AND e.co_cnes_key IS NOT NULL)::BIGINT
  FROM rd r
  LEFT JOIN est e ON e.co_cnes_key=r.cnes
  WHERE r.competencia={qs(latest)}
)
SELECT
  relation, eligible, matched,
  eligible-matched AS unmatched,
  CASE WHEN eligible=0 THEN NULL ELSE matched::DOUBLE/eligible END AS coverage
FROM metrics
ORDER BY relation;
"""
    coverage=duck(coverage_sql)
    write_text(report,coverage)

    rows=list(csv.DictReader(coverage.splitlines()))
    hard_bad=[]
    for r in rows:
        eligible=int(r["eligible"])
        matched=int(r["matched"])
        cov=float(r["coverage"]) if r["coverage"] else 0.0
        rel=r["relation"]
        threshold=(
            args.min_cnes_current if rel.startswith("cnes_")
            else args.min_sigtap if rel.startswith("sigtap_")
            else args.min_territory
        )
        st="OK" if cov>=threshold else "FAIL"
        print(
            f"RELATION {rel} eligible={eligible} matched={matched} "
            f"coverage={cov:.6f} threshold={threshold:.3f} status={st}"
        )
        if cov<threshold:
            hard_bad.append((rel,cov,threshold))

    # Query analitica deliberadamente mais pesada: usa toda a serie moderna para
    # territorio + SIGTAP e inclui CNES apenas na competencia mais recente, pois
    # dim_estabelecimento atual nao deve ser retroaplicada silenciosamente.
    heavy_sql=f"""
WITH
rd AS (
  SELECT
    lpad(cast(competencia as varchar),6,'0') AS competencia,
    upper(cast(uf as varchar)) AS uf,
    trim(cast(n_aih as varchar)) AS n_aih,
    trim(cast(cnes as varchar)) AS cnes,
    trim(cast(proc_rea as varchar)) AS proc_rea,
    trim(cast(munic_res as varchar)) AS munic_res,
    trim(cast(munic_mov as varchar)) AS munic_mov
  FROM read_parquet({qs(str(rd_glob))}, hive_partitioning=true, union_by_name=true)
),
terr AS (
  SELECT
    trim(cast(co_municipio as varchar)) AS co_municipio,
    co_regiao,no_regiao,sg_uf,no_uf,
    co_macrorregiao_saude,no_macrorregiao_saude,
    co_regiao_saude,no_regiao_saude,
    no_municipio
  FROM read_parquet({qs(territorio)})
  WHERE tp_territorio='MUNICIPIO'
),
sig AS (
  SELECT
    trim(cast(co_procedimento as varchar)) AS co_procedimento,
    _observed_competencias
  FROM read_parquet({qs(sigtap)})
),
est AS (
  SELECT
    trim(cast(co_cnes_key as varchar)) AS co_cnes_key,
    co_unidade_key,
    co_municipio_territorio,
    no_municipio_territorio
  FROM read_parquet({qs(cnes)})
),
joined AS (
  SELECT
    r.competencia,
    substr(r.competencia,1,4) AS ano,
    r.uf,
    r.n_aih,
    r.cnes,
    r.proc_rea,
    tr.no_regiao AS regiao_residencia,
    tr.no_uf AS uf_residencia,
    tr.no_municipio AS municipio_residencia,
    tm.no_regiao AS regiao_estabelecimento,
    tm.no_uf AS uf_estabelecimento,
    tm.no_municipio AS municipio_estabelecimento,
    s.co_procedimento IS NOT NULL AS procedimento_sigtap_ok,
    CASE WHEN r.competencia={qs(latest)} THEN e.co_cnes_key END AS cnes_dim_atual
  FROM rd r
  LEFT JOIN terr tr ON tr.co_municipio=r.munic_res
  LEFT JOIN terr tm ON tm.co_municipio=r.munic_mov
  LEFT JOIN sig s
    ON s.co_procedimento=r.proc_rea
   AND list_contains(s._observed_competencias,r.competencia)
  LEFT JOIN est e
    ON r.competencia={qs(latest)}
   AND e.co_cnes_key=r.cnes
)
SELECT
  ano,
  coalesce(regiao_estabelecimento,'<SEM_REGIAO>') AS regiao_estabelecimento,
  coalesce(uf_estabelecimento,uf,'<SEM_UF>') AS uf_estabelecimento,
  count(*)::BIGINT AS segmentos_rd,
  count(DISTINCT n_aih)::BIGINT AS aih_logicas,
  count(*) FILTER (WHERE procedimento_sigtap_ok)::BIGINT AS segmentos_proc_sigtap_ok,
  count(*) FILTER (
    WHERE competencia={qs(latest)} AND cnes_dim_atual IS NOT NULL
  )::BIGINT AS segmentos_cnes_atual_ok
FROM joined
GROUP BY 1,2,3
ORDER BY 1,2,3;
"""
    heavy_out=duck(heavy_sql)
    write_text(heavy,heavy_out)
    heavy_rows=max(len(heavy_out.splitlines())-1,0)
    print(
        f"SIH_HEAVY_QUERY_OK latest_competencia={latest} rows={heavy_rows} "
        f"output={heavy}"
    )

    if hard_bad:
        print("SIH_DIMENSION_QC_FAIL relations="+",".join(x[0] for x in hard_bad))
        return 10

    marker=state/"qc_dimensions_current.ok"
    write_text(
        marker,
        "\n".join([
            f"timestamp={ts}",
            f"latest_competencia={latest}",
            f"report={report}",
            f"heavy_query={heavy}",
            f"relations={len(rows)}",
            "cardinality=many_to_one_expected",
            "cnes_policy=current_dimension_only_on_latest_sih_competencia",
            "sigtap_policy=exact_observed_competencia",
            "territory_policy=municipio_key",
            "status=validated",
            "",
        ])
    )
    print(f"SIH_DIMENSION_QC_OK marker={marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
