#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

RE_ZIP = re.compile(r"^TabelaUnificada_(\d{6}).*\.zip$", re.I)
RE_COMP_DIR = re.compile(r"^competencia=(\d{6})$")
META_COLUMNS = {"_source_competencia", "_source_zip", "_source_sha256", "_ingested_at"}
VOLATILE_COLUMNS = {"dt_competencia"}

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sql_str(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"

def qi(value: str) -> str:
    return '"' + value.replace('"', '""') + '"'

def run_duck(sql: str, *, capture: bool = False) -> str:
    p = subprocess.run(["duckdb", "-csv", "-noheader", "-c", sql], text=True, capture_output=True)
    if p.returncode != 0:
        if p.stdout: print(p.stdout, file=sys.stderr)
        if p.stderr: print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"duckdb falhou rc={p.returncode}")
    return p.stdout if capture else ""

def read_marker(path: Path) -> dict[str, str]:
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def canonical_raw(raw: Path) -> dict[str, Path]:
    by_comp = defaultdict(list)
    for p in raw.glob("TabelaUnificada_*.zip"):
        m = RE_ZIP.match(p.name)
        if m: by_comp[m.group(1)].append(p)
    return {c: sorted(ps, key=lambda p: p.name)[-1] for c, ps in by_comp.items()}

def load_keys(path: Path) -> dict[str, list[str]]:
    out = {}
    with path.open(encoding="utf-8", newline="") as f:
        for r in csv.DictReader(f, delimiter="\t"):
            out[r["table"].lower()] = [x for x in r["primary_key"].split("|") if x]
    return out

def describe_union(files: list[Path]) -> list[str]:
    vals = ",".join(sql_str(str(p)) for p in files)
    text = run_duck(f"DESCRIBE SELECT * FROM read_parquet([{vals}], union_by_name=true);", capture=True)
    return [row[0] for row in csv.reader(text.splitlines()) if row]

def canonical_hash_expr(cols: list[str]) -> str:
    if not cols: return "sha256('')"
    parts = []
    for c in cols:
        q = qi(c)
        v = f"CAST({q} AS VARCHAR)"
        parts.append(f"CASE WHEN {q} IS NULL THEN '-1:' ELSE CAST(length({v}) AS VARCHAR) || ':' || {v} END || chr(31)")
    return "sha256(" + " || ".join(parts) + ")"

def read_parquet_expr(files: list[Path]) -> str:
    vals = ",\n        ".join(sql_str(str(p)) for p in files)
    return f"read_parquet([\n        {vals}\n    ], union_by_name=true)"

def table_files(table_dir: Path, allowed: set[str]) -> list[tuple[str, Path]]:
    out = []
    if not table_dir.is_dir(): return out
    for comp_dir in sorted(table_dir.iterdir()):
        if not comp_dir.is_dir(): continue
        m = RE_COMP_DIR.match(comp_dir.name)
        if not m or m.group(1) not in allowed: continue
        p = comp_dir / "part-000.parquet"
        if p.is_file(): out.append((m.group(1), p))
    return out

def write_snapshot_calendar(out: Path, snapshots: list[dict[str, str]]):
    values = []
    for i, s in enumerate(snapshots, start=1):
        values.append("(" + ",".join([
            sql_str(s["competencia"]), str(i), sql_str(s.get("zip","")),
            sql_str(s.get("zip_sha256","")), sql_str(s.get("timestamp","")),
            str(int(s.get("tables","0") or 0))
        ]) + ")")
    tmp = out.with_name(out.name + f".partial.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    run_duck(f"""
COPY (
  SELECT * FROM (VALUES {','.join(values)})
  AS t(competencia, snapshot_ordinal, source_zip, source_sha256, qc_timestamp, tables)
)
TO {sql_str(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
    os.replace(tmp, out)

def build_table(table, files_by_comp, keys, silver_root, latest_global):
    files = [p for _, p in files_by_comp]
    comps = [c for c, _ in files_by_comp]
    columns = describe_union(files)
    colset = set(columns)
    missing_keys = [k for k in keys if k not in colset]
    if missing_keys:
        raise RuntimeError(f"{table}: chaves ausentes: {missing_keys}")

    official = [c for c in columns if c not in META_COLUMNS and c != "competencia"]
    semantic = [c for c in official if c not in set(keys) and c not in VOLATILE_COLUMNS]
    has_dt = "dt_competencia" in colset
    hash_expr = canonical_hash_expr(semantic)
    read_expr = read_parquet_expr(files)
    cal_values = ",".join(f"({sql_str(c)},{i})" for i,c in enumerate(comps, start=1))

    key_select = ", ".join(qi(k) for k in keys)
    sem_select = ", ".join(qi(c) for c in semantic)
    select_fields = ", ".join([x for x in [key_select, sem_select] if x])
    if select_fields: select_fields += ", "

    dt_expr = "CAST(b.dt_competencia AS VARCHAR)" if has_dt else "NULL::VARCHAR"
    group_fields = [qi(k) for k in keys] + [qi(c) for c in semantic] + ["b._source_competencia", "cal.snapshot_ordinal", dt_expr]
    partition_fields = ", ".join([qi(k) for k in keys] + ["_semantic_hash", "_multiplicity"])
    temporal_group = ", ".join([qi(k) for k in keys] + [qi(c) for c in semantic] + ["_semantic_hash", "_multiplicity", "_island"])

    outdir = silver_root / table
    outdir.mkdir(parents=True, exist_ok=True)
    temporal = outdir / "temporal.parquet"
    tmp = temporal.with_name(temporal.name + f".partial.{os.getpid()}")
    tmp.unlink(missing_ok=True)

    run_duck(f"""
COPY (
WITH cal(competencia, snapshot_ordinal) AS (VALUES {cal_values}),
obs AS (
  SELECT
    {select_fields}
    {hash_expr} AS _semantic_hash,
    b._source_competencia,
    {dt_expr} AS _source_dt_competencia,
    cal.snapshot_ordinal,
    count(*)::BIGINT AS _multiplicity
  FROM {read_expr} b
  JOIN cal ON b._source_competencia = cal.competencia
  GROUP BY {', '.join(group_fields)}
),
marked AS (
  SELECT *,
         snapshot_ordinal - row_number() OVER (
           PARTITION BY {partition_fields}
           ORDER BY snapshot_ordinal
         ) AS _island
  FROM obs
)
SELECT
  {select_fields}
  _semantic_hash,
  min(_source_competencia) AS valid_from_competencia,
  max(_source_competencia) AS valid_to_competencia,
  count(*)::INTEGER AS _snapshot_count,
  _multiplicity,
  list(_source_competencia ORDER BY snapshot_ordinal) AS _observed_competencias,
  list(_source_dt_competencia ORDER BY snapshot_ordinal) AS _source_dt_competencias,
  (max(_source_competencia) = {sql_str(latest_global)}) AS _is_current
FROM marked
GROUP BY {temporal_group}
ORDER BY {', '.join(qi(k) for k in keys)}, valid_from_competencia, _semantic_hash
)
TO {sql_str(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
    os.replace(tmp, temporal)

    official_with_source = official + ["_source_competencia"]
    bronze_hash = canonical_hash_expr(official_with_source)
    recon_hash = canonical_hash_expr(official_with_source)
    recon_dt = "unnest(_source_dt_competencias) AS dt_competencia," if has_dt else "unnest(_source_dt_competencias) AS _ignored_dt_competencia,"
    recon_fields = ", ".join([qi(k) for k in keys] + [qi(c) for c in semantic])
    if recon_fields: recon_fields += ", "

    qcout = run_duck(f"""
WITH bronze AS (
  SELECT * FROM {read_expr}
),
b AS (
  SELECT {bronze_hash} AS h, count(*)::BIGINT AS n
  FROM bronze GROUP BY h
),
recon0 AS (
  SELECT
    {recon_fields}
    unnest(_observed_competencias) AS _source_competencia,
    {recon_dt}
    _multiplicity
  FROM read_parquet({sql_str(str(temporal))})
),
r AS (
  SELECT {recon_hash} AS h, sum(_multiplicity)::BIGINT AS n
  FROM recon0 GROUP BY h
),
d AS (
  SELECT coalesce(b.h,r.h) AS h, coalesce(b.n,0) AS bn, coalesce(r.n,0) AS rn
  FROM b FULL OUTER JOIN r USING(h)
  WHERE coalesce(b.n,0) <> coalesce(r.n,0)
)
SELECT
  (SELECT count(*) FROM bronze),
  (SELECT coalesce(sum(_multiplicity),0) FROM recon0),
  (SELECT count(*) FROM d),
  (SELECT count(*) FROM read_parquet({sql_str(str(temporal))}));
""", capture=True).strip()

    row = next(csv.reader([qcout])) if qcout else []
    if len(row) != 4:
        raise RuntimeError(f"{table}: QC inesperado: {qcout!r}")
    bronze_rows, reconstructed_rows, diffs, temporal_rows = map(int, row)
    if bronze_rows != reconstructed_rows or diffs != 0:
        raise RuntimeError(f"{table}: QC lossless falhou bronze={bronze_rows} recon={reconstructed_rows} diffs={diffs}")

    return {
      "table":table, "snapshots_available":str(len(comps)),
      "first_competencia":comps[0], "last_competencia":comps[-1],
      "bronze_rows":str(bronze_rows), "temporal_rows":str(temporal_rows),
      "reconstructed_rows":str(reconstructed_rows),
      "differing_hash_groups":str(diffs),
      "semantic_columns":str(len(semantic)), "key":"|".join(keys), "status":"ok"
    }

def main():
    ap = argparse.ArgumentParser(description="SIGTAP Silver temporal lossless com controle de volatilidade")
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    ap.add_argument("--keys", type=Path)
    args = ap.parse_args()

    if not shutil.which("duckdb"): die("duckdb CLI ausente")
    root = Path(__file__).resolve().parents[3]
    keys_path = args.keys or root / "systems" / "sigtap" / "keys.tsv"
    lake = Path(args.lake_root)
    raw = lake/"raw"/"sigtap"/"zip"
    bronze = lake/"bronze"/"sigtap"
    silver = lake/"silver"/"sigtap"
    state = lake/"state"/"sigtap"
    silver.mkdir(parents=True, exist_ok=True); state.mkdir(parents=True, exist_ok=True)

    canonical = canonical_raw(raw)
    if not canonical: die(f"nenhum ZIP Raw SIGTAP em {raw}")

    snapshots=[]; incomplete=[]
    for comp,zp in sorted(canonical.items()):
        marker=state/f"qc_raw_bronze_{comp}.ok"
        if not marker.is_file():
            incomplete.append(f"{comp}: marker ausente"); continue
        mm=read_marker(marker)
        if mm.get("zip") != zp.name:
            incomplete.append(f"{comp}: marker={mm.get('zip','')} canonico={zp.name}"); continue
        snapshots.append({"competencia":comp, **mm})

    if incomplete:
        print("Bronze ainda nao esta completa/homologada:", file=sys.stderr)
        for x in incomplete[:50]: print(f"  {x}", file=sys.stderr)
        if len(incomplete)>50: print(f"  ... mais {len(incomplete)-50}", file=sys.stderr)
        die("Silver bloqueada ate toda competencia canonica passar Raw->Bronze QC",20)

    allowed={s["competencia"] for s in snapshots}
    latest_global=max(allowed)
    write_snapshot_calendar(silver/"_snapshots.parquet", snapshots)

    key_registry=load_keys(keys_path)
    tables=sorted(p.name for p in bronze.iterdir() if p.is_dir())
    if not tables: die(f"nenhuma tabela Bronze em {bronze}")
    unknown=[t for t in tables if t not in key_registry]
    if unknown: die("tabelas Bronze sem chave: "+", ".join(unknown),21)

    report_rows=[]; failures=[]
    for i,table in enumerate(tables,start=1):
        tfiles=table_files(bronze/table,allowed)
        if not tfiles: continue
        print(f"[{i}/{len(tables)}] SILVER {table} snapshots={len(tfiles)}")
        try:
            r=build_table(table,tfiles,key_registry[table],silver,latest_global)
            report_rows.append(r)
            print(f"  OK bronze={r['bronze_rows']} temporal={r['temporal_rows']}")
        except Exception as e:
            failures.append((table,str(e)))
            print(f"  ERRO {e}",file=sys.stderr)

    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    report=state/f"silver_temporal_{ts}.tsv"
    fields=["table","snapshots_available","first_competencia","last_competencia","bronze_rows","temporal_rows","reconstructed_rows","differing_hash_groups","semantic_columns","key","status"]
    with report.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(report_rows)
        for table,_ in failures: w.writerow({"table":table,"status":"failed"})

    print(f"Relatorio: {report}")
    if failures: die(f"Silver incompleta: {len(failures)} tabelas falharam",30)

    marker=state/"silver_complete.ok"
    marker.write_text("\n".join([
      f"timestamp={ts}", f"competencias={len(snapshots)}",
      f"first_competencia={min(allowed)}", f"last_competencia={latest_global}",
      f"tables={len(report_rows)}", f"report={report}",
      "policy=semantic_hash_excludes_dt_competencia_and_etl_provenance",
      "qc=lossless_multiset_reconstruction",""
    ]),encoding="utf-8")
    print(f"SILVER_COMPLETE_OK {marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
