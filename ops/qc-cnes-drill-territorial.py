#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def duck(db: Path, sql: str, capture: bool = False) -> str:
    p = subprocess.run(
        ["duckdb", str(db), "-csv", "-noheader", "-c", sql],
        text=True,
        capture_output=True,
    )
    if p.returncode:
        if p.stdout:
            print(p.stdout, file=sys.stderr)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def main() -> int:
    ap = argparse.ArgumentParser(
        description="QC completo do drill territorial CNES Silver"
    )
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslabx"),
    )
    ap.add_argument("--database", type=Path)
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root)
    db = (args.database or lake / "silver" / "suslabx.duckdb").resolve()
    state = lake / "state" / "cnes"
    state.mkdir(parents=True, exist_ok=True)

    if not db.is_file():
        die(f"DuckDB ausente: {db}", 4)

    stats_sql = """
WITH t AS (
  SELECT *
  FROM cnes.dim_territorio
  WHERE tp_territorio='MUNICIPIO'
),
e AS (
  SELECT *
  FROM cnes.vw_estabelecimento_drill
),
region_multimacro AS (
  SELECT count(*) AS n
  FROM (
    SELECT co_regiao_saude_key
    FROM t
    GROUP BY 1
    HAVING count(DISTINCT co_macrorregiao_saude_key)>1
  )
),
macro_multiuf AS (
  SELECT count(*) AS n
  FROM (
    SELECT co_macrorregiao_saude_key
    FROM t
    GROUP BY 1
    HAVING count(DISTINCT co_uf_key)>1
  )
),
drill_conflict AS (
  SELECT count(*) AS n
  FROM (
    SELECT co_regiao_saude_drill_key
    FROM t
    GROUP BY 1
    HAVING count(DISTINCT co_uf_key)>1
       OR count(DISTINCT co_macrorregiao_saude_key)>1
       OR count(DISTINCT co_regiao_saude_key)>1
  )
)
SELECT
  (SELECT count(*) FROM t),
  (SELECT count(DISTINCT co_regiao_key) FROM t),
  (SELECT count(DISTINCT no_regiao) FROM t),
  (SELECT count(DISTINCT co_uf_key) FROM t),
  (SELECT count(*) FROM t
     WHERE co_regiao_key IS NULL OR no_regiao IS NULL OR no_regiao=''),
  (SELECT count(*) FROM t
     WHERE co_macrorregiao_saude_key IS NULL
        OR no_macrorregiao_saude IS NULL OR no_macrorregiao_saude=''),
  (SELECT count(*) FROM t
     WHERE co_regiao_saude_key IS NULL
        OR no_regiao_saude IS NULL OR no_regiao_saude=''),
  (SELECT count(*) FROM t
     WHERE co_regiao_saude_drill_key IS NULL
        OR co_regiao_saude_drill_key=''),
  (SELECT count(*) FROM t
     WHERE co_municipio_key IS NULL OR no_municipio IS NULL OR no_municipio=''),
  (SELECT count(*) FROM t
     WHERE coalesce(qt_regiao_saude,0)<>1),
  (SELECT count(*) FROM t
     WHERE coalesce(qt_macrorregiao_saude,0)<>1),
  (SELECT count(*) FROM cnes.dim_territorio WHERE tp_territorio='RA_DF'),
  (SELECT count(*) FROM cnes.dim_estabelecimento),
  (SELECT count(*) FROM e),
  (SELECT count(*) FROM e WHERE co_territorio_key IS NULL),
  (SELECT count(*) FROM e
     WHERE co_regiao_key IS NULL OR no_regiao IS NULL OR no_regiao=''),
  (SELECT count(*) FROM e
     WHERE sg_uf='DF' AND tp_territorio<>'RA_DF'),
  (SELECT n FROM region_multimacro),
  (SELECT n FROM macro_multiuf),
  (SELECT n FROM drill_conflict);
"""

    vals = list(map(int, next(csv.reader([duck(db, stats_sql, True).strip()]))))
    keys = [
        "municipios",
        "regioes",
        "nomes_regioes",
        "ufs",
        "miss_regiao",
        "miss_macro",
        "miss_regsaud",
        "miss_regsaud_drill_key",
        "miss_municipio",
        "municipio_multi_regsaud",
        "municipio_multi_macro",
        "ra_df",
        "estabelecimentos",
        "drill_rows",
        "estab_sem_territorio",
        "estab_sem_regiao",
        "df_estab_sem_ra",
        "regiao_saude_multimacro",
        "macro_saude_multiuf",
        "drill_path_conflitos",
    ]
    s = dict(zip(keys, vals))

    for k, v in s.items():
        print(f"{k}={v}")

    ts = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    if s["regiao_saude_multimacro"]:
        detail = state / f"qc_drill_territorial_{ts}_non_strict.tsv"
        duck(
            db,
            f"""
COPY (
WITH t AS (
  SELECT *
  FROM cnes.dim_territorio
  WHERE tp_territorio='MUNICIPIO'
),
multi AS (
  SELECT co_regiao_saude_key
  FROM t
  GROUP BY 1
  HAVING count(DISTINCT co_macrorregiao_saude_key)>1
)
SELECT
  'REGIAO_SAUDE_MULTIMACRO' AS finding,
  t.co_regiao_key,
  t.no_regiao,
  t.co_uf_key,
  t.sg_uf,
  t.co_macrorregiao_saude_key,
  t.co_macrorregiao_saude,
  t.no_macrorregiao_saude,
  t.co_regiao_saude_key,
  t.co_regiao_saude_drill_key,
  t.co_regiao_saude,
  t.no_regiao_saude,
  t.co_municipio_key,
  t.co_municipio_ibge,
  t.no_municipio
FROM t
JOIN multi USING (co_regiao_saude_key)
ORDER BY
  t.sg_uf,
  t.co_regiao_saude_key,
  t.co_macrorregiao_saude_key,
  t.no_municipio
)
TO {qs(str(detail))} (HEADER, DELIMITER '\t');
""",
        )
        print(
            "REGIAO_SAUDE_MULTIMACRO_INFO "
            f"count={s['regiao_saude_multimacro']} detail={detail}"
        )

        summary = duck(
            db,
            """
WITH t AS (
  SELECT *
  FROM cnes.dim_territorio
  WHERE tp_territorio='MUNICIPIO'
),
multi AS (
  SELECT co_regiao_saude_key
  FROM t
  GROUP BY 1
  HAVING count(DISTINCT co_macrorregiao_saude_key)>1
)
SELECT
  co_regiao_saude_key,
  any_value(no_regiao_saude),
  string_agg(
    DISTINCT co_macrorregiao_saude_key,
    ' | '
    ORDER BY co_macrorregiao_saude_key
  ),
  count(*)
FROM t
JOIN multi USING (co_regiao_saude_key)
GROUP BY 1
ORDER BY 1;
""",
            True,
        ).strip()
        for row in csv.reader(summary.splitlines()):
            print(
                "  canonical_region={} nome={} macro_paths={} municipios={}".format(
                    *row
                )
            )

    hard = (
        s["municipios"] != 5571
        or s["regioes"] != 5
        or s["nomes_regioes"] != 5
        or s["ufs"] != 27
        or any(
            s[k]
            for k in [
                "miss_regiao",
                "miss_macro",
                "miss_regsaud",
                "miss_regsaud_drill_key",
                "miss_municipio",
                "municipio_multi_regsaud",
                "municipio_multi_macro",
                "estab_sem_territorio",
                "estab_sem_regiao",
                "df_estab_sem_ra",
                "macro_saude_multiuf",
                "drill_path_conflitos",
            ]
        )
        or s["ra_df"] < 20
        or s["estabelecimentos"] != s["drill_rows"]
    )

    marker = state / "qc_drill_territorial_current.ok"
    marker.unlink(missing_ok=True)

    if hard:
        print("CNES_DRILL_TERRITORIAL_QC_FAIL", file=sys.stderr)
        return 20

    marker.write_text(
        "\n".join(
            [
                f"timestamp={ts}",
                *(f"{k}={v}" for k, v in s.items()),
                "hierarquia_drill=REGIAO>UF>MACRORREGIAO_SAUDE>REGIAO_SAUDE_DRILL>MUNICIPIO>RA_DF",
                "regiao_saude_canonica=independente_da_macrorregiao",
                "status=validated",
                "",
            ]
        ),
        encoding="utf-8",
    )
    print(f"marker={marker}")
    print("CNES_DRILL_TERRITORIAL_QC_OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
