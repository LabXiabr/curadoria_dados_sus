#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, datetime as dt, os, re, subprocess, threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

SERVICES=("bureta","pipeta")
FIELDS=["service","series","subsystem","uf","competencia","dbc","schema","table","status","rows_pg","rows_parquet","bytes_parquet","path","error"]
print_lock=threading.Lock()

def qid(s): return '"' + s.replace('"','""') + '"'
def qlit(s): return "'" + s.replace("'","''") + "'"

def psql(service,sql):
    p=subprocess.run(["psql",f"service={service}","-X","-At","-F","\t","-P","pager=off","-c",sql],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr.strip())
    return p.stdout

def latest(service):
    return psql(service,r"""SELECT table_schema||'.'||table_name
FROM information_schema.tables
WHERE table_schema='public' AND table_name ~ '^lista_dissemin_dbc_[0-9]{8}$'
ORDER BY table_name DESC LIMIT 1;""").strip()

def source_series(version, schema):
    version=(version or "").strip()
    if version:
        return version.lower()
    m=re.match(r"^sia_(\d{6}_\d{6}|\d{6}_)_", (schema or "").lower())
    if m:
        return m.group(1)
    raise RuntimeError(f"serie FTP SIA nao identificada: version={version!r} schema={schema!r}")

def manifest_rows(service,table):
    cutoff="< 202000" if service=="bureta" else ">= 202000"
    sql=f"""SELECT upper(coalesce(sg_versao,'')),upper(coalesce(sg_subsistema,'')),upper(coalesce(sg_uf,'')),
coalesce(nu_competencia,0)::text,lower(no_dbc_origem),no_schema,no_tabela
FROM {table}
WHERE upper(coalesce(sg_sistema,''))='SIA'
  AND coalesce(st_existe_sql,0)=1
  AND coalesce(nu_competencia,0) {cutoff}
  AND coalesce(no_schema,'')<>'' AND coalesce(no_tabela,'')<>''
ORDER BY 1,3,2,4;"""
    out=[]
    for line in psql(service,sql).splitlines():
        p=line.split("\t")
        if len(p)==7:
            out.append(dict(
                service=service,
                series=source_series(p[0], p[5]),
                subsystem=p[1],
                uf=p[2],
                competencia=p[3],
                dbc=p[4],
                schema=p[5],
                table=p[6],
            ))
    return out

def count_pg(r):
    return int(psql(r["service"],f"SELECT count(*) FROM {qid(r['schema'])}.{qid(r['table'])};").strip())

def count_pq(path):
    p=subprocess.run(["duckdb","-csv","-noheader","-c",f"SELECT count(*) FROM read_parquet({qlit(str(path))});"],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr.strip())
    return int(p.stdout.strip())

def export_one(r,root):
    path=root/r["series"]/r["subsystem"].lower()/f"uf={r['uf']}"/f"competencia={r['competencia']}"/f"source_service={r['service']}"/f"source_schema={r['schema']}"/f"source_table={r['table']}"/f"{r['dbc']}.parquet"
    path.parent.mkdir(parents=True,exist_ok=True)
    partial=path.with_name(path.name+f".partial.{os.getpid()}.{threading.get_ident()}")
    try:
        rows=count_pg(r)
        if path.is_file():
            pq=count_pq(path)
            if pq==rows:
                return {**r,"status":"SKIP_OK","rows_pg":rows,"rows_parquet":pq,"bytes_parquet":path.stat().st_size,"path":str(path),"error":""}
            raise RuntimeError(f"Parquet existente diverge: pg={rows} parquet={pq}")
        partial.unlink(missing_ok=True)
        sql=f"""INSTALL postgres; LOAD postgres;
ATTACH 'service={r['service']}' AS src (TYPE POSTGRES, READ_ONLY);
COPY (SELECT * FROM src.{qid(r['schema'])}.{qid(r['table'])})
TO {qlit(str(partial))} (FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880);"""
        p=subprocess.run(["duckdb","-c",sql],text=True,capture_output=True)
        if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip())
        pq=count_pq(partial)
        if pq!=rows: raise RuntimeError(f"count diverge: pg={rows} parquet={pq}")
        os.replace(partial,path)
        return {**r,"status":"OK","rows_pg":rows,"rows_parquet":pq,"bytes_parquet":path.stat().st_size,"path":str(path),"error":""}
    except Exception as e:
        partial.unlink(missing_ok=True)
        return {**r,"status":"ERROR","rows_pg":"","rows_parquet":"","bytes_parquet":"","path":str(path),"error":str(e)}

def write_tsv(path,rows):
    with path.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,delimiter="\t",lineterminator="\n"); w.writeheader(); w.writerows(rows)

def main():
    ap=argparse.ArgumentParser(description="Snapshot overnight SIA PostgreSQL -> Parquet staging SUSLabX")
    ap.add_argument("--lake-root",default="/dados/abertos/suslabx")
    ap.add_argument("--jobs",type=int,default=2)
    ap.add_argument("--subsystem",action="append",help="Filtra, ex. PA; pode repetir")
    ap.add_argument("--limit",type=int,default=0)
    ap.add_argument("--run-id")
    args=ap.parse_args()
    if args.jobs<1: raise SystemExit("--jobs deve ser >=1")
    lake=Path(args.lake_root)
    rid=args.run_id or ("sia_"+dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    run=lake/"state"/"overnight"/rid; run.mkdir(parents=True,exist_ok=True)
    staging=lake/"staging"/"psql_snapshot"/"sia"
    rows=[]; lists={}
    for svc in SERVICES:
        tb=latest(svc)
        if not tb: raise SystemExit(f"lista_dissemin ausente em {svc}")
        lists[svc]=tb; rows += manifest_rows(svc,tb)
    subs={x.upper() for x in (args.subsystem or [])}
    if subs: rows=[r for r in rows if r["subsystem"] in subs]
    # dedup canonico
    dedup={}
    for r in rows:
        dedup[(r["service"],r["series"],r["schema"],r["table"],r["dbc"])]=r
    rows=list(dedup.values())
    if args.limit>0: rows=rows[:args.limit]
    with (run/"sia_manifest.tsv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["service","series","subsystem","uf","competencia","dbc","schema","table"],delimiter="\t",lineterminator="\n"); w.writeheader(); w.writerows(rows)
    (run/"source_lists.txt").write_text("\n".join(f"{k}={v}" for k,v in lists.items())+"\n",encoding="utf-8")
    (lake/"state"/"overnight"/"LATEST_SIA").write_text(str(run.resolve())+"\n",encoding="utf-8")
    print(f"SIA_OVERNIGHT_START run={run} files={len(rows)} jobs={args.jobs}",flush=True)
    results=[]
    with ThreadPoolExecutor(max_workers=args.jobs) as ex:
        fut={ex.submit(export_one,r,staging):r for r in rows}
        for i,f in enumerate(as_completed(fut),1):
            x=f.result(); results.append(x)
            with print_lock:
                print(f"[{i}/{len(rows)}] {x['status']} {x['service']} {x['series']} {x['subsystem']} {x['uf']} {x['competencia']} {x['dbc']} {x['error']}",flush=True)
            write_tsv(run/"sia_parquet_results.tsv",sorted(results,key=lambda z:(z["series"],z["subsystem"],z["competencia"],z["uf"],z["dbc"])))
    bad=[r for r in results if r["status"] not in {"OK","SKIP_OK"} or str(r["rows_pg"])!=str(r["rows_parquet"])]
    with (run/"main.log").open("w",encoding="utf-8") as f:
        f.write(f"SIA_FILES={len(rows)}\nSIA_OK={len(rows)-len(bad)}\nSIA_BAD={len(bad)}\n")
        if not bad: f.write("OVERNIGHT_DONE\n")
    print(f"SIA_OVERNIGHT_DONE files={len(rows)} ok={len(rows)-len(bad)} bad={len(bad)} run={run}")
    return 0 if not bad else 10

if __name__=="__main__":
    raise SystemExit(main())
