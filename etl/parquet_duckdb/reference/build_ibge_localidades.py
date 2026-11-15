#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

FIELDS = [
    "CD_UF", "NM_UF", "SIGLA_UF", "CD_MUN", "NM_MUN",
    "CD_RGINT", "NM_RGINT", "CD_RGI", "NM_RGI",
    "CT_LOCALIDADE", "SCT_LOCALIDADE",
    "CD_LOCALIDADE", "NM_LOCALIDADE",
    "LAT_LOCALIDADE", "LONG_LOCALIDADE",
]

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def qi(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'

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

def read_marker(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Extrai atributos do GeoPackage IBGE Localidades para Silver"
    )
    ap.add_argument(
        "--year",
        default=os.environ.get("IBGE_LOCALIDADES_YEAR", "2022"),
    )
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"),
    )
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root)
    state = lake / "state" / "reference"
    raw_marker = state / f"ibge_localidades_{args.year}.raw.ok"
    if not raw_marker.is_file():
        die(f"marker Raw ausente: {raw_marker}", 4)

    meta = read_marker(raw_marker)
    zip_path = Path(meta["path"])
    if not zip_path.is_file():
        die(f"ZIP Raw ausente: {zip_path}", 4)

    out = lake / "silver" / "reference" / "ibge_localidades" / "current.parquet"
    out.parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="ibge_localidades_") as td0:
        td = Path(td0)

        with zipfile.ZipFile(zip_path) as zf:
            members = [n for n in zf.namelist() if n.lower().endswith(".gpkg")]
            if not members:
                die("GeoPackage ausente no ZIP", 5)
            member = members[0]
            gpkg = td / Path(member).name
            with zf.open(member) as src, gpkg.open("wb") as dst:
                shutil.copyfileobj(src, dst)

        con = sqlite3.connect(str(gpkg))
        try:
            try:
                candidates = [
                    r[0]
                    for r in con.execute(
                        "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
                    )
                ]
            except sqlite3.DatabaseError:
                candidates = []

            if not candidates:
                candidates = [
                    r[0]
                    for r in con.execute(
                        "SELECT name FROM sqlite_master "
                        "WHERE type='table' "
                        "AND name NOT LIKE 'gpkg_%' "
                        "AND name NOT LIKE 'rtree_%'"
                    )
                ]

            table = None
            actual: dict[str, str] = {}
            for candidate in candidates:
                colmap = {
                    r[1].upper(): r[1]
                    for r in con.execute(f"PRAGMA table_info({qi(candidate)})")
                }
                if all(field in colmap for field in FIELDS):
                    table = candidate
                    actual = colmap
                    break

            if table is None:
                die(
                    "nenhuma tabela GeoPackage contem todos os campos esperados; "
                    f"candidates={candidates}",
                    6,
                )

            tsv = td / "localidades.tsv"
            select_sql = ", ".join(qi(actual[field]) for field in FIELDS)
            cur = con.execute(f"SELECT {select_sql} FROM {qi(table)}")

            with tsv.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, delimiter="\t", lineterminator="\n")
                w.writerow(FIELDS)
                while True:
                    rows = cur.fetchmany(5000)
                    if not rows:
                        break
                    w.writerows(rows)
        finally:
            con.close()

        tmp = out.with_name(out.name + f".partial.{os.getpid()}")
        tmp.unlink(missing_ok=True)

        duck(f"""
COPY (
  SELECT
    *,
    {qs(args.year)}::VARCHAR AS _source_year,
    {qs(meta.get("sha256", ""))}::VARCHAR AS _source_sha256,
    {qs(str(zip_path))}::VARCHAR AS _source_path,
    current_timestamp AS _built_at
  FROM read_csv(
    {qs(str(tsv))},
    delim='\t',
    header=true,
    all_varchar=true,
    null_padding=true,
    parallel=false
  )
)
TO {qs(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")

    stats = duck(
        f"""
SELECT
  count(*) AS rows,
  count(*) FILTER (
    WHERE trim(CD_UF)='53'
      AND regexp_matches(trim(CD_LOCALIDADE), '^[0-9]{{11}}$')
  ) AS ra_df_11d
FROM read_parquet({qs(str(tmp))});
""",
        True,
    ).strip()

    rows, ra_df = map(int, next(csv.reader([stats])))

    if rows < 80000 or not (30 <= ra_df <= 40):
        tmp.unlink(missing_ok=True)
        die(
            f"cobertura inesperada rows={rows} ra_df_11d={ra_df}; "
            "esperado rows>=80000 e 30..40 localidades DF de 11 digitos",
            20,
        )

    os.replace(tmp, out)

    ts = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    marker = state / "ibge_localidades_current.ok"
    marker.write_text(
        "\n".join(
            [
                f"timestamp={ts}",
                f"year={args.year}",
                f"rows={rows}",
                f"ra_df_11d={ra_df}",
                f"path={out}",
                f"source_sha256={meta.get('sha256', '')}",
                "scope=atributos_nao_geometricos_Localidades_do_Brasil",
                "ra_df_rule=CD_UF_53_and_CD_LOCALIDADE_11_digits",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"IBGE_LOCALIDADES_SILVER_OK rows={rows} ra_df_11d={ra_df}")
    print(f"path={out}")
    print(f"marker={marker}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
