#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
POLICY = ROOT / "systems" / "dissemin" / "source_policy.tsv"

SYSTEMS = {
    "SIA": {"policy": "SIASUS", "dir": "sia"},
    "SIH": {"policy": "SIHSUS", "dir": "sih"},
}

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"

def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def competencia_from_yymm(yymm: str) -> str:
    yy = int(yymm[:2])
    year = 1900 + yy if yy >= 80 else 2000 + yy
    mm = int(yymm[2:])
    if not 1 <= mm <= 12:
        raise ValueError(yymm)
    return f"{year:04d}{mm:02d}"

def load_subsystems(system: str) -> list[str]:
    path = ROOT / "systems" / system.lower() / "subsystems.tsv"
    return sorted(
        {r["subsystem"].upper() for r in read_tsv(path) if r.get("subsystem")},
        key=lambda x: (-len(x), x),
    )

def parse_filename(path: Path, subsystems: list[str]):
    stem = path.stem.upper()
    for sub in subsystems:
        if not stem.startswith(sub):
            continue
        m = re.fullmatch(r"([A-Z]{2})(\d{4})", stem[len(sub):])
        if not m:
            continue
        try:
            return sub, m.group(1), competencia_from_yymm(m.group(2))
        except ValueError:
            return None
    return None

def r_dbc_to_tsv(src: Path, dest: Path) -> int:
    code = r'''
args <- commandArgs(TRUE)
if (!requireNamespace("microdatasus", quietly=TRUE)) {
  cat("ERRO_MICRODATASUS_AUSENTE\n", file=stderr())
  quit(status=42)
}
x <- microdatasus::read_dbc(args[1], as_character=TRUE)
x[["_source_row_number"]] <- as.character(seq_len(nrow(x)))
write.table(
  x,
  file=args[2],
  sep="\t",
  quote=TRUE,
  row.names=FALSE,
  col.names=TRUE,
  na="",
  fileEncoding="UTF-8"
)
cat(sprintf("ROWS=%d\n", nrow(x)))
'''
    p = subprocess.run(
        ["Rscript", "-e", code, str(src), str(dest)],
        text=True, capture_output=True
    )
    if p.returncode:
        if p.stdout:
            print(p.stdout, file=sys.stderr)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        if p.returncode == 42:
            die("pacote R microdatasus ausente no host", 42)
        raise RuntimeError(f"Rscript read_dbc rc={p.returncode}")
    m = re.search(r"ROWS=(\d+)", p.stdout)
    if not m:
        raise RuntimeError("Rscript nao informou ROWS")
    return int(m.group(1))

def duck_count(path: Path) -> int:
    p = subprocess.run(
        ["duckdb", "-noheader", "-csv", "-c",
         f"SELECT count(*) FROM read_parquet({sqls(str(path))});"],
        text=True, capture_output=True
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return int(p.stdout.strip())

def tsv_to_parquet(tsv: Path, dest: Path, meta: dict[str, str]):
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + f".partial.{os.getpid()}")
    extras = ",\n".join(
        f"{sqls(v)}::VARCHAR AS {k}" for k, v in meta.items()
    )
    sql = f"""
COPY (
  SELECT *, {extras}
  FROM read_csv(
    {sqls(str(tsv))},
    delim='\\t',
    header=true,
    all_varchar=true,
    quote='"',
    escape='"',
    null_padding=true,
    ignore_errors=false
  )
)
TO {sqls(str(tmp))}
(FORMAT PARQUET, COMPRESSION ZSTD);
"""
    p = subprocess.run(["duckdb", "-c", sql], text=True, capture_output=True)
    if p.returncode:
        tmp.unlink(missing_ok=True)
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    os.replace(tmp, dest)

def main() -> int:
    ap = argparse.ArgumentParser(description="DBC canonico -> Bronze Parquet SIA/SIH")
    ap.add_argument("--system", required=True, choices=sorted(SYSTEMS))
    ap.add_argument("--from", dest="comp_from")
    ap.add_argument("--to", dest="comp_to")
    ap.add_argument("--uf", action="append")
    ap.add_argument("--subsystem", action="append")
    ap.add_argument("--max-files", type=int, default=0)
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"))
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)
    if not shutil.which("Rscript"):
        die("Rscript ausente", 3)

    system = args.system
    cfg = SYSTEMS[system]
    lake = Path(args.lake_root).resolve()
    raw_publicos = lake / "raw" / "dissemin" / "publicos"
    bronze_root = lake / "bronze" / cfg["dir"]
    state = lake / "state" / cfg["dir"]
    state.mkdir(parents=True, exist_ok=True)

    policies = [
        r for r in read_tsv(POLICY)
        if r["system"] == cfg["policy"] and r["etl_policy"] == "etl"
    ]
    subsystems = load_subsystems(system)
    wanted_subs = {x.upper() for x in (args.subsystem or [])}
    wanted_ufs = {x.upper() for x in (args.uf or [])}

    candidates = []
    for pol in policies:
        root = raw_publicos / pol["source_root"]
        if not root.is_dir():
            continue
        for p in sorted(root.rglob("*.dbc")):
            parsed = parse_filename(p, subsystems)
            if not parsed:
                continue
            sub, uf, comp = parsed
            if wanted_subs and sub not in wanted_subs:
                continue
            if wanted_ufs and uf not in wanted_ufs:
                continue
            if args.comp_from and comp < args.comp_from:
                continue
            if args.comp_to and comp > args.comp_to:
                continue
            candidates.append((comp, sub, uf, p))

    candidates.sort(key=lambda x: (x[0], x[1], x[2], str(x[3])))
    if args.max_files > 0:
        candidates = candidates[:args.max_files]

    print(f"DBC_BRONZE_PLAN system={system} files={len(candidates)} dry_run={int(args.dry_run)}")
    for comp, sub, uf, p in candidates:
        print(f"{comp}\t{sub}\t{uf}\t{p}")

    if args.dry_run:
        return 0
    if not candidates:
        die(f"nenhum DBC canonico encontrado em {raw_publicos}", 4)

    manifest_path = state / "bronze_current.tsv"
    previous = read_tsv(manifest_path) if manifest_path.is_file() else []
    selected_keys = set()
    new_rows = []

    for idx, (comp, sub, uf, src) in enumerate(candidates, 1):
        rel = src.relative_to(raw_publicos).as_posix()
        source_url = "ftp://ftp.datasus.gov.br/dissemin/publicos/" + rel
        digest = sha256(src)
        key = (sub, uf, comp, rel)
        selected_keys.add(key)
        dest = (
            bronze_root / sub.lower() / f"uf={uf}" / f"competencia={comp}"
            / f"sha256={digest}" / "part-000.parquet"
        )

        if dest.is_file() and not args.force:
            source_rows = duck_count(dest)
            print(f"[{idx}/{len(candidates)}] SKIP {src.name} rows={source_rows}")
        else:
            with tempfile.TemporaryDirectory(prefix=f"{system.lower()}_dbc_") as td:
                tsv = Path(td) / (src.stem + ".tsv")
                source_rows = r_dbc_to_tsv(src, tsv)
                meta = {
                    "_source_system": system,
                    "_source_subsystem": sub,
                    "_source_uf": uf,
                    "_source_competencia": comp,
                    "_source_file": src.name,
                    "_source_relative_path": rel,
                    "_source_url": source_url,
                    "_source_sha256": digest,
                }
                tsv_to_parquet(tsv, dest, meta)
            parquet_rows = duck_count(dest)
            if parquet_rows != source_rows:
                dest.unlink(missing_ok=True)
                raise RuntimeError(
                    f"row_count mismatch {src}: source={source_rows} parquet={parquet_rows}"
                )
            print(f"[{idx}/{len(candidates)}] OK {src.name} rows={source_rows}")

        new_rows.append({
            "system": system,
            "subsystem": sub,
            "uf": uf,
            "competencia": comp,
            "source_relative_path": rel,
            "source_file": src.name,
            "source_url": source_url,
            "source_sha256": digest,
            "bronze_path": str(dest),
            "rows": str(source_rows),
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "status": "validated",
        })

    merged = []
    for r in previous:
        k = (r.get("subsystem",""), r.get("uf",""), r.get("competencia",""), r.get("source_relative_path",""))
        if k not in selected_keys:
            merged.append(r)
    merged.extend(new_rows)
    merged.sort(key=lambda r: (r["competencia"], r["subsystem"], r["uf"], r["source_relative_path"]))

    fields = [
        "system","subsystem","uf","competencia","source_relative_path",
        "source_file","source_url","source_sha256","bronze_path","rows",
        "ingested_at","status"
    ]
    tmp = manifest_path.with_name(manifest_path.name + f".partial.{os.getpid()}")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(merged)
    os.replace(tmp, manifest_path)

    (state / "bronze_current.ok").write_text(
        "\n".join([
            f"system={system}",
            f"manifest={manifest_path}",
            f"selected_files={len(new_rows)}",
            f"total_files={len(merged)}",
            "status=complete",
            "",
        ]),
        encoding="utf-8",
    )
    print(f"DBC_BRONZE_OK system={system} selected_files={len(new_rows)} total_files={len(merged)}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
