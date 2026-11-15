#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def qi(v: str) -> str:
    return '"' + v.replace('"','""') + '"'

def duck(sql: str, capture: bool=False) -> str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        if p.stdout: print(p.stdout,file=sys.stderr)
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def columns(path: Path) -> dict[str,str]:
    out=duck(f"DESCRIBE SELECT * FROM read_parquet({qs(str(path))});",True)
    return {r[0].upper():r[0] for r in csv.reader(out.splitlines()) if r}

def choose(cols: dict[str,str], *cands: str) -> str | None:
    for c in cands:
        if c.upper() in cols:
            return cols[c.upper()]
    return None

def main() -> int:
    ap=argparse.ArgumentParser(description="Mapeia localidades operacionais CNES do DF contra divisoes administrativas territoriais")
    ap.add_argument("--competencia",required=True)
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()

    if not re.fullmatch(r"\d{6}",args.competencia):
        die("competencia deve ser YYYYMM",2)
    if not shutil.which("duckdb"):
        die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    estab=lake/"bronze"/"cnes"/"tb_estabelecimento"/f"competencia={args.competencia}"/"part-000.parquet"
    mun=lake/"silver"/"reference"/"territorio"/"tb_municip"/"current.parquet"
    rel=lake/"silver"/"reference"/"territorio"/"rl_municip_divadm"/"current.parquet"
    div=lake/"silver"/"reference"/"territorio"/"tb_divadm"/"current.parquet"
    state=lake/"state"/"cnes"
    state.mkdir(parents=True,exist_ok=True)

    for p in (estab,mun,rel,div):
        if not p.is_file():
            die(f"arquivo ausente: {p}")

    ec=columns(estab)
    mc=columns(mun)
    rc=columns(rel)
    dc=columns(div)

    e_mun=choose(ec,"CO_MUNICIPIO_GESTOR","CO_MUNICIP_GESTOR")
    e_cnes=choose(ec,"CO_CNES")
    m_key=choose(mc,"CO_MUNICIP")
    m_name=choose(mc,"DS_NOME","DS_NOMEPAD")
    r_mun=choose(rc,"CO_MUNICIP","CO_MUNINIP")
    r_div=choose(rc,"CO_DIVADM")
    d_div=choose(dc,"CO_DIVADM")
    d_name=choose(dc,"DS_NOME","DS_NOMEPAD","DS_ABREV")
    if not all([e_mun,m_key,m_name,r_mun,r_div,d_div,d_name]):
        die(
            "schema territorial/CNES nao resolvido: "
            f"estab={sorted(ec.values())} mun={sorted(mc.values())} "
            f"rel={sorted(rc.values())} div={sorted(dc.values())}"
        )

    e_cnes_expr=f"trim(cast(e.{qi(e_cnes)} as varchar))" if e_cnes else "NULL::VARCHAR"
    raw=f"regexp_replace(trim(cast(e.{qi(e_mun)} as varchar)), '[^0-9]', '', 'g')"
    code6=f"CASE WHEN length({raw})=7 THEN substr({raw},1,6) ELSE {raw} END"
    norm=lambda expr: f"upper(regexp_replace(strip_accents(trim(cast({expr} as varchar))), '[^A-Z0-9]+', '', 'g'))"

    base=f"""
WITH used AS (
  SELECT
    {code6} AS co_localidade_cnes,
    count(*) AS rows,
    min({e_cnes_expr}) AS exemplo_cnes
  FROM read_parquet({qs(str(estab))}) e
  WHERE substr({code6},1,2)='53'
  GROUP BY 1
),
catalog AS (
  SELECT
    trim(cast(m.{qi(m_key)} as varchar)) AS co_localidade_cnes,
    min(nullif(trim(cast(m.{qi(m_name)} as varchar)),'')) AS no_localidade_cnes
  FROM read_parquet({qs(str(mun))}) m
  WHERE substr(trim(cast(m.{qi(m_key)} as varchar)),1,2)='53'
  GROUP BY 1
),
df_div_raw AS (
  SELECT DISTINCT
    trim(cast(r.{qi(r_div)} as varchar)) AS co_divisao_administrativa,
    nullif(trim(cast(d.{qi(d_name)} as varchar)),'') AS no_divisao_administrativa
  FROM read_parquet({qs(str(rel))}) r
  LEFT JOIN read_parquet({qs(str(div))}) d
    ON trim(cast(d.{qi(d_div)} as varchar))=trim(cast(r.{qi(r_div)} as varchar))
  WHERE trim(cast(r.{qi(r_mun)} as varchar))='530010'
),
df_div AS (
  SELECT
    {norm("no_divisao_administrativa")} AS name_norm,
    count(DISTINCT co_divisao_administrativa) AS candidates,
    min(co_divisao_administrativa) AS co_divisao_administrativa,
    min(no_divisao_administrativa) AS no_divisao_administrativa
  FROM df_div_raw
  WHERE no_divisao_administrativa IS NOT NULL
  GROUP BY 1
),
mapped AS (
  SELECT
    u.*,
    c.no_localidade_cnes,
    CASE
      WHEN {norm("c.no_localidade_cnes")}='BRASILIA' THEN 'PLANOPILOTO'
      ELSE {norm("c.no_localidade_cnes")}
    END AS target_norm
  FROM used u
  LEFT JOIN catalog c USING (co_localidade_cnes)
),
resolved AS (
  SELECT
    m.*,
    coalesce(d.candidates,0) AS candidate_count,
    d.co_divisao_administrativa,
    d.no_divisao_administrativa,
    CASE
      WHEN d.co_divisao_administrativa IS NOT NULL
       AND regexp_matches(d.co_divisao_administrativa, '^530010[0-9]{{5}}$')
      THEN d.co_divisao_administrativa
    END AS co_ra_ibge,
    CASE
      WHEN d.candidates=1 AND {norm("m.no_localidade_cnes")}='BRASILIA'
           AND m.target_norm='PLANOPILOTO' THEN 'alias_brasilia_plano_piloto'
      WHEN d.candidates=1 THEN 'name_exact_normalized'
      WHEN d.candidates>1 THEN 'ambiguous_name'
      ELSE 'unresolved'
    END AS match_method
  FROM mapped m
  LEFT JOIN df_div d ON d.name_norm=m.target_norm
)
"""

    summary=duck(base+"""
SELECT
  count(*) AS df_localidade_codes,
  sum(rows) AS df_estabelecimentos,
  count(*) FILTER (WHERE match_method IN ('name_exact_normalized','alias_brasilia_plano_piloto')) AS mapped_codes,
  count(*) FILTER (WHERE match_method='unresolved') AS unresolved_codes,
  count(*) FILTER (WHERE match_method='ambiguous_name') AS ambiguous_codes,
  count(*) FILTER (WHERE co_ra_ibge IS NOT NULL) AS ra_ibge_11d_codes
FROM resolved;
""",True).strip()
    vals=list(map(int,next(csv.reader([summary]))))
    keys=["df_localidade_codes","df_estabelecimentos","mapped_codes","unresolved_codes","ambiguous_codes","ra_ibge_11d_codes"]
    s=dict(zip(keys,vals))

    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    detail=state/f"qc_df_territorio_{args.competencia}_{ts}.tsv"
    tmp=detail.with_suffix(".partial.tsv")
    duck(f"""
COPY (
{base}
SELECT
  co_localidade_cnes,
  no_localidade_cnes,
  rows,
  exemplo_cnes,
  candidate_count,
  co_divisao_administrativa,
  no_divisao_administrativa,
  co_ra_ibge,
  match_method
FROM resolved
ORDER BY rows DESC, co_localidade_cnes
)
TO {qs(str(tmp))} (HEADER, DELIMITER '\t');
""")
    os.replace(tmp,detail)

    marker=state/f"qc_df_territorio_{args.competencia}.ok"
    marker.write_text("\n".join([
        f"competencia={args.competencia}",
        f"timestamp={ts}",
        *(f"{k}={v}" for k,v in s.items()),
        f"detail={detail}",
        "parent_municipio_ibge=5300108",
        "policy=mapear_localidade_CNES_para_RA_por_referencia_territorial;alias_BRASILIA_para_PLANO_PILOTO_explicito;nao_usar_prefixo_CO_UNIDADE",
        "status=observed",
        ""
    ]),encoding="utf-8")

    print("CNES_DF_TERRITORIO " + " ".join(f"{k}={v}" for k,v in s.items()))
    print(f"detail={detail}")
    print(f"marker={marker}")
    print("CNES_DF_TERRITORIO_QC_OK")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
