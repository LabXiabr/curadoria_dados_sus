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

def duck(sql: str, capture: bool = False) -> str:
    p = subprocess.run(
        ["duckdb", "-csv", "-noheader", "-c", sql],
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
        description="Constroi referencia Silver das RAs do Distrito Federal"
    )
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslabx"),
    )
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root)
    src = lake / "silver" / "reference" / "ibge_localidades" / "current.parquet"
    out = lake / "silver" / "reference" / "ra_df" / "current.parquet"
    state = lake / "state" / "reference"

    if not src.is_file():
        die(f"IBGE Localidades ausente: {src}", 4)

    out.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    tmp = out.with_name(out.name + f".partial.{os.getpid()}")
    tmp.unlink(missing_ok=True)

    duck(f"""
COPY (
  SELECT DISTINCT
    trim(CD_LOCALIDADE) AS co_ra_ibge,
    trim(NM_LOCALIDADE) AS no_ra,
    upper(
      regexp_replace(
        strip_accents(trim(NM_LOCALIDADE)),
        '[^A-Z0-9]+',
        '',
        'g'
      )
    ) AS no_ra_norm,
    trim(CT_LOCALIDADE) AS ct_localidade,
    trim(SCT_LOCALIDADE) AS sct_localidade,
    trim(CD_MUN) AS co_municipio_ibge,
    trim(NM_MUN) AS no_municipio_ibge,
    trim(LAT_LOCALIDADE) AS nu_latitude_ra,
    trim(LONG_LOCALIDADE) AS nu_longitude_ra,
    _source_year,
    _source_sha256,
    current_timestamp AS _built_at
  FROM read_parquet({qs(str(src))})
  WHERE trim(CD_UF)='53'
    AND regexp_matches(trim(CD_LOCALIDADE), '^[0-9]{{11}}$')
)
TO {qs(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")

    stats = duck(
        f"""
SELECT
  count(*) AS rows,
  count(DISTINCT co_ra_ibge) AS unique_codes,
  count(*) FILTER (
    WHERE co_ra_ibge IS NULL
       OR co_ra_ibge=''
       OR no_ra IS NULL
       OR no_ra=''
  ) AS missing
FROM read_parquet({qs(str(tmp))});
""",
        True,
    ).strip()

    rows, unique_codes, missing = map(int, next(csv.reader([stats])))

    if not (30 <= rows <= 40) or rows != unique_codes or missing:
        tmp.unlink(missing_ok=True)
        die(
            f"QC RA-DF falhou rows={rows} unique={unique_codes} missing={missing}; "
            "esperado 30..40 codigos unicos e completos",
            20,
        )

    os.replace(tmp, out)

    ts = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    marker = state / "ra_df_current.ok"
    marker.write_text(
        "\n".join(
            [
                f"timestamp={ts}",
                f"rows={rows}",
                f"unique_codes={unique_codes}",
                f"path={out}",
                "key=RA_DF:co_ra_ibge",
                "source=IBGE_Localidades_do_Brasil_2022",
                "selection_rule=CD_UF_53_and_CD_LOCALIDADE_11_digits",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"RA_DF_OK rows={rows} unique_codes={unique_codes}")
    print(f"path={out}")
    print(f"marker={marker}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
