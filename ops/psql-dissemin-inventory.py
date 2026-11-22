#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

SYSTEMS = ("SIA","SIH","CIH","CIHA","SIM","SINASC","SINAN")

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def load_env(path: Path) -> dict[str,str]:
    env = dict(os.environ)
    if path.is_file():
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k,v = line.split("=",1)
            v = v.strip()
            if len(v) >= 2 and v[0] == v[-1] and v[0] in {"'", '"'}:
                v = v[1:-1]
            env.setdefault(k.strip(),v)
    return env

def profile(env: dict[str,str], prefix: str) -> dict[str,str]:
    p = prefix.upper()
    names = {
        "host":f"{p}_HOST","port":f"{p}_DB_PORT","db":f"{p}_DB_NAME",
        "user":f"{p}_DB_USER","password":f"{p}_DB_PASSWORD",
    }
    out = {k:env.get(v,"") for k,v in names.items()}
    missing = [names[k] for k,v in out.items() if not v]
    if missing:
        die("variaveis ausentes: " + ",".join(missing),41)
    return out

def psql(cfg: dict[str,str], sql: str) -> str:
    env = dict(os.environ)
    env["PGPASSWORD"] = cfg["password"]
    p = subprocess.run(
        ["psql","-h",cfg["host"],"-p",cfg["port"],"-U",cfg["user"],
         "-d",cfg["db"],"-At","-F","\t","-v","ON_ERROR_STOP=1","-c",sql],
        text=True,capture_output=True,env=env,
    )
    if p.returncode:
        if p.stderr:
            print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"psql rc={p.returncode}")
    return p.stdout

def infer_system(schema: str) -> str:
    s = schema.lower()
    for system,prefix in (
        ("CIHA","ciha"),("SINASC","sinasc"),("SINAN","sinan"),
        ("SIH","sih"),("SIA","sia"),("SIM","sim"),("CIH","cih"),
    ):
        if s == prefix or s.startswith(prefix+"_"):
            return system
    return ""

def infer_subsystem(schema: str) -> str:
    return schema.rsplit("_",1)[-1].upper() if "_" in schema else ""

def main() -> int:
    ap = argparse.ArgumentParser(description="Inventaria PostgreSQL bdsus para transposicao lossless a Parquet")
    ap.add_argument("--profile",default="BURETA")
    ap.add_argument("--env-file",type=Path,default=Path.home()/"etl_ftp_sus_parquet"/".env")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslabx"))
    ap.add_argument("--system",action="append")
    args = ap.parse_args()

    env = load_env(args.env_file)
    cfg = profile(env,args.profile)
    wanted = {x.upper() for x in (args.system or SYSTEMS)}

    sql = r"""
WITH cols AS (
  SELECT table_schema,table_name,
         string_agg(lower(column_name),',' ORDER BY ordinal_position) AS columns,
         bool_or(lower(column_name)='nu_competencia') AS has_nu_competencia,
         bool_or(lower(column_name)='sg_uf') AS has_sg_uf,
         bool_or(lower(column_name) IN ('pa_autoriz','ap_autoriz')) AS has_autorizacao,
         bool_or(lower(column_name) IN ('cnspcn','nu_cnspcn','ap_cnspcn','cns_pac')) AS has_cnspcn
  FROM information_schema.columns
  WHERE table_schema NOT IN ('pg_catalog','information_schema')
  GROUP BY 1,2
), rels AS (
  SELECT n.nspname AS table_schema,c.relname AS table_name,
         pg_total_relation_size(c.oid)::bigint AS total_bytes,
         greatest(c.reltuples,0)::bigint AS estimated_rows
  FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
  WHERE c.relkind IN ('r','p')
    AND n.nspname NOT IN ('pg_catalog','information_schema')
)
SELECT r.table_schema,r.table_name,r.total_bytes,r.estimated_rows,
       coalesce(c.has_nu_competencia,false)::int,
       coalesce(c.has_sg_uf,false)::int,
       coalesce(c.has_autorizacao,false)::int,
       coalesce(c.has_cnspcn,false)::int,
       coalesce(c.columns,'')
FROM rels r LEFT JOIN cols c USING(table_schema,table_name)
WHERE lower(r.table_schema) ~ '^(sia|sih|cih|ciha|sim|sinasc|sinan)(_|$)'
ORDER BY r.total_bytes DESC,r.table_schema,r.table_name;
"""
    rows=[]; counts=Counter()
    for line in psql(cfg,sql).splitlines():
        parts=line.split("\t",8)
        if len(parts) != 9:
            continue
        schema,table,total_bytes,estimated_rows,has_comp,has_uf,has_auth,has_cns,columns=parts
        system=infer_system(schema)
        if not system or system not in wanted:
            continue
        subsystem=infer_subsystem(schema)
        rows.append({
            "profile":args.profile.upper(),"system":system,"subsystem":subsystem,
            "table_schema":schema,"table_name":table,"total_bytes":total_bytes,
            "estimated_rows":estimated_rows,"has_nu_competencia":has_comp,
            "has_sg_uf":has_uf,"has_autorizacao":has_auth,"has_cnspcn":has_cns,
            "columns":columns,"status":"mapped",
        })
        counts[(system,subsystem)] += 1

    state=Path(args.lake_root)/"state"/"psql"
    state.mkdir(parents=True,exist_ok=True)
    out=state/f"dissemin_inventory_{args.profile.lower()}.tsv"
    fields=["profile","system","subsystem","table_schema","table_name","total_bytes",
            "estimated_rows","has_nu_competencia","has_sg_uf","has_autorizacao",
            "has_cnspcn","columns","status"]
    with out.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    (state/f"dissemin_inventory_{args.profile.lower()}.ok").write_text(
        f"profile={args.profile.upper()}\nreport={out}\ntables={len(rows)}\nstatus=complete\n",
        encoding="utf-8",
    )
    print(f"PSQL_DISSEMIN_INVENTORY_OK profile={args.profile.upper()} tables={len(rows)} report={out}")
    for (system,subsystem),n in sorted(counts.items()):
        print(f"{system}\t{subsystem}\t{n}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
