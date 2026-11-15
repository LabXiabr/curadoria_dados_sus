#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
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

RE_ZIP = re.compile(r"^BASE_DE_DADOS_CNES_(\d{6})\.ZIP$", re.I)

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

def normalize_table(filename: str, competencia: str) -> str:
    stem = Path(filename).stem
    stem = re.sub(rf"[_-]?{re.escape(competencia)}$", "", stem, flags=re.I)
    stem = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", stem)
    stem = unicodedata.normalize("NFKD", stem)
    stem = "".join(c for c in stem if not unicodedata.combining(c))
    stem = re.sub(r"[^A-Za-z0-9]+", "_", stem).strip("_").lower()
    if not stem:
        raise RuntimeError(f"nome de tabela vazio para {filename}")
    if stem[0].isdigit():
        stem = "t_" + stem
    return stem

def detect_encoding(sample: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252"):
        try:
            sample.decode(enc)
            return enc
        except UnicodeDecodeError:
            pass
    return "latin-1"

def detect_delimiter(text: str) -> str:
    try:
        return csv.Sniffer().sniff(text, delimiters=";,\t|").delimiter
    except csv.Error:
        return ";"

def recode_entry(zf: zipfile.ZipFile, info: zipfile.ZipInfo, dest: Path) -> tuple[str, str]:
    with zf.open(info, "r") as src:
        sample = src.read(262144)
    enc = detect_encoding(sample)
    text_sample = sample.decode(enc, errors="strict")
    delim = detect_delimiter(text_sample)
    with zf.open(info, "r") as raw:
        reader = io.TextIOWrapper(raw, encoding=enc, errors="strict", newline="")
        with dest.open("w", encoding="utf-8", newline="") as out:
            shutil.copyfileobj(reader, out, length=1024 * 1024)
    return enc, delim

def independent_csv_rows(path: Path, delim: str) -> int:
    with path.open("r", encoding="utf-8", newline="") as f:
        r = csv.reader(f, delimiter=delim)
        try:
            next(r)
        except StopIteration:
            return 0
        n = 0
        for row in r:
            if not row or all(x == "" for x in row):
                continue
            n += 1
        return n

def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def main() -> int:
    ap = argparse.ArgumentParser(description="CNES BASE_DE_DADOS mensal -> Bronze Parquet")
    ap.add_argument("--competencia", required=True)
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"))
    ap.add_argument("--zip", type=Path)
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    if not re.fullmatch(r"\d{6}", args.competencia):
        die("competencia deve ser YYYYMM")
    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root)
    rawdir = lake / "raw" / "cnes" / "base_dados" / f"competencia={args.competencia}"
    bronze = lake / "bronze" / "cnes"
    state = lake / "state" / "cnes"
    workroot = lake / "work" / "cnes"
    state.mkdir(parents=True, exist_ok=True)
    workroot.mkdir(parents=True, exist_ok=True)

    zp = args.zip
    if zp is None:
        matches = sorted(rawdir.glob(f"BASE_DE_DADOS_CNES_{args.competencia}.ZIP"))
        if not matches:
            matches = sorted(rawdir.glob(f"BASE_DE_DADOS_CNES_{args.competencia}.zip"))
        if not matches:
            die(f"ZIP Raw nao encontrado em {rawdir}", 4)
        zp = matches[-1]
    zp = zp.resolve()
    m = RE_ZIP.match(zp.name)
    if not m or m.group(1) != args.competencia:
        die(f"ZIP nao corresponde a competencia {args.competencia}: {zp.name}", 4)

    zip_sha = file_sha256(zp)
    ts = subprocess.run(["date", "+%Y%m%d_%H%M%S"], text=True,
                        capture_output=True, check=True).stdout.strip()
    work = Path(tempfile.mkdtemp(prefix=f"{args.competencia}_", dir=workroot))
    manifest = state / f"bronze_{args.competencia}_{ts}.tsv"
    rows_report = []
    seen_tables: set[str] = set()

    try:
        with zipfile.ZipFile(zp) as zf:
            bad = zf.testzip()
            if bad:
                die(f"ZIP corrompido; primeiro membro ruim: {bad}", 5)
            entries = [i for i in zf.infolist()
                       if not i.is_dir() and i.filename.lower().endswith(".csv")]
            if not entries:
                ext = sorted({Path(i.filename).suffix.lower() for i in zf.infolist() if not i.is_dir()})
                die(f"nenhum CSV no ZIP; extensoes observadas={ext}", 6)

            for idx, info in enumerate(sorted(entries, key=lambda x: x.filename.lower()), start=1):
                table = normalize_table(Path(info.filename).name, args.competencia)
                if table in seen_tables:
                    raise RuntimeError(f"colisao de tabela normalizada: {table}")
                seen_tables.add(table)

                utf8 = work / f"{table}.csv"
                enc, delim = recode_entry(zf, info, utf8)
                rows_src = independent_csv_rows(utf8, delim)

                destdir = bronze / table / f"competencia={args.competencia}"
                destdir.mkdir(parents=True, exist_ok=True)
                dest = destdir / "part-000.parquet"
                partial = dest.with_name(dest.name + f".partial.{os.getpid()}")
                partial.unlink(missing_ok=True)

                src_expr = f"""read_csv_auto(
                    {sqls(str(utf8))},
                    delim={sqls(delim)},
                    header=true,
                    all_varchar=true,
                    sample_size=-1,
                    null_padding=true
                )"""
                run_duck(f"""
COPY (
  SELECT *,
         {sqls(args.competencia)}::VARCHAR AS _source_competencia,
         {sqls(zp.name)}::VARCHAR AS _source_zip,
         {sqls(zip_sha)}::VARCHAR AS _source_zip_sha256,
         {sqls(info.filename)}::VARCHAR AS _source_file,
         current_timestamp AS _ingested_at
  FROM {src_expr}
)
TO {sqls(str(partial))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
                rows_pq = int(run_duck(
                    f"SELECT count(*) FROM read_parquet({sqls(str(partial))});",
                    capture=True).strip())
                if rows_src != rows_pq:
                    raise RuntimeError(
                        f"{table}: linhas CSV={rows_src} Parquet={rows_pq}")
                os.replace(partial, dest)
                rows_report.append((table, info.filename, enc, delim, rows_src,
                                    info.file_size, f"{info.CRC:08x}", str(dest)))
                print(f"[{idx}/{len(entries)}] OK {table} rows={rows_src} encoding={enc} delim={delim!r}")

        with manifest.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(["table", "source_file", "encoding", "delimiter", "rows",
                        "source_bytes", "source_crc32", "parquet"])
            w.writerows(rows_report)

        marker = state / f"qc_bronze_{args.competencia}.ok"
        marker.write_text("\n".join([
            f"competencia={args.competencia}",
            f"timestamp={ts}",
            f"zip={zp.name}",
            f"zip_sha256={zip_sha}",
            f"tables={len(rows_report)}",
            f"manifest={manifest}",
            "qc=independent_python_csv_record_count_vs_parquet_count",
            ""
        ]), encoding="utf-8")
        print(f"CNES_BRONZE_QC_OK {marker}")
        return 0
    finally:
        if args.keep_work:
            print(f"work={work}")
        else:
            shutil.rmtree(work, ignore_errors=True)

if __name__ == "__main__":
    raise SystemExit(main())
