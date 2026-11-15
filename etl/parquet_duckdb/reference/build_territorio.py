#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
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
    return "'" + v.replace("'", "''") + "'"

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

def read_marker(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def table_name(filename: str) -> str:
    stem = Path(filename).stem
    stem = unicodedata.normalize("NFKD", stem)
    stem = "".join(c for c in stem if not unicodedata.combining(c))
    stem = re.sub(r"[^A-Za-z0-9_]+", "_", stem).strip("_").lower()
    return stem

def detect_encoding(sample: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            sample.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    return "latin-1"

def detect_delim(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters=";,\t|").delimiter
    except csv.Error:
        counts = {d: text.count(d) for d in (";", ",", "\t", "|")}
        return max(counts, key=counts.get)

def recode(zf: zipfile.ZipFile, info: zipfile.ZipInfo, out: Path) -> tuple[str, str]:
    with zf.open(info, "r") as f:
        sample = f.read(262144)
    enc = detect_encoding(sample)
    delim = detect_delim(sample.decode(enc, errors="strict"))
    with zf.open(info, "r") as raw:
        src = io.TextIOWrapper(raw, encoding=enc, errors="strict", newline="")
        with out.open("w", encoding="utf-8", newline="") as dst:
            shutil.copyfileobj(src, dst, length=1024 * 1024)
    return enc, delim

def count_rows(path: Path, delim: str) -> int:
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter=delim)
        try:
            next(r)
        except StopIteration:
            return 0
        return sum(1 for row in r if row and any(x.strip() for x in row))

def main() -> int:
    ap = argparse.ArgumentParser(description="Base territorial DATASUS -> Bronze/Silver Parquet")
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"))
    ap.add_argument("--zip", type=Path)
    ap.add_argument("--snapshot")
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root)
    state = lake / "state" / "reference"
    marker_path = state / "territorio_latest.ok"

    if args.zip:
        zp = args.zip.resolve()
        snapshot = args.snapshot or "manual"
        sha = subprocess.run(["sha256sum", str(zp)], text=True, capture_output=True,
                             check=True).stdout.split()[0]
    else:
        if not marker_path.is_file():
            die(f"marker ausente: {marker_path}; rode ops/territorio-acquire.sh", 4)
        m = read_marker(marker_path)
        zp = Path(m["path"])
        snapshot = args.snapshot or m["snapshot"]
        sha = m["sha256"]

    if not zp.is_file():
        die(f"ZIP ausente: {zp}", 4)

    bronze_root = lake / "bronze" / "reference" / "territorio"
    silver_root = lake / "silver" / "reference" / "territorio"
    workroot = lake / "work" / "territorio"
    workroot.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f"{snapshot}_", dir=workroot))
    report_rows = []

    try:
        with zipfile.ZipFile(zp) as zf:
            bad = zf.testzip()
            if bad:
                die(f"ZIP corrompido: {bad}", 5)
            entries = [
                x for x in zf.infolist()
                if not x.is_dir() and x.filename.lower().endswith(".csv")
            ]
            if not entries:
                die("ZIP territorial sem CSV", 6)

            seen = set()
            for idx, info in enumerate(sorted(entries, key=lambda x: x.filename.lower()), 1):
                table = table_name(Path(info.filename).name)
                if table in seen:
                    raise RuntimeError(f"colisao de tabela: {table}")
                seen.add(table)

                src = work / f"{table}.csv"
                enc, delim = recode(zf, info, src)
                rows_src = count_rows(src, delim)

                destdir = bronze_root / table / f"snapshot={snapshot}"
                destdir.mkdir(parents=True, exist_ok=True)
                dest = destdir / "part-000.parquet"
                partial = dest.with_name(dest.name + f".partial.{os.getpid()}")

                run_duck(f"""
COPY (
  SELECT *,
         {sqls(snapshot)}::VARCHAR AS _source_snapshot,
         {sqls(zp.name)}::VARCHAR AS _source_zip,
         {sqls(sha)}::VARCHAR AS _source_sha256,
         {sqls(info.filename)}::VARCHAR AS _source_file,
         current_timestamp AS _ingested_at
  FROM read_csv_auto(
      {sqls(str(src))},
      delim={sqls(delim)},
      header=true,
      all_varchar=true,
      sample_size=-1,
      null_padding=true
  )
)
TO {sqls(str(partial))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
                rows_pq = int(run_duck(
                    f"SELECT count(*) FROM read_parquet({sqls(str(partial))});",
                    True).strip())
                if rows_src != rows_pq:
                    raise RuntimeError(f"{table}: CSV={rows_src} Parquet={rows_pq}")
                os.replace(partial, dest)

                current_dir = silver_root / table
                current_dir.mkdir(parents=True, exist_ok=True)
                current = current_dir / "current.parquet"
                ctmp = current.with_name(current.name + f".partial.{os.getpid()}")
                run_duck(f"""
COPY (
  SELECT * FROM read_parquet({sqls(str(dest))})
)
TO {sqls(str(ctmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
                os.replace(ctmp, current)

                report_rows.append((
                    table, info.filename, enc, delim, rows_src,
                    info.file_size, f"{info.CRC:08x}", str(dest), str(current)
                ))
                print(f"[{idx}/{len(entries)}] OK {table} rows={rows_src}")

        ts = subprocess.run(["date", "+%Y%m%d_%H%M%S"], text=True,
                            capture_output=True, check=True).stdout.strip()
        report = state / f"territorio_{snapshot}_{ts}.tsv"
        with report.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(["table", "source_file", "encoding", "delimiter", "rows",
                        "source_bytes", "source_crc32", "bronze", "silver_current"])
            w.writerows(report_rows)

        q = run_duck(f"""
SELECT
  count(*) AS rows,
  count(DISTINCT coalesce(cast(CO_MUNICIP as varchar), cast(co_municipip as varchar), '')) AS municipios
FROM read_parquet({sqls(str(silver_root / 'tb_municip' / 'current.parquet'))});
""", True) if (silver_root / "tb_municip" / "current.parquet").is_file() else ""

        marker = state / "territorio_current.ok"
        marker.write_text("\n".join([
            f"timestamp={ts}",
            f"snapshot={snapshot}",
            f"source_zip={zp.name}",
            f"source_sha256={sha}",
            f"tables={len(report_rows)}",
            f"report={report}",
            ""
        ]), encoding="utf-8")
        print(f"TERRITORIO_REFERENCE_OK snapshot={snapshot} tables={len(report_rows)}")
        print(f"marker={marker}")
        return 0
    finally:
        if args.keep_work:
            print(f"work={work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

if __name__ == "__main__":
    raise SystemExit(main())
