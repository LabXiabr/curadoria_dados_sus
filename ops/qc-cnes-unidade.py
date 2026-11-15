#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
from pathlib import Path

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def duck(sql: str, capture: bool=False) -> str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout if capture else ""

def main() -> int:
    ap=argparse.ArgumentParser(description="QC semantico de CO_UNIDADE no CNES")
    ap.add_argument("--competencia",required=True)
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()

    if not re.fullmatch(r"\d{6}",args.competencia):
        raise SystemExit("competencia deve ser YYYYMM")
    if not shutil.which("duckdb"):
        raise SystemExit("duckdb CLI ausente")

    lake=Path(args.lake_root)
    src=lake/"bronze"/"cnes"/"tb_estabelecimento"/f"competencia={args.competencia}"/"part-000.parquet"
    state=lake/"state"/"cnes"
    state.mkdir(parents=True,exist_ok=True)
    if not src.is_file():
        raise SystemExit(f"tb_estabelecimento ausente: {src}")

    base=f"""
WITH b AS (
  SELECT
    trim(cast(CO_UNIDADE as varchar)) AS co_unidade,
    trim(cast(CO_CNES as varchar)) AS co_cnes,
    regexp_replace(trim(cast(CO_MUNICIPIO_GESTOR as varchar)), '[^0-9]', '', 'g') AS co_mun,
    CASE
      WHEN regexp_matches(trim(cast(CO_UNIDADE as varchar)), '^[0-9]{{13}}$')
      THEN substr(trim(cast(CO_UNIDADE as varchar)),1,6)
    END AS unidade_mun6,
    CASE
      WHEN regexp_matches(trim(cast(CO_UNIDADE as varchar)), '^[0-9]{{13}}$')
      THEN substr(trim(cast(CO_UNIDADE as varchar)),7,7)
    END AS unidade_cnes7
  FROM read_parquet({qs(str(src))})
)
"""

    summary=duck(base+"""
SELECT
  count(*) AS rows,
  count(*) FILTER (WHERE co_unidade IS NULL OR co_unidade='') AS unidade_missing,
  count(*) FILTER (WHERE regexp_matches(co_unidade, '^[0-9]{13}$')) AS unidade_numeric13,
  count(*) FILTER (
    WHERE regexp_matches(co_unidade, '^[0-9]{13}$')
      AND unidade_cnes7 = lpad(co_cnes,7,'0')
  ) AS suffix_equals_cnes,
  count(*) FILTER (
    WHERE regexp_matches(co_unidade, '^[0-9]{13}$')
      AND unidade_cnes7 <> lpad(co_cnes,7,'0')
  ) AS suffix_diff_cnes,
  count(*) FILTER (
    WHERE regexp_matches(co_unidade, '^[0-9]{13}$')
      AND unidade_mun6 = CASE
          WHEN length(co_mun)=7 THEN substr(co_mun,1,6)
          ELSE co_mun
      END
  ) AS prefix_equals_municipio,
  count(*) FILTER (
    WHERE regexp_matches(co_unidade, '^[0-9]{13}$')
      AND unidade_mun6 <> CASE
          WHEN length(co_mun)=7 THEN substr(co_mun,1,6)
          ELSE co_mun
      END
  ) AS prefix_diff_municipio
FROM b;
""",True).strip()

    vals=next(csv.reader([summary]))
    fields=[
        "rows","unidade_missing","unidade_numeric13","suffix_equals_cnes",
        "suffix_diff_cnes","prefix_equals_municipio","prefix_diff_municipio"
    ]
    data=dict(zip(fields,map(int,vals)))

    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    detail=state/f"qc_unidade_{args.competencia}_{ts}_mismatch.tsv"
    tmp=detail.with_suffix(".partial.tsv")
    duck(f"""
COPY (
{base}
SELECT
  co_unidade, co_cnes, co_mun, unidade_mun6, unidade_cnes7,
  CASE WHEN unidade_cnes7 <> lpad(co_cnes,7,'0') THEN 1 ELSE 0 END AS suffix_diff_cnes,
  CASE WHEN unidade_mun6 <> CASE
      WHEN length(co_mun)=7 THEN substr(co_mun,1,6)
      ELSE co_mun END THEN 1 ELSE 0 END AS prefix_diff_municipio
FROM b
WHERE NOT regexp_matches(co_unidade, '^[0-9]{{13}}$')
   OR unidade_cnes7 <> lpad(co_cnes,7,'0')
   OR unidade_mun6 <> CASE
      WHEN length(co_mun)=7 THEN substr(co_mun,1,6)
      ELSE co_mun END
)
TO {qs(str(tmp))} (HEADER, DELIMITER '\t');
""")
    os.replace(tmp,detail)

    marker=state/f"qc_unidade_{args.competencia}.ok"
    marker.write_text("\n".join([
        f"competencia={args.competencia}",
        f"timestamp={ts}",
        *(f"{k}={v}" for k,v in data.items()),
        f"detail={detail}",
        "interpretation=CO_UNIDADE_tested_as_candidate_municipio6_plus_cnes7",
        "policy=prefix_not_authoritative_for_territory_until_qc",
        "status=observed",
        ""
    ]),encoding="utf-8")

    for k in fields:
        print(f"{k}={data[k]}")
    print(f"detail={detail}")
    print(f"marker={marker}")
    print("CNES_UNIDADE_QC_OK")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
