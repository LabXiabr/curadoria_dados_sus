#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import fnmatch
import os
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
CANONICAL = ROOT / "catalog" / "datasus_canonical_fields.tsv"
FIELD_CATALOG = ROOT / "catalog" / "fields.tsv"

SYSTEMS = {
    "SIA": {"dir": "sia"},
    "SIH": {"dir": "sih"},
}

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"

def qid(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'

def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def duck_columns(path: Path) -> list[str]:
    sql = f"DESCRIBE SELECT * FROM read_parquet({sqls(str(path))});"
    p = subprocess.run(["duckdb", "-csv", "-header", "-c", sql], text=True, capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    rows = list(csv.DictReader(p.stdout.splitlines()))
    return [r["column_name"] for r in rows]

def duck_count(path: Path) -> int:
    p = subprocess.run(
        ["duckdb","-noheader","-csv","-c",
         f"SELECT count(*) FROM read_parquet({sqls(str(path))});"],
        text=True,capture_output=True
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return int(p.stdout.strip())

def comp_in_range(comp: str, lo: str, hi: str) -> bool:
    return (not lo or comp >= lo) and (not hi or comp <= hi)

def match_columns(columns: list[str], patterns: list[str]) -> list[str]:
    out = []
    for pat in patterns:
        p = pat.strip()
        if not p:
            continue
        if p == "file_competencia":
            if "_source_competencia" in columns and "_source_competencia" not in out:
                out.append("_source_competencia")
            continue
        for col in columns:
            if fnmatch.fnmatchcase(col.upper(), p.upper()) and col not in out:
                out.append(col)
    return out

def coalesce_expr(cols: list[str]) -> str:
    if not cols:
        return "NULL::VARCHAR"
    if len(cols) == 1:
        return qid(cols[0])
    return "COALESCE(" + ",".join(f"NULLIF({qid(c)}, '')" for c in cols) + ")"

def fact_name(system: str, sub: str) -> str:
    return f"fact_{system.lower()}_{sub.lower()}"

def main() -> int:
    ap = argparse.ArgumentParser(description="Bronze DBC -> Silver canonica SIA/SIH")
    ap.add_argument("--system", required=True, choices=sorted(SYSTEMS))
    ap.add_argument("--from", dest="comp_from")
    ap.add_argument("--to", dest="comp_to")
    ap.add_argument("--uf", action="append")
    ap.add_argument("--subsystem", action="append")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslabx"))
    args = ap.parse_args()

    system = args.system
    lake = Path(args.lake_root)
    state = lake / "state" / SYSTEMS[system]["dir"]
    manifest = state / "bronze_current.tsv"
    if not manifest.is_file():
        die(f"manifest Bronze ausente: {manifest}", 4)

    wanted_subs = {x.upper() for x in (args.subsystem or [])}
    wanted_ufs = {x.upper() for x in (args.uf or [])}
    selected = []
    for r in read_tsv(manifest):
        if r.get("status") != "validated":
            continue
        comp = r["competencia"]
        if wanted_subs and r["subsystem"].upper() not in wanted_subs:
            continue
        if wanted_ufs and r["uf"].upper() not in wanted_ufs:
            continue
        if args.comp_from and comp < args.comp_from:
            continue
        if args.comp_to and comp > args.comp_to:
            continue
        selected.append(r)

    canonical = [r for r in read_tsv(CANONICAL) if r["system"] == system and r.get("canonical_field")]
    field_catalog = [r for r in read_tsv(FIELD_CATALOG) if r["system"] == system]

    silver_root = lake / "silver" / SYSTEMS[system]["dir"]
    out_manifest = state / "silver_current.tsv"
    out_rows = []

    for idx, r in enumerate(selected, 1):
        src = Path(r["bronze_path"])
        if not src.is_file():
            raise RuntimeError(f"Bronze ausente: {src}")
        sub = r["subsystem"].upper()
        comp = r["competencia"]
        uf = r["uf"].upper()
        columns = duck_columns(src)
        colset = {c.casefold(): c for c in columns}

        mappings: dict[str, list[str]] = defaultdict(list)
        for m in canonical:
            if m["subsystem"].upper() != sub:
                continue
            if not comp_in_range(comp, m.get("competence_min",""), m.get("competence_max","")):
                continue
            actual = colset.get(m["physical_field"].casefold())
            if actual and actual not in mappings[m["canonical_field"]]:
                mappings[m["canonical_field"]].append(actual)

        obj = fact_name(system, sub)
        scopes = {obj, f"fact_{system.lower()}_*"}
        for f in field_catalog:
            if f["object_scope"] not in scopes or f["field"] in mappings:
                continue
            candidates = match_columns(columns, f.get("source_examples","").split("|"))
            if candidates:
                mappings[f["field"]].extend(candidates)

        provenance = [c for c in columns if c.startswith("_source_")]
        projections = [qid(c) for c in provenance]
        for name in sorted(mappings):
            projections.append(f"{coalesce_expr(mappings[name])} AS {qid(name)}")

        if not projections:
            raise RuntimeError(f"nenhuma coluna Silver projetada: {src}")

        dest = silver_root / obj / f"uf={uf}" / f"competencia={comp}" / "part-000.parquet"
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_name(dest.name + f".partial.{os.getpid()}")

        if dest.is_file() and not args.force:
            out_count = duck_count(dest)
        else:
            sql = (
                "COPY (SELECT " + ", ".join(projections)
                + f" FROM read_parquet({sqls(str(src))})) "
                + f"TO {sqls(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);"
            )
            p = subprocess.run(["duckdb","-c",sql],text=True,capture_output=True)
            if p.returncode:
                tmp.unlink(missing_ok=True)
                raise RuntimeError(p.stderr.strip() or p.stdout.strip())
            os.replace(tmp,dest)
            out_count = duck_count(dest)

        in_count = int(r["rows"])
        if in_count != out_count:
            raise RuntimeError(f"Silver alterou grain: {src} bronze={in_count} silver={out_count}")

        out_rows.append({
            "system":system,
            "object":obj,
            "subsystem":sub,
            "uf":uf,
            "competencia":comp,
            "source_sha256":r["source_sha256"],
            "bronze_path":str(src),
            "silver_path":str(dest),
            "rows":str(out_count),
            "canonical_fields":str(len(mappings)),
            "status":"validated",
        })
        print(f"[{idx}/{len(selected)}] SILVER_OK object={obj} uf={uf} competencia={comp} rows={out_count} fields={len(mappings)}")

    fields=[
        "system","object","subsystem","uf","competencia","source_sha256",
        "bronze_path","silver_path","rows","canonical_fields","status"
    ]
    with out_manifest.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader()
        w.writerows(sorted(out_rows,key=lambda x:(x["competencia"],x["object"],x["uf"])))

    (state/"silver_current.ok").write_text(
        "\n".join([
            f"system={system}",
            f"manifest={out_manifest}",
            f"files={len(out_rows)}",
            "status=complete",
            "",
        ]),
        encoding="utf-8",
    )
    print(f"DBC_SILVER_OK system={system} files={len(out_rows)} manifest={out_manifest}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
