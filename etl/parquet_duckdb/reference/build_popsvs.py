#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def run_duck(sql: str, capture: bool = False) -> str:
    p = subprocess.run(["duckdb", "-csv", "-noheader", "-c", sql],
                       text=True, capture_output=True)
    if p.returncode:
        if p.stdout:
            print(p.stdout, file=sys.stderr)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def normalize_name(name: str) -> str:
    s = unicodedata.normalize("NFKD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def parse_dbf(path: Path):
    with path.open("rb") as f:
        header = f.read(32)
        if len(header) != 32:
            raise RuntimeError("cabecalho DBF incompleto")
        n_records = struct.unpack("<I", header[4:8])[0]
        header_len = struct.unpack("<H", header[8:10])[0]
        record_len = struct.unpack("<H", header[10:12])[0]

        fields = []
        while True:
            b = f.read(1)
            if not b:
                raise RuntimeError("fim inesperado no descritor DBF")
            if b == b"\r":
                break
            desc = b + f.read(31)
            raw_name = desc[0:11].split(b"\x00", 1)[0].decode("ascii", errors="ignore").strip()
            ftype = chr(desc[11])
            flen = desc[16]
            dec = desc[17]
            fields.append((normalize_name(raw_name), ftype, flen, dec, raw_name))

        f.seek(header_len)
        rows = []
        for _ in range(n_records):
            rec = f.read(record_len)
            if len(rec) < record_len:
                break
            if rec[:1] == b"*":
                continue
            pos = 1
            row = {}
            for name, ftype, flen, dec, raw_name in fields:
                raw = rec[pos:pos+flen]
                pos += flen
                raw = raw.rstrip(b" \x00")
                try:
                    val = raw.decode("cp1252")
                except UnicodeDecodeError:
                    val = raw.decode("latin-1")
                row[name] = val.strip()
            rows.append(row)
    return fields, rows, n_records

def pick(row_names: set[str], *candidates: str) -> str:
    for c in candidates:
        if c in row_names:
            return c
    raise RuntimeError(f"campo ausente; esperados={candidates}; encontrados={sorted(row_names)}")

def main() -> int:
    ap = argparse.ArgumentParser(description="POPSVS DBF -> Bronze/Silver Parquet")
    ap.add_argument("--from", dest="year_from", type=int, default=2000)
    ap.add_argument("--to", dest="year_to", type=int, default=2025)
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"))
    args = ap.parse_args()

    if args.year_from > args.year_to:
        die("--from > --to")
    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root)
    raw_root = lake / "raw" / "reference" / "populacao_popsvs"
    bronze_root = lake / "bronze" / "reference" / "populacao_popsvs"
    silver_root = lake / "silver" / "reference" / "populacao_idade_sexo"
    state = lake / "state" / "reference"
    workroot = lake / "work" / "popsvs"
    state.mkdir(parents=True, exist_ok=True)
    workroot.mkdir(parents=True, exist_ok=True)

    failures = []
    report_rows = []

    for year in range(args.year_from, args.year_to + 1):
        yy = f"{year % 100:02d}"
        zp = raw_root / f"ano={year}" / f"POPSBR{yy}.zip"
        if not zp.is_file():
            failures.append((year, "raw_zip_missing"))
            continue

        zip_sha = sha256_file(zp)
        work = Path(tempfile.mkdtemp(prefix=f"{year}_", dir=workroot))
        try:
            with zipfile.ZipFile(zp) as zf:
                bad = zf.testzip()
                if bad:
                    raise RuntimeError(f"ZIP corrompido: {bad}")
                dbfs = [x for x in zf.namelist() if x.lower().endswith(".dbf")]
                if not dbfs:
                    raise RuntimeError("ZIP sem DBF")
                preferred = [x for x in dbfs if Path(x).name.lower() == f"pop{yy}.dbf"]
                member = preferred[0] if preferred else sorted(dbfs)[0]
                dbf = work / Path(member).name
                with zf.open(member) as src, dbf.open("wb") as dst:
                    shutil.copyfileobj(src, dst)

            fields, rows, declared = parse_dbf(dbf)
            if not rows:
                raise RuntimeError("DBF sem registros")
            names = set(rows[0].keys())
            c_mun = pick(names, "cod_mun", "co_municipio", "codmun", "municipio")
            c_ano = pick(names, "ano")
            c_sexo = pick(names, "sexo")
            c_idade = pick(names, "idade")
            c_pop = pick(names, "pop", "populacao")

            csv_path = work / f"popsvs_{year}.csv"
            with csv_path.open("w", encoding="utf-8", newline="") as f:
                w = csv.writer(f, lineterminator="\n")
                w.writerow(["co_municipio", "ano", "sexo", "idade", "populacao"])
                for r in rows:
                    ano = r.get(c_ano, "").strip()
                    if ano and ano != str(year):
                        raise RuntimeError(f"ano divergente no DBF: {ano} != {year}")
                    pop = r.get(c_pop, "").strip()
                    if pop and not re.fullmatch(r"-?\d+(?:\.0+)?", pop):
                        raise RuntimeError(f"populacao nao inteira: {pop!r}")
                    if pop.endswith(".0"):
                        pop = pop[:-2]
                    w.writerow([
                        r.get(c_mun, "").strip(),
                        ano or str(year),
                        r.get(c_sexo, "").strip(),
                        r.get(c_idade, "").strip(),
                        pop,
                    ])

            bronze_dir = bronze_root / f"ano={year}"
            bronze_dir.mkdir(parents=True, exist_ok=True)
            bronze = bronze_dir / "part-000.parquet"
            btmp = bronze.with_name(bronze.name + f".partial.{os.getpid()}")

            run_duck(f"""
COPY (
 SELECT
   cast(co_municipio as varchar) AS co_municipio,
   cast(ano as varchar) AS ano,
   cast(sexo as varchar) AS sexo,
   cast(idade as varchar) AS idade,
   cast(populacao as varchar) AS populacao,
   {sqls(zp.name)}::VARCHAR AS _source_zip,
   {sqls(zip_sha)}::VARCHAR AS _source_sha256,
   {sqls(member)}::VARCHAR AS _source_dbf,
   current_timestamp AS _ingested_at
 FROM read_csv_auto({sqls(str(csv_path))}, header=true, all_varchar=true, sample_size=-1)
)
TO {sqls(str(btmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
            os.replace(btmp, bronze)

            silver_dir = silver_root / f"ano={year}"
            silver_dir.mkdir(parents=True, exist_ok=True)
            silver = silver_dir / "part-000.parquet"
            stmp = silver.with_name(silver.name + f".partial.{os.getpid()}")
            run_duck(f"""
COPY (
 SELECT
   co_municipio,
   cast(ano as INTEGER) AS ano,
   sexo,
   idade,
   cast(nullif(populacao,'') as BIGINT) AS populacao,
   _source_zip,
   _source_sha256,
   _source_dbf,
   _ingested_at
 FROM read_parquet({sqls(str(bronze))})
)
TO {sqls(str(stmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")

            stats = run_duck(f"""
SELECT
  count(*) AS rows,
  count(*) FILTER (WHERE co_municipio IS NULL OR co_municipio='') AS missing_municipio,
  count(*) FILTER (WHERE populacao IS NULL) AS missing_pop,
  count(*) - count(DISTINCT co_municipio || chr(31) || cast(ano as varchar) || chr(31) || sexo || chr(31) || idade) AS duplicate_key
FROM read_parquet({sqls(str(stmp))});
""", True).strip()
            rows_pq, miss_mun, miss_pop, dup = map(int, next(csv.reader([stats])))
            if rows_pq != len(rows) or miss_mun or miss_pop or dup:
                raise RuntimeError(
                    f"QC falhou rows_dbf={len(rows)} rows_pq={rows_pq} "
                    f"missing_municipio={miss_mun} missing_pop={miss_pop} duplicate_key={dup}"
                )
            os.replace(stmp, silver)

            marker = state / f"popsvs_{year}.ok"
            marker.write_text("\n".join([
                f"ano={year}",
                f"timestamp={subprocess.run(['date','-Is'],text=True,capture_output=True,check=True).stdout.strip()}",
                f"zip={zp.name}",
                f"zip_sha256={zip_sha}",
                f"dbf={member}",
                f"dbf_records_declared={declared}",
                f"rows={rows_pq}",
                f"bronze={bronze}",
                f"silver={silver}",
                ""
            ]), encoding="utf-8")
            report_rows.append((year, zp.name, member, rows_pq, zip_sha, "ok"))
            print(f"OK {year} rows={rows_pq} dbf={member}")
        except Exception as exc:
            failures.append((year, str(exc)))
            report_rows.append((year, zp.name, "", "", zip_sha, f"failed:{exc}"))
            print(f"ERRO {year}: {exc}", file=sys.stderr)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    ts = subprocess.run(["date", "+%Y%m%d_%H%M%S"], text=True,
                        capture_output=True, check=True).stdout.strip()
    report = state / f"popsvs_build_{ts}.tsv"
    with report.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, delimiter="\t", lineterminator="\n")
        w.writerow(["ano","zip","dbf","rows","sha256","status"])
        w.writerows(report_rows)

    print(f"Relatorio: {report}")
    if failures:
        for year, err in failures:
            print(f"FALHA {year}: {err}", file=sys.stderr)
        die(f"POPSVS Silver incompleta: {len(failures)} ano(s)", 20)

    global_marker = state / "popsvs_complete.ok"
    global_marker.write_text("\n".join([
        f"timestamp={ts}",
        f"from={args.year_from}",
        f"to={args.year_to}",
        f"anos={args.year_to-args.year_from+1}",
        f"report={report}",
        "grain=municipio_sexo_idade_ano",
        ""
    ]), encoding="utf-8")
    print(f"POPSVS_COMPLETE_OK {global_marker}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
