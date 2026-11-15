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

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def duck(sql: str, capture: bool=False) -> str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr or p.stdout)
    return p.stdout if capture else ""

def main() -> int:
    ap=argparse.ArgumentParser(description="QC das chaves CO_UNIDADE e CO_CNES no CNES")
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
    END AS unidade_prefix6,
    CASE
      WHEN regexp_matches(trim(cast(CO_UNIDADE as varchar)), '^[0-9]{{13}}$')
      THEN substr(trim(cast(CO_UNIDADE as varchar)),7,7)
    END AS unidade_cnes7
  FROM read_parquet({qs(str(src))})
),
u AS (
  SELECT co_unidade, count(DISTINCT co_cnes) AS n_cnes
  FROM b
  WHERE co_unidade IS NOT NULL AND co_unidade<>''
  GROUP BY 1
),
c AS (
  SELECT co_cnes, count(DISTINCT co_unidade) AS n_unidade
  FROM b
  WHERE co_cnes IS NOT NULL AND co_cnes<>''
  GROUP BY 1
)
"""

    summary=duck(base+"""
SELECT
  (SELECT count(*) FROM b) AS rows,
  (SELECT count(*) FROM b WHERE co_unidade IS NULL OR co_unidade='') AS unidade_missing,
  (SELECT count(*) FROM b WHERE co_cnes IS NULL OR co_cnes='') AS cnes_missing,
  (SELECT count(*) FROM b WHERE regexp_matches(co_unidade, '^[0-9]{13}$')) AS unidade_numeric13,
  (SELECT count(*) FROM b WHERE co_unidade IS NOT NULL AND co_unidade<>'' AND NOT regexp_matches(co_unidade, '^[0-9]{13}$')) AS unidade_non_numeric13,
  (SELECT count(*) FROM b
     WHERE regexp_matches(co_unidade, '^[0-9]{13}$')
       AND unidade_cnes7 = lpad(co_cnes,7,'0')) AS suffix_equals_cnes,
  (SELECT count(*) FROM b
     WHERE regexp_matches(co_unidade, '^[0-9]{13}$')
       AND unidade_cnes7 <> lpad(co_cnes,7,'0')) AS suffix_diff_cnes,
  (SELECT count(*) FROM b
     WHERE regexp_matches(co_unidade, '^[0-9]{13}$')
       AND unidade_prefix6 = CASE
           WHEN length(co_mun)=7 THEN substr(co_mun,1,6)
           ELSE co_mun END) AS prefix_equals_municipio_gestor_cnes,
  (SELECT count(*) FROM b
     WHERE regexp_matches(co_unidade, '^[0-9]{13}$')
       AND unidade_prefix6 <> CASE
           WHEN length(co_mun)=7 THEN substr(co_mun,1,6)
           ELSE co_mun END) AS prefix_diff_municipio_gestor_cnes,
  (SELECT count(*) FROM u WHERE n_cnes>1) AS co_unidade_multicnes,
  (SELECT count(*) FROM c WHERE n_unidade>1) AS co_cnes_multiunidade;
""",True).strip()

    vals=next(csv.reader([summary]))
    fields=[
        "rows","unidade_missing","cnes_missing","unidade_numeric13",
        "unidade_non_numeric13","suffix_equals_cnes","suffix_diff_cnes",
        "prefix_equals_municipio_gestor_cnes","prefix_diff_municipio_gestor_cnes",
        "co_unidade_multicnes","co_cnes_multiunidade"
    ]
    data=dict(zip(fields,map(int,vals)))

    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    detail=state/f"qc_unidade_{args.competencia}_{ts}_detail.tsv"
    tmp=detail.with_suffix(".partial.tsv")
    duck(f"""
COPY (
{base}
SELECT
  b.co_unidade,
  b.co_cnes,
  b.co_mun AS co_municipio_gestor_cnes,
  b.unidade_prefix6,
  b.unidade_cnes7,
  coalesce(u.n_cnes,0) AS n_cnes_por_unidade,
  coalesce(c.n_unidade,0) AS n_unidades_por_cnes,
  CASE
    WHEN b.co_unidade IS NULL OR b.co_unidade='' THEN 'missing_co_unidade'
    WHEN b.co_cnes IS NULL OR b.co_cnes='' THEN 'missing_co_cnes'
    WHEN regexp_matches(b.co_unidade, '^[0-9]{{13}}$')
         AND b.unidade_cnes7 <> lpad(b.co_cnes,7,'0') THEN 'numeric13_suffix_diff_cnes'
    WHEN coalesce(u.n_cnes,0)>1 THEN 'co_unidade_multicnes'
    WHEN coalesce(c.n_unidade,0)>1 THEN 'co_cnes_multiunidade'
    WHEN NOT regexp_matches(b.co_unidade, '^[0-9]{{13}}$') THEN 'non_numeric13_informative'
    WHEN b.unidade_prefix6 <> CASE
         WHEN length(b.co_mun)=7 THEN substr(b.co_mun,1,6)
         ELSE b.co_mun END THEN 'prefix_diff_localidade_cnes_informative'
    ELSE 'ok'
  END AS finding
FROM b
LEFT JOIN u USING (co_unidade)
LEFT JOIN c USING (co_cnes)
WHERE b.co_unidade IS NULL OR b.co_unidade=''
   OR b.co_cnes IS NULL OR b.co_cnes=''
   OR NOT regexp_matches(b.co_unidade, '^[0-9]{{13}}$')
   OR b.unidade_cnes7 <> lpad(b.co_cnes,7,'0')
   OR b.unidade_prefix6 <> CASE
      WHEN length(b.co_mun)=7 THEN substr(b.co_mun,1,6)
      ELSE b.co_mun END
   OR coalesce(u.n_cnes,0)>1
   OR coalesce(c.n_unidade,0)>1
)
TO {qs(str(tmp))} (HEADER, DELIMITER '\t');
""")
    os.replace(tmp,detail)

    hard_fail=(
        data["unidade_missing"]>0
        or data["cnes_missing"]>0
        or data["suffix_diff_cnes"]>0
        or data["co_unidade_multicnes"]>0
        or data["co_cnes_multiunidade"]>0
    )

    marker=state/f"qc_unidade_{args.competencia}.ok"
    marker.unlink(missing_ok=True)

    for k in fields:
        print(f"{k}={data[k]}")
    print(f"detail={detail}")

    if hard_fail:
        print(
            "CNES_UNIDADE_QC_FAIL "
            "hard_fail=missing_key_or_functional_relation_or_numeric13_suffix",
            file=sys.stderr,
        )
        return 20

    marker.write_text("\n".join([
        f"competencia={args.competencia}",
        f"timestamp={ts}",
        *(f"{k}={v}" for k,v in data.items()),
        f"detail={detail}",
        "interpretation=CO_UNIDADE_opaca;numeric13_suffix7_observado_como_CO_CNES;prefix6_nao_autoritativo",
        "policy=hard_fail_missing_keys_or_relation_conflict_or_numeric13_suffix_conflict;non_numeric13_and_prefix_difference_informative",
        "status=validated",
        ""
    ]),encoding="utf-8")
    print(f"marker={marker}")
    print("CNES_UNIDADE_QC_OK")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
