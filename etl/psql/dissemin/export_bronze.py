#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}",file=sys.stderr)
    raise SystemExit(code)

def qid(v: str) -> str:
    return '"' + v.replace('"','""') + '"'

def sqls(v: str) -> str:
    return "'" + v.replace("'","''") + "'"

def read_tsv(path: Path) -> list[dict[str,str]]:
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def load_env(path: Path) -> dict[str,str]:
    env=dict(os.environ)
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line=raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k,v=line.split("=",1); v=v.strip()
            if len(v)>=2 and v[0]==v[-1] and v[0] in {"'",'"'}:
                v=v[1:-1]
            env.setdefault(k.strip(),v)
    return env

def profile(env: dict[str,str], prefix: str) -> dict[str,str]:
    p=prefix.upper()
    names={"host":f"{p}_HOST","port":f"{p}_DB_PORT","db":f"{p}_DB_NAME",
           "user":f"{p}_DB_USER","password":f"{p}_DB_PASSWORD"}
    out={k:env.get(v,"") for k,v in names.items()}
    missing=[names[k] for k,v in out.items() if not v]
    if missing:
        die("variaveis ausentes: "+",".join(missing),41)
    return out

def psql_count(cfg: dict[str,str], schema: str, table: str) -> int:
    env=dict(os.environ); env["PGPASSWORD"]=cfg["password"]
    p=subprocess.run(
        ["psql","-h",cfg["host"],"-p",cfg["port"],"-U",cfg["user"],"-d",cfg["db"],
         "-Atq","-v","ON_ERROR_STOP=1","-c",
         f"SELECT count(*)::bigint FROM {qid(schema)}.{qid(table)};"],
        text=True,capture_output=True,env=env,
    )
    if p.returncode:
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"psql count rc={p.returncode}")
    return int(p.stdout.strip())

def uri(cfg: dict[str,str]) -> str:
    return (
        f"postgresql://{quote(cfg['user'],safe='.~_-')}:{quote(cfg['password'],safe='.~_-')}"
        f"@{cfg['host']}:{cfg['port']}/{quote(cfg['db'],safe='.~_-')}"
    )

def scalar(sql: str) -> int:
    p=subprocess.run(["duckdb","-noheader","-csv","-c",sql],text=True,capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return int(p.stdout.strip() or 0)

def yy_to_year(yy: int) -> int:
    return 1900+yy if yy>=80 else 2000+yy

def infer_period(system: str, subsystem: str, table: str) -> tuple[str,str]:
    if system not in {"SIA","SIH","CIH","CIHA"}:
        return "",""
    m=re.match(rf"^{re.escape(subsystem)}([A-Z]{{2}})(\d{{2}})(\d{{2}})",table.upper())
    if not m:
        return "",""
    yy=int(m.group(2)); mm=int(m.group(3))
    if not 1<=mm<=12:
        return "",""
    return m.group(1),f"{yy_to_year(yy):04d}{mm:02d}"

def main() -> int:
    ap=argparse.ArgumentParser(description="Transpoe PostgreSQL bdsus para Bronze Parquet sem DBC")
    ap.add_argument("--profile",default="BURETA")
    ap.add_argument("--env-file",type=Path,default=Path.home()/"etl_ftp_sus_parquet"/".env")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    ap.add_argument("--inventory",type=Path)
    ap.add_argument("--system",action="append")
    ap.add_argument("--subsystem",action="append")
    ap.add_argument("--uf",action="append")
    ap.add_argument("--schema",action="append")
    ap.add_argument("--table",action="append")
    ap.add_argument("--from",dest="comp_from")
    ap.add_argument("--to",dest="comp_to")
    ap.add_argument("--max-tables",type=int,default=0)
    ap.add_argument("--execute",action="store_true")
    ap.add_argument("--force",action="store_true")
    args=ap.parse_args()

    for cmd in ("psql","duckdb"):
        if not shutil.which(cmd): die(f"comando ausente: {cmd}",42)

    lake=Path(args.lake_root).resolve(); state=lake/"state"/"psql"
    inv=args.inventory or state/f"dissemin_inventory_{args.profile.lower()}.tsv"
    if not inv.is_file(): die(f"inventario ausente: {inv}",43)

    wanted_systems={x.upper() for x in (args.system or [])}
    wanted_subs={x.upper() for x in (args.subsystem or [])}
    wanted_ufs={x.upper() for x in (args.uf or [])}
    wanted_schema=set(args.schema or []); wanted_table=set(args.table or [])
    selected=[]
    for r in read_tsv(inv):
        if r.get("status")!="mapped": continue
        if wanted_systems and r["system"].upper() not in wanted_systems: continue
        if wanted_subs and r["subsystem"].upper() not in wanted_subs: continue
        if wanted_schema and r["table_schema"] not in wanted_schema: continue
        if wanted_table and r["table_name"] not in wanted_table: continue
        uf,comp=infer_period(r["system"],r["subsystem"],r["table_name"])
        r=dict(r); r["source_uf"]=uf; r["source_competencia"]=comp
        if wanted_ufs and uf.upper() not in wanted_ufs: continue
        if (args.comp_from or args.comp_to) and not comp: continue
        if args.comp_from and comp<args.comp_from: continue
        if args.comp_to and comp>args.comp_to: continue
        selected.append(r)
    selected.sort(key=lambda r:(r["system"],r["subsystem"],r["source_competencia"],r["table_schema"],r["table_name"]))
    if args.max_tables>0: selected=selected[:args.max_tables]

    print(f"PSQL_BRONZE_PLAN profile={args.profile.upper()} tables={len(selected)} execute={int(args.execute)}")
    for r in selected:
        print("\t".join([r["system"],r["subsystem"],r["source_uf"],r["source_competencia"],r["table_schema"],r["table_name"]]))
    if not args.execute: return 0
    if not selected: die("nenhuma tabela selecionada",4)

    cfg=profile(load_env(args.env_file),args.profile)
    pguri=uri(cfg)
    lake.joinpath("work","duckdb").mkdir(parents=True,exist_ok=True)
    test=subprocess.run(["duckdb","-c","LOAD postgres;"],text=True,capture_output=True)
    if test.returncode:
        test=subprocess.run(["duckdb","-c","INSTALL postgres; LOAD postgres;"],text=True,capture_output=True)
        if test.returncode: raise RuntimeError(test.stderr.strip() or test.stdout.strip())

    manifest=state/f"dissemin_bronze_{args.profile.lower()}.tsv"
    previous=read_tsv(manifest) if manifest.is_file() else []
    replacing={(r["table_schema"],r["table_name"]) for r in selected}
    out=[r for r in previous if (r.get("table_schema"),r.get("table_name")) not in replacing]

    for i,r in enumerate(selected,1):
        schema=r["table_schema"]; table=r["table_name"]
        uf=r["source_uf"] or "unknown"; comp=r["source_competencia"] or "unknown"
        dest=(lake/"bronze"/r["system"].lower()/r["subsystem"].lower()/
              f"uf={uf}"/f"competencia={comp}"/f"source_schema={schema}"/
              f"source_table={table}"/"part-000.parquet")
        dest.parent.mkdir(parents=True,exist_ok=True)
        partial=dest.with_name(dest.name+f".partial.{os.getpid()}")
        rows_pg=psql_count(cfg,schema,table)

        if dest.is_file() and not args.force:
            rows_pq=scalar(f"SELECT count(*) FROM read_parquet({sqls(str(dest))});")
            if rows_pg!=rows_pq:
                raise RuntimeError(f"Parquet existente diverge {schema}.{table}: psql={rows_pg} parquet={rows_pq}")
            print(f"[{i}/{len(selected)}] SKIP_QC_OK {schema}.{table} rows={rows_pg}")
        else:
            migrated=datetime.now(timezone.utc).isoformat()
            sql=f"""
LOAD postgres;
SET temp_directory={sqls(str(lake/'work'/'duckdb'))};
SET preserve_insertion_order=false;
ATTACH {sqls(pguri)} AS src (TYPE POSTGRES, READ_ONLY);
COPY (
 SELECT *,
        {sqls(args.profile.upper())}::VARCHAR AS _source_db_profile,
        {sqls(schema)}::VARCHAR AS _source_schema,
        {sqls(table)}::VARCHAR AS _source_table,
        {sqls(r['system'])}::VARCHAR AS _source_system,
        {sqls(r['subsystem'])}::VARCHAR AS _source_subsystem,
        {sqls(r['source_uf'])}::VARCHAR AS _source_uf,
        {sqls(r['source_competencia'])}::VARCHAR AS _source_competencia,
        {sqls(migrated)}::VARCHAR AS _migrated_at
 FROM src.{qid(schema)}.{qid(table)}
)
TO {sqls(str(partial))} (FORMAT PARQUET, COMPRESSION ZSTD);
"""
            p=subprocess.run(["duckdb"],input=sql,text=True,capture_output=True)
            if p.returncode:
                partial.unlink(missing_ok=True)
                if p.stdout: print(p.stdout,file=sys.stderr)
                if p.stderr: print(p.stderr,file=sys.stderr)
                raise RuntimeError(f"DuckDB export falhou {schema}.{table}")
            rows_pq=scalar(f"SELECT count(*) FROM read_parquet({sqls(str(partial))});")
            if rows_pg!=rows_pq:
                partial.unlink(missing_ok=True)
                raise RuntimeError(f"QC falhou {schema}.{table}: psql={rows_pg} parquet={rows_pq}")
            os.replace(partial,dest)
            print(f"[{i}/{len(selected)}] PSQL_BRONZE_OK {schema}.{table} rows={rows_pg}")

        out.append({
            "profile":args.profile.upper(),"system":r["system"],"subsystem":r["subsystem"],
            "table_schema":schema,"table_name":table,"source_uf":r["source_uf"],
            "source_competencia":r["source_competencia"],"rows_psql":str(rows_pg),
            "rows_parquet":str(rows_pq),"bytes_parquet":str(dest.stat().st_size),
            "bronze_path":str(dest),"status":"validated",
        })

    fields=["profile","system","subsystem","table_schema","table_name","source_uf",
            "source_competencia","rows_psql","rows_parquet","bytes_parquet","bronze_path","status"]
    out.sort(key=lambda r:(r["system"],r["subsystem"],r.get("source_competencia",""),r["table_schema"],r["table_name"]))
    tmp=manifest.with_name(manifest.name+f".partial.{os.getpid()}")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(out)
    os.replace(tmp,manifest)
    print(f"PSQL_BRONZE_COMPLETE profile={args.profile.upper()} tables={len(selected)} manifest={manifest}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
