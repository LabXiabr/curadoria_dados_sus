#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, datetime as dt, os, re, subprocess, threading, tempfile, time, signal
import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.parquet as pq
import psycopg
from psycopg import sql
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from pathlib import Path

SERVICES=("bureta","pipeta")
FIELDS=["service","series","subsystem","uf","competencia","dbc","schema","table","status","rows_pg","rows_parquet","bytes_parquet","path","error"]
print_lock=threading.Lock()

def qid(s): return '"' + s.replace('"','""') + '"'
def qlit(s): return "'" + s.replace("'","''") + "'"

def psql(service,sql):
    p=subprocess.run(["psql",f"service={service}","-X","-At","-F","\t","-P","pager=off","-c",sql],text=True,capture_output=True,timeout=120)
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


# One persistent libpq connection per worker and service; no DuckDB CLI/extension.
_tls=threading.local()
_connections=[]
_conn_lock=threading.Lock()
stop=threading.Event()

def connection(service):
    cache=getattr(_tls,"connections",None)
    if cache is None:
        cache=_tls.connections={}
    con=cache.get(service)
    if con is None or con.closed or con.broken:
        con=psycopg.connect(f"service={service}",autocommit=True,connect_timeout=15,
            options="-c max_parallel_workers_per_gather=0 -c statement_timeout=1800000",
            application_name="suslabx_stage3_arrow")
        cache[service]=con
        with _conn_lock: _connections.append(con)
    return con

def arrow_type(name, mod):
    simple={"text":pa.string(),"varchar":pa.string(),"bpchar":pa.string(),
        "name":pa.string(),"int2":pa.int16(),"int4":pa.int32(),"int8":pa.int64(),
        "float4":pa.float32(),"float8":pa.float64(),"bool":pa.bool_(),
        "date":pa.date32(),"timestamp":pa.timestamp("us"),
        "timestamptz":pa.timestamp("us",tz="UTC"),"time":pa.time64("us")}
    if name in simple: return simple[name]
    if name=="numeric" and mod>=4:
        v=mod-4; precision=(v>>16)&65535; scale=v&2047
        if scale>=1024: scale-=2048
        if 0<=scale<=precision<=76:
            return (pa.decimal128 if precision<=38 else pa.decimal256)(precision,scale)
    raise ValueError(f"Tipo PostgreSQL sem mapeamento seguro: {name} typmod={mod}")

def get_schema(cur, r):
    cur.execute("""SELECT a.attname,t.typname,a.atttypmod
        FROM pg_attribute a JOIN pg_type t ON t.oid=a.atttypid
        WHERE a.attrelid=to_regclass(%s) AND a.attnum>0 AND NOT a.attisdropped
        ORDER BY a.attnum""", (qid(r['schema'])+'.'+qid(r['table']),))
    cols=cur.fetchall()
    if not cols: raise ValueError("Tabela ausente ou sem colunas")
    return pa.schema([(name,arrow_type(typ,mod)) for name,typ,mod in cols])

def compatible(a,b):
    # Ignore metadata and nullable flags. Existing DuckDB strings may be large_string.
    def norm(t): return pa.string() if pa.types.is_large_string(t) else t
    return a.names==b.names and all(norm(x.type)==norm(y.type) for x,y in zip(a,b))

def export_one(r,root,work):
    path=root/r["series"]/r["subsystem"].lower()/f"uf={r['uf']}"/f"competencia={r['competencia']}"/f"source_service={r['service']}"/f"source_schema={r['schema']}"/f"source_table={r['table']}"/f"{r['dbc']}.parquet"
    partial=path.with_name(path.name+f".partial.{os.getpid()}.{threading.get_ident()}")
    started=time.monotonic()
    try:
        path.parent.mkdir(parents=True,exist_ok=True)
        con=connection(r['service'])
        ident=sql.Identifier(r['schema'],r['table'])
        with con.transaction():
            with con.cursor() as cur:
                cur.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
                cur.execute("SET LOCAL DateStyle TO 'ISO, YMD'")
                cur.execute("SET LOCAL TIME ZONE 'UTC'")
                schema=get_schema(cur,r)
                cur.execute(sql.SQL("SELECT count(*) FROM {}").format(ident))
                rows=cur.fetchone()[0]
                if path.is_file():
                    old=pq.ParquetFile(path)
                    if old.metadata.num_rows!=rows or not compatible(old.schema_arrow,schema):
                        raise ValueError(f"Parquet existente diverge em contagem ou tipos; preservado: pg={rows} parquet={old.metadata.num_rows}")
                    return {**r,"status":"SKIP_OK","rows_pg":rows,"rows_parquet":rows,"bytes_parquet":path.stat().st_size,"path":str(path),"error":""}
                partial.unlink(missing_ok=True)
                with tempfile.TemporaryDirectory(prefix="copy_",dir=work) as temp:
                    source=Path(temp)/"source.csv"
                    if rows:
                        with source.open("wb") as f:
                            with cur.copy(sql.SQL("COPY {} TO STDOUT WITH (FORMAT CSV, HEADER TRUE, ENCODING 'UTF8')").format(ident)) as cp:
                                for block in cp:
                                    if stop.is_set(): raise RuntimeError("Execucao interrompida")
                                    f.write(block)
                    # Count and COPY use the same read-only snapshot.
                    with pq.ParquetWriter(partial,schema,compression="zstd") as writer:
                        if rows:
                            reader=pacsv.open_csv(source,
                                read_options=pacsv.ReadOptions(use_threads=False,block_size=8*1024*1024),
                                parse_options=pacsv.ParseOptions(newlines_in_values=True,ignore_empty_lines=False),
                                convert_options=pacsv.ConvertOptions(
                                    column_types=schema,strings_can_be_null=True,
                                    quoted_strings_can_be_null=False,null_values=[""],
                                    true_values=["t","true"],false_values=["f","false"]))
                            if not compatible(reader.schema,schema): raise ValueError("Schema CSV diverge")
                            for batch in reader:
                                if stop.is_set(): raise RuntimeError("Execucao interrompida")
                                writer.write_batch(batch,row_group_size=122880)
                    result=pq.ParquetFile(partial)
                    n=result.metadata.num_rows
                    if n!=rows or not compatible(result.schema_arrow,schema):
                        raise ValueError(f"CQ divergente: pg={rows} parquet={n}")
        if stop.is_set(): raise RuntimeError("Execucao interrompida")
        os.replace(partial,path)
        return {**r,"status":"OK","rows_pg":rows,"rows_parquet":n,"bytes_parquet":path.stat().st_size,"path":str(path),"error":""}
    except Exception as e:
        partial.unlink(missing_ok=True)
        return {**r,"status":"ERROR","rows_pg":"","rows_parquet":"","bytes_parquet":"","path":str(path),"error":str(e)}

def main():
    ap=argparse.ArgumentParser(description="Snapshot overnight SIA PostgreSQL -> Parquet staging SUSLabX")
    ap.add_argument("--lake-root",default="/dados/abertos/suslabx")
    ap.add_argument("--jobs",type=int,default=2)
    ap.add_argument("--subsystem",action="append",help="Filtra, ex. PA; pode repetir")
    ap.add_argument("--series",action="append",help="Filtra serie FTP, ex. 200801_; pode repetir")
    ap.add_argument("--limit",type=int,default=0)
    ap.add_argument("--plan-only",action="store_true",help="Gera manifesto/plano sem exportar Parquet nem alterar LATEST_SIA")
    ap.add_argument("--run-id")
    ap.add_argument("--service", choices=SERVICES, action="append")
    ap.add_argument("--dbc", action="append", help="Filtro pelo nome DBC")
    ap.add_argument("--max-consecutive-errors",type=int,default=10)
    ap.add_argument("--temp-root",help="Diretorio temporario para CSV (padrao: run/work)")
    args=ap.parse_args()
    if args.jobs<1 or args.max_consecutive_errors<1: raise SystemExit("jobs e max-consecutive-errors devem ser >=1")
    lake=Path(args.lake_root)
    rid=args.run_id or ("sia_"+dt.datetime.now().strftime("%Y%m%d_%H%M%S"))
    run=lake/"state"/"overnight"/rid; run.mkdir(parents=True,exist_ok=False)
    staging=lake/"staging"/"psql_snapshot"/"sia"
    rows=[]; lists={}
    for svc in (args.service or SERVICES):
        tb=latest(svc)
        if not tb: raise SystemExit(f"lista_dissemin ausente em {svc}")
        lists[svc]=tb; rows += manifest_rows(svc,tb)
    subs={x.upper() for x in (args.subsystem or [])}
    if subs: rows=[r for r in rows if r["subsystem"] in subs]
    series={x.lower() for x in (args.series or [])}
    if series: rows=[r for r in rows if r["series"].lower() in series]
    if args.dbc: rows=[r for r in rows if r["dbc"].lower() in {x.lower() for x in args.dbc}]
    # dedup canonico
    dedup={}
    for r in rows:
        dedup[(r["service"],r["series"],r["schema"],r["table"],r["dbc"])]=r
    rows=list(dedup.values())
    if args.limit>0: rows=rows[:args.limit]
    with (run/"sia_manifest.tsv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["service","series","subsystem","uf","competencia","dbc","schema","table"],delimiter="\t",lineterminator="\n"); w.writeheader(); w.writerows(rows)
    (run/"source_lists.txt").write_text("\n".join(f"{k}={v}" for k,v in lists.items())+"\n",encoding="utf-8")
    if args.plan_only:
        print(
            f"SIA_PLAN_ONLY run={run} files={len(rows)} jobs={args.jobs} "
            f"series={','.join(sorted(series)) if series else 'ALL'}"
        )
        for r in rows[:20]:
            print(
                f"PLAN {r['service']} {r['series']} {r['subsystem']} "
                f"{r['uf']} {r['competencia']} {r['dbc']} "
                f"{r['schema']}.{r['table']}"
            )
        if len(rows)>20:
            print(f"PLAN ... {len(rows)-20} arquivos adicionais")
        return 0
    if not rows: raise SystemExit("Manifesto sem tabelas para os filtros")
    work=Path(args.temp_root) if args.temp_root else run/"work"
    work.mkdir(parents=True,exist_ok=True)
    (lake/"state"/"overnight"/"LATEST_SIA").write_text(str(run.resolve())+"\n",encoding="utf-8")
    print(
        f"SIA_OVERNIGHT_START run={run} files={len(rows)} jobs={args.jobs} "
        f"series={','.join(sorted(series)) if series else 'ALL'}",
        flush=True
    )
    # Append incremental; at most jobs tasks in flight. Never enqueue the whole manifest.
    # Each checkpoint row is flushed and fsynced before reporting completion.
    def on_signal(signum,frame):
        stop.set()
    signal.signal(signal.SIGTERM,on_signal)
    signal.signal(signal.SIGINT,on_signal)
    ok=bad=done=consecutive=0
    t0=time.monotonic()
    iterator=iter(rows)
    try:
        with (run/"sia_parquet_results.tsv").open("w",encoding="utf-8",newline="") as f, ThreadPoolExecutor(max_workers=args.jobs) as ex:
            w=csv.DictWriter(f,fieldnames=FIELDS,delimiter="\t",lineterminator="\n")
            w.writeheader(); f.flush(); os.fsync(f.fileno())
            pending=set()
            def submit():
                if stop.is_set(): return
                r=next(iterator,None)
                if r is not None: pending.add(ex.submit(export_one,r,staging,work))
            for _ in range(args.jobs): submit()
            while pending:
                finished,pending=wait(pending,return_when=FIRST_COMPLETED)
                for future in finished:
                    x=future.result(); done+=1
                    good=x["status"] in {"OK","SKIP_OK"} and x["rows_pg"]==x["rows_parquet"]
                    if good: ok+=1; consecutive=0
                    else: bad+=1; consecutive+=1
                    # Single-line errors keep TSV line counters in the wrapper reliable.
                    x["error"]=" ".join(x["error"].split())
                    w.writerow(x); f.flush(); os.fsync(f.fileno())
                    rate=done/max(time.monotonic()-t0,0.001)*3600
                    print(f"[{done}/{len(rows)}] {x['status']} {x['service']} {x['series']} {x['subsystem']} {x['uf']} {x['competencia']} {x['dbc']} {x['error']} | files/h={rate:.1f}",flush=True)
                    if consecutive>=args.max_consecutive_errors and not stop.is_set():
                        print(f"CIRCUIT_BREAKER consecutive_errors={consecutive}",flush=True)
                        stop.set()
                for _ in finished: submit()
    finally:
        for con in _connections:
            con.close()
    complete=done==len(rows) and bad==0 and not stop.is_set()
    with (run/"main.log").open("w",encoding="utf-8") as f:
        f.write(f"SIA_FILES={len(rows)}\nSIA_OK={ok}\nSIA_BAD={bad}\nSIA_PENDING={len(rows)-done}\n")
        if complete: f.write("OVERNIGHT_DONE\n")
    print(f"SIA_OVERNIGHT_DONE files={len(rows)} ok={ok} bad={bad} pending={len(rows)-done} run={run}",flush=True)
    return 0 if complete else 10

if __name__=="__main__":
    raise SystemExit(main())
