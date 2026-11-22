#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import subprocess
from collections import defaultdict
from pathlib import Path

def die(msg:str,code:int=2)->None:
    print(f"ERRO: {msg}")
    raise SystemExit(code)

def qident(v:str)->str:
    return '"' + v.replace('"','""') + '"'

def qlit(v:str)->str:
    return "'" + v.replace("'","''") + "'"

def read_tsv(path:Path)->list[dict[str,str]]:
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def psql_count(service:str,schema:str,table:str)->int:
    sql=f"SELECT count(*) FROM {qident(schema)}.{qident(table)};"
    p=subprocess.run(["psql",f"service={service}","-X","-At","-P","pager=off","-c",sql],
                     text=True,capture_output=True)
    if p.returncode:
        die(f"psql {service} {schema}.{table}: {p.stderr.strip()}",30)
    return int(p.stdout.strip())

def parquet_count(path:Path)->int:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",
                      f"SELECT count(*) FROM read_parquet({qlit(str(path))});"],
                     text=True,capture_output=True)
    if p.returncode:
        die(f"duckdb {path}: {p.stderr.strip()}",31)
    return int(p.stdout.strip())

def sample(rows:list[dict[str,str]])->list[dict[str,str]]:
    groups=defaultdict(list)
    for r in rows:
        groups[(r["service"],r["series"],r["subsystem"])].append(r)
    out=[]; seen=set()
    for key,vals in sorted(groups.items()):
        vals=sorted(vals,key=lambda x:(x["competencia"],x["uf"],x["dbc"]))
        for r in (vals[0],vals[len(vals)//2],vals[-1]):
            k=(r["service"],r["schema"],r["table"],r["dbc"])
            if k not in seen:
                seen.add(k); out.append(r)
    return out

def main()->int:
    ap=argparse.ArgumentParser(description="CQ SIA PostgreSQL versus staging Parquet")
    ap.add_argument("--lake-root",default="/dados/abertos/suslabx")
    ap.add_argument("--run")
    ap.add_argument("--series",action="append")
    args=ap.parse_args()

    lake=Path(args.lake_root).resolve()
    if args.run:
        run=Path(args.run).resolve()
    else:
        latest=lake/"state"/"overnight"/"LATEST_SIA"
        if not latest.is_file(): die(f"LATEST_SIA ausente: {latest}",20)
        run=Path(latest.read_text(encoding="utf-8").strip()).resolve()

    manifest=run/"sia_manifest.tsv"; results=run/"sia_parquet_results.tsv"; mainlog=run/"main.log"
    for p in (manifest,results,mainlog):
        if not p.is_file(): die(f"run incompleto: {p}",21)
    if "OVERNIGHT_DONE" not in mainlog.read_text(encoding="utf-8",errors="replace").splitlines():
        die("snapshot SIA ainda nao concluiu",22)

    m=read_tsv(manifest); r=read_tsv(results)
    wanted={x.lower() for x in (args.series or [])}
    if wanted:
        m=[x for x in m if x.get("series","").lower() in wanted]
        r=[x for x in r if x.get("series","").lower() in wanted]

    if len(m)!=len(r):
        die(f"manifest/results divergem: manifest={len(m)} results={len(r)}",23)

    bad=[x for x in r if x.get("status") not in {"OK","SKIP_OK"} or
         not x.get("rows_pg") or not x.get("rows_parquet") or
         x.get("rows_pg")!=x.get("rows_parquet")]
    if bad: die(f"results SIA divergentes: {len(bad)}",24)

    partials=list((lake/"staging"/"psql_snapshot"/"sia").rglob("*.partial*"))
    if partials: die(f"partials SIA encontrados: {len(partials)}",25)

    picks=sample(r)
    out=[]; bad_live=0
    for x in picks:
        path=Path(x["path"])
        pg=psql_count(x["service"],x["schema"],x["table"])
        pq=parquet_count(path)
        expected=int(x["rows_parquet"])
        ok=int(pg==pq==expected); bad_live += 0 if ok else 1
        out.append({
            "service":x["service"],"series":x["series"],"subsystem":x["subsystem"],
            "uf":x["uf"],"competencia":x["competencia"],"dbc":x["dbc"],
            "schema":x["schema"],"table":x["table"],"rows_recorded":str(expected),
            "rows_pg_live":str(pg),"rows_parquet_live":str(pq),"ok":str(ok)
        })
        print(f"LIVE {x['service']} {x['series']} {x['subsystem']} {x['uf']} {x['competencia']} {x['dbc']} pg={pg} pq={pq} ok={ok}")

    state=lake/"state"/"sia"; state.mkdir(parents=True,exist_ok=True)
    ts=dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report=state/f"qc_source_staging_live_{ts}.tsv"
    fields=list(out[0].keys()) if out else []
    with report.open("w",encoding="utf-8",newline="") as f:
        if fields:
            w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
            w.writeheader(); w.writerows(out)
    if bad_live: die(f"amostra live SIA divergente: {bad_live}",40)

    marker=state/"qc_source_staging_live_current.ok"
    marker.write_text(
        f"timestamp={ts}\nrun={run}\nfiles_full_gate={len(r)}\nlive_sample={len(picks)}\nreport={report}\nstatus=validated\n",
        encoding="utf-8")
    print(f"SIA_SOURCE_STAGING_LIVE_QC_OK files={len(r)} sample={len(picks)} report={report}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
