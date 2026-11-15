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

def sqls(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def qi(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'

def duck(sql: str, capture: bool = False) -> str:
    p = subprocess.run(
        ["duckdb","-csv","-noheader","-c",sql],
        text=True,capture_output=True
    )
    if p.returncode:
        if p.stdout:
            print(p.stdout,file=sys.stderr)
        if p.stderr:
            print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def describe(path: Path) -> dict[str,str]:
    out=duck(f"DESCRIBE SELECT * FROM read_parquet({sqls(str(path))});",True)
    return {r[0].upper():r[0] for r in csv.reader(out.splitlines()) if r}

def choose(cols: dict[str,str], *cands: str) -> str | None:
    for c in cands:
        if c.upper() in cols:
            return cols[c.upper()]
    return None

def read_marker(path: Path) -> dict[str,str]:
    out={}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1)
            out[k]=v
    return out

def main() -> int:
    ap=argparse.ArgumentParser(
        description="QC territorial da Bronze CNES contra dimensao municipal conformada"
    )
    ap.add_argument("--competencia",required=True)
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()

    if not re.fullmatch(r"\d{6}",args.competencia):
        die("competencia deve ser YYYYMM",2)
    if not shutil.which("duckdb"):
        die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    state=lake/"state"
    terr_state=state/"reference"
    cnes_state=state/"cnes"
    cnes_state.mkdir(parents=True,exist_ok=True)

    gate=terr_state/"territorio_current_complete.ok"
    if not gate.is_file():
        die(f"gate territorial ausente: {gate}")
    territory=read_marker(gate)

    bronze_marker=cnes_state/f"qc_bronze_{args.competencia}.ok"
    if not bronze_marker.is_file():
        die(f"marker Bronze CNES ausente: {bronze_marker}")

    estab=lake/"bronze"/"cnes"/"tb_estabelecimento"/f"competencia={args.competencia}"/"part-000.parquet"
    if not estab.is_file():
        candidates=sorted(
            (lake/"bronze"/"cnes").glob(f"*estabelec*/competencia={args.competencia}/part-000.parquet")
        )
        if len(candidates)==1:
            estab=candidates[0]
        else:
            die(
                "tb_estabelecimento nao localizado de forma univoca; "
                f"candidatos={[str(x) for x in candidates]}"
            )

    cols=describe(estab)
    c_mun=choose(
        cols,
        "CO_MUNICIPIO_GESTOR",
        "CO_MUNICIP_GESTOR",
        "CO_MUNICIPIO",
        "CO_MUNICIP",
        "IBGE",
    )
    c_cnes=choose(cols,"CO_CNES","CNES","CO_UNIDADE")
    if not c_mun:
        die(f"coluna municipal nao encontrada em {estab.parent.parent.name}: {sorted(cols.values())}")

    ctx=lake/"silver"/"reference"/"municipio_contexto"/"current.parquet"
    terr_all=lake/"silver"/"reference"/"territorio"/"tb_municip"/"current.parquet"
    if not ctx.is_file() or not terr_all.is_file():
        die("referencias municipais territoriais ausentes")

    mun_raw=f"regexp_replace(trim(cast(e.{qi(c_mun)} as varchar)), '[^0-9]', '', 'g')"
    mun6=f"""CASE
      WHEN length({mun_raw})=7 THEN substr({mun_raw},1,6)
      WHEN length({mun_raw})=6 THEN {mun_raw}
      ELSE NULL
    END"""
    mun7=f"""CASE
      WHEN length({mun_raw})=7 THEN {mun_raw}
      ELSE NULL
    END"""
    cnes_expr=f"trim(cast(e.{qi(c_cnes)} as varchar))" if c_cnes else "NULL::VARCHAR"

    detail=cnes_state/f"qc_territorio_{args.competencia}_unmatched.tsv"
    tmp=detail.with_suffix(".partial.tsv")

    base=f"""
WITH e0 AS (
  SELECT
    {cnes_expr} AS co_cnes,
    {mun_raw} AS co_municipio_raw,
    {mun6} AS co_municipio_6,
    {mun7} AS co_municipio_7
  FROM read_parquet({sqls(str(estab))}) e
),
active AS (
  SELECT DISTINCT co_municipio, co_municipio_ibge
  FROM read_parquet({sqls(str(ctx))})
),
catalog AS (
  SELECT DISTINCT
    trim(cast(CO_MUNICIP as varchar)) AS co_municipio,
    trim(cast(CO_MUNICDV as varchar)) AS co_municipio_ibge
  FROM read_parquet({sqls(str(terr_all))})
),
classified AS (
  SELECT
    e0.*,
    CASE
      WHEN co_municipio_raw IS NULL OR co_municipio_raw='' THEN 'missing_code'
      WHEN a.co_municipio IS NOT NULL OR a.co_municipio_ibge IS NOT NULL THEN 'active'
      WHEN c.co_municipio IS NOT NULL OR c.co_municipio_ibge IS NOT NULL THEN 'historical_catalog'
      ELSE 'unmatched'
    END AS territory_status
  FROM e0
  LEFT JOIN active a
    ON a.co_municipio=e0.co_municipio_6
    OR (e0.co_municipio_7 IS NOT NULL AND a.co_municipio_ibge=e0.co_municipio_7)
  LEFT JOIN catalog c
    ON c.co_municipio=e0.co_municipio_6
    OR (e0.co_municipio_7 IS NOT NULL AND c.co_municipio_ibge=e0.co_municipio_7)
)
"""

    summary=duck(base+"""
SELECT
  count(*) AS rows,
  count(DISTINCT co_cnes) FILTER (WHERE co_cnes IS NOT NULL AND co_cnes<>'') AS cnes_distinct,
  count(*) FILTER (WHERE territory_status='active') AS active_rows,
  count(*) FILTER (WHERE territory_status='historical_catalog') AS historical_rows,
  count(*) FILTER (WHERE territory_status='unmatched') AS unmatched_rows,
  count(*) FILTER (WHERE territory_status='missing_code') AS missing_code_rows,
  count(DISTINCT co_municipio_raw) FILTER (WHERE territory_status='unmatched') AS unmatched_codes
FROM classified;
""",True).strip()

    vals=list(map(int,next(csv.reader([summary]))))
    keys=["rows","cnes_distinct","active_rows","historical_rows",
          "unmatched_rows","missing_code_rows","unmatched_codes"]
    s=dict(zip(keys,vals))

    duck(f"""
COPY (
{base}
SELECT
  territory_status,
  co_municipio_raw,
  co_municipio_6,
  co_municipio_7,
  count(*) AS rows,
  min(co_cnes) AS exemplo_cnes
FROM classified
WHERE territory_status <> 'active'
GROUP BY 1,2,3,4
ORDER BY territory_status, rows DESC, co_municipio_raw
)
TO {sqls(str(tmp))} (HEADER, DELIMITER '\t');
""")
    os.replace(tmp,detail)

    print("CNES_TERRITORIO " + " ".join(f"{k}={v}" for k,v in s.items()))
    print(f"estabelecimento={estab}")
    print(f"municipality_column={c_mun}")
    print(f"detail={detail}")

    # Unmatched real codes are a hard failure; historical codes and blanks are reported.
    if s["unmatched_rows"] > 0:
        print(
            f"CNES_TERRITORIO_QC_FAIL unmatched_rows={s['unmatched_rows']} "
            f"unmatched_codes={s['unmatched_codes']}",
            file=sys.stderr,
        )
        return 20

    ts=subprocess.run(
        ["date","+%Y%m%d_%H%M%S"],
        text=True,capture_output=True,check=True
    ).stdout.strip()
    marker=cnes_state/f"qc_territorio_{args.competencia}.ok"
    marker.write_text("\n".join([
        f"competencia={args.competencia}",
        f"timestamp={ts}",
        f"territorio_snapshot={territory.get('snapshot','')}",
        f"territorio_source_sha256={territory.get('source_sha256','')}",
        f"table={estab.parent.parent.name}",
        f"municipality_column={c_mun}",
        *(f"{k}={v}" for k,v in s.items()),
        f"detail={detail}",
        "policy=bronze_fiel_sem_enriquecimento;territorio_usado_como_dimensao_conformada_de_qc",
        ""
    ]),encoding="utf-8")
    print(f"CNES_TERRITORIO_QC_OK {marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
