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

ROOT=Path(__file__).resolve().parents[3]
CANONICAL=ROOT/"catalog"/"datasus_canonical_fields.tsv"
FIELDS=ROOT/"catalog"/"fields.tsv"

def die(msg: str, code: int=2):
    print(f"ERRO: {msg}",file=sys.stderr); raise SystemExit(code)

def read_tsv(path: Path):
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def sqls(v: str) -> str:
    return "'" + v.replace("'","''") + "'"

def qid(v: str) -> str:
    return '"' + v.replace('"','""') + '"'

def columns(path: Path) -> list[str]:
    p=subprocess.run(
        ["duckdb","-csv","-header","-c",f"DESCRIBE SELECT * FROM read_parquet({sqls(str(path))});"],
        text=True,capture_output=True,
    )
    if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return [r["column_name"] for r in csv.DictReader(p.stdout.splitlines())]

def count(path: Path) -> int:
    p=subprocess.run(
        ["duckdb","-noheader","-csv","-c",f"SELECT count(*) FROM read_parquet({sqls(str(path))});"],
        text=True,capture_output=True,
    )
    if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return int(p.stdout.strip() or 0)

def in_range(comp: str, lo: str, hi: str) -> bool:
    return (not comp or not lo or comp>=lo) and (not comp or not hi or comp<=hi)

def matches(cols: list[str], pats: list[str]) -> list[str]:
    out=[]
    for pat in pats:
        pat=pat.strip()
        if not pat: continue
        for col in cols:
            if fnmatch.fnmatchcase(col.upper(),pat.upper()) and col not in out:
                out.append(col)
    return out

def expr(cols: list[str]) -> str:
    if not cols: return "NULL::VARCHAR"
    if len(cols)==1: return f"CAST({qid(cols[0])} AS VARCHAR)"
    return "COALESCE(" + ",".join(f"NULLIF(CAST({qid(c)} AS VARCHAR),'')" for c in cols) + ")"

def main() -> int:
    ap=argparse.ArgumentParser(description="Bronze PostgreSQL -> Silver canonica")
    ap.add_argument("--profile",default="BURETA")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    ap.add_argument("--manifest",type=Path)
    ap.add_argument("--system",action="append")
    ap.add_argument("--subsystem",action="append")
    ap.add_argument("--from",dest="comp_from")
    ap.add_argument("--to",dest="comp_to")
    ap.add_argument("--max-tables",type=int,default=0)
    ap.add_argument("--execute",action="store_true")
    ap.add_argument("--force",action="store_true")
    args=ap.parse_args()

    lake=Path(args.lake_root).resolve(); state=lake/"state"/"psql"
    manifest=args.manifest or state/f"dissemin_bronze_{args.profile.lower()}.tsv"
    if not manifest.is_file(): die(f"manifest Bronze ausente: {manifest}",4)

    wanted_systems={x.upper() for x in (args.system or [])}
    wanted_subs={x.upper() for x in (args.subsystem or [])}
    selected=[]
    for r in read_tsv(manifest):
        if r.get("status")!="validated": continue
        if wanted_systems and r["system"].upper() not in wanted_systems: continue
        if wanted_subs and r["subsystem"].upper() not in wanted_subs: continue
        comp=r.get("source_competencia","")
        if (args.comp_from or args.comp_to) and not comp: continue
        if args.comp_from and comp<args.comp_from: continue
        if args.comp_to and comp>args.comp_to: continue
        selected.append(r)
    selected.sort(key=lambda r:(r["system"],r["subsystem"],r.get("source_competencia",""),r["table_schema"],r["table_name"]))
    if args.max_tables>0: selected=selected[:args.max_tables]

    print(f"PSQL_SILVER_PLAN profile={args.profile.upper()} tables={len(selected)} execute={int(args.execute)}")
    for r in selected:
        print("\t".join([r["system"],r["subsystem"],r.get("source_uf",""),r.get("source_competencia",""),r["table_schema"],r["table_name"]]))
    if not args.execute: return 0

    canonical=read_tsv(CANONICAL); field_catalog=read_tsv(FIELDS)
    out_manifest=state/f"dissemin_silver_{args.profile.lower()}.tsv"
    previous=read_tsv(out_manifest) if out_manifest.is_file() else []
    replacing={(r["table_schema"],r["table_name"]) for r in selected}
    out=[r for r in previous if (r.get("table_schema"),r.get("table_name")) not in replacing]

    for i,r in enumerate(selected,1):
        system=r["system"].upper(); sub=r["subsystem"].upper(); comp=r.get("source_competencia","")
        src=Path(r["bronze_path"])
        if not src.is_file(): raise RuntimeError(f"Bronze ausente: {src}")
        cols=columns(src); ci={c.casefold():c for c in cols}
        mapping: dict[str,list[str]]=defaultdict(list)

        for m in canonical:
            if m.get("system")!=system or m.get("subsystem","").upper()!=sub: continue
            if not m.get("canonical_field") or not in_range(comp,m.get("competence_min",""),m.get("competence_max","")): continue
            actual=ci.get(m.get("physical_field","").casefold())
            if actual and actual not in mapping[m["canonical_field"]]:
                mapping[m["canonical_field"]].append(actual)

        obj=f"fact_{system.lower()}_{sub.lower()}"
        scopes={obj,f"fact_{system.lower()}_*"}
        for f in field_catalog:
            if f.get("system")!=system or f.get("object_scope") not in scopes: continue
            name=f.get("field","")
            if not name or name in mapping: continue
            got=matches(cols,f.get("source_examples","").split("|"))
            if got: mapping[name].extend(got)

        if system=="SIA":
            curated={
                "nu_autorizacao":["PA_AUTORIZ","AP_AUTORIZ","AUTORIZ"],
                "nu_cnspcn":["NU_CNSPCN","CNSPCN","AP_CNSPCN","CNS_PAC"],
                "competencia_producao":["PA_CMP","AP_CMP","AP_MVM","DT_PROCESS"],
            }
            for name,pats in curated.items():
                if name not in mapping:
                    mapping[name].extend(matches(cols,pats))

        provenance=[c for c in cols if c.startswith("_source_") or c=="_migrated_at"]
        projection=[qid(c) for c in provenance]
        for name in sorted(mapping):
            projection.append(f"{expr(mapping[name])} AS {qid(name)}")
        if not projection: raise RuntimeError(f"sem campos Silver: {src}")

        uf=r.get("source_uf","") or "unknown"; out_comp=comp or "unknown"
        dest=(lake/"silver"/system.lower()/obj/f"uf={uf}"/f"competencia={out_comp}"/
              f"source_schema={r['table_schema']}"/f"source_table={r['table_name']}"/"part-000.parquet")
        dest.parent.mkdir(parents=True,exist_ok=True)
        partial=dest.with_name(dest.name+f".partial.{os.getpid()}")

        if dest.is_file() and not args.force:
            rows_out=count(dest)
        else:
            sql=("COPY (SELECT "+",".join(projection)+f" FROM read_parquet({sqls(str(src))})) "
                 +f"TO {sqls(str(partial))} (FORMAT PARQUET, COMPRESSION ZSTD);")
            p=subprocess.run(["duckdb","-c",sql],text=True,capture_output=True)
            if p.returncode:
                partial.unlink(missing_ok=True); raise RuntimeError(p.stderr.strip() or p.stdout.strip())
            os.replace(partial,dest); rows_out=count(dest)
        rows_in=int(r["rows_parquet"])
        if rows_in!=rows_out:
            raise RuntimeError(f"Silver alterou grain {src}: bronze={rows_in} silver={rows_out}")

        out.append({
            "profile":r["profile"],"system":system,"subsystem":sub,
            "table_schema":r["table_schema"],"table_name":r["table_name"],
            "source_uf":r.get("source_uf",""),"source_competencia":comp,
            "rows_bronze":str(rows_in),"rows_silver":str(rows_out),
            "canonical_fields":str(len(mapping)),"silver_path":str(dest),"status":"validated",
        })
        print(f"[{i}/{len(selected)}] PSQL_SILVER_OK {system}.{sub} {r['table_schema']}.{r['table_name']} rows={rows_out} fields={len(mapping)}")

    fields=["profile","system","subsystem","table_schema","table_name","source_uf",
            "source_competencia","rows_bronze","rows_silver","canonical_fields","silver_path","status"]
    out.sort(key=lambda r:(r["system"],r["subsystem"],r.get("source_competencia",""),r["table_schema"],r["table_name"]))
    tmp=out_manifest.with_name(out_manifest.name+f".partial.{os.getpid()}")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(out)
    os.replace(tmp,out_manifest)
    print(f"PSQL_SILVER_COMPLETE profile={args.profile.upper()} tables={len(selected)} manifest={out_manifest}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
