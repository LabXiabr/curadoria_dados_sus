#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, os, subprocess
from pathlib import Path

def die(msg: str, code: int = 2) -> None:
    print(f"ERRO: {msg}")
    raise SystemExit(code)

def qi(s: str) -> str:
    return '"' + s.replace('"','""') + '"'

def qs(s: str) -> str:
    return "'" + s.replace("'","''") + "'"

def read_tsv(path: Path) -> list[dict[str,str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def write_tsv_atomic(path: Path, rows: list[dict[str,str]], fields: list[str]) -> None:
    tmp=path.with_name(path.name+f".partial.{os.getpid()}")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    os.replace(tmp,path)

def psql_count(service: str, schema: str, table: str) -> int:
    p=subprocess.run(
        ["psql",f"service={service}","-X","-At","-P","pager=off","-c",
         f"SELECT count(*) FROM {qi(schema)}.{qi(table)};"],
        text=True,capture_output=True)
    if p.returncode:
        die(f"count PostgreSQL falhou: {p.stderr.strip()}",20)
    return int(p.stdout.strip())

def parquet_count(path: Path) -> int:
    p=subprocess.run(
        ["duckdb","-csv","-noheader","-c",f"SELECT count(*) FROM read_parquet({qs(str(path))});"],
        text=True,capture_output=True)
    if p.returncode:
        die(f"count Parquet falhou: {p.stderr.strip()}",21)
    return int(p.stdout.strip())

def main() -> int:
    ap=argparse.ArgumentParser(description="Reprocessa um DBC do snapshot SIH staging e reconcilia o results.tsv")
    ap.add_argument("--lake-root",default="/dados/abertos/suslake")
    ap.add_argument("--run",help="Diretorio do overnight; padrao state/overnight/LATEST")
    ap.add_argument("--dbc",required=True,help="Nome exato do DBC, ex. SPRJ1910.dbc")
    ap.add_argument("--execute",action="store_true")
    args=ap.parse_args()

    lake=Path(args.lake_root).resolve()
    if args.run:
        run=Path(args.run).resolve()
    else:
        latest=lake/"state"/"overnight"/"LATEST"
        if not latest.is_file(): die(f"LATEST ausente: {latest}",3)
        run=Path(latest.read_text(encoding="utf-8").strip()).resolve()

    manifest_path=run/"sih_manifest.tsv"
    results_path=run/"sih_parquet_results.tsv"
    if not manifest_path.is_file() or not results_path.is_file():
        die(f"run sem manifest/results: {run}",4)

    manifest=read_tsv(manifest_path)
    matches=[r for r in manifest if (r.get("dbc") or "").lower()==args.dbc.lower()]
    if len(matches)!=1:
        die(f"DBC deve resolver exatamente 1 linha no manifesto; encontrados={len(matches)}",5)
    r=matches[0]

    service=r["service"]; sub=r["subsystem"]; uf=r["uf"]; comp=r["competencia"]
    schema=r["schema"]; table=r["table"]; dbc=r["dbc"]
    stem=Path(dbc).stem

    # Mantem exatamente o layout do overnight legado de 2026-11-15.
    out=(lake/"staging"/"psql_snapshot"/"sih"/f"service={service}"/f"subsystem={sub}"/
         f"competencia={comp}"/f"uf={uf}"/f"{stem}.parquet")
    out.parent.mkdir(parents=True,exist_ok=True)
    partial=out.with_name(f".{stem}.partial.{os.getpid()}.parquet")
    log=run/"parquet_logs"/f"{service}_{sub}_{uf}_{comp}_{stem}.repair.log"
    log.parent.mkdir(parents=True,exist_ok=True)

    src_rows=psql_count(service,schema,table)
    print(f"SIH_REPAIR_PLAN run={run}")
    print(f"source={service}:{schema}.{table} dbc={dbc} rows={src_rows}")
    print(f"dest={out}")
    print(f"log={log}")

    if out.is_file():
        pq=parquet_count(out)
        print(f"existing_parquet rows={pq}")
        if pq==src_rows:
            print("SKIP_OK: staging ja coincide com PostgreSQL")
        elif not args.execute:
            print("DRY_RUN: staging existente diverge; --execute substituiria somente apos gerar e validar partial")

    if not args.execute:
        print("DRY_RUN: nenhuma alteracao realizada")
        return 0

    partial.unlink(missing_ok=True)
    sql=f"""
LOAD postgres;
ATTACH 'service={service}' AS pg (TYPE postgres, READ_ONLY);
COPY (
  SELECT
    t.*,
    {qs(service)}::VARCHAR AS _suslake_source_service,
    {qs(dbc)}::VARCHAR AS _suslake_source_dbc,
    {qs(schema)}::VARCHAR AS _suslake_source_schema,
    {qs(table)}::VARCHAR AS _suslake_source_table,
    {qs(sub)}::VARCHAR AS _suslake_source_subsystem,
    {qs(uf)}::VARCHAR AS _suslake_source_uf,
    {qs(comp)}::VARCHAR AS _suslake_source_competencia
  FROM pg.{qi(schema)}.{qi(table)} t
)
TO {qs(str(partial))}
(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880);
DETACH pg;
"""
    with log.open("w",encoding="utf-8") as lf:
        p=subprocess.run(["duckdb","-c",sql],text=True,stdout=lf,stderr=subprocess.STDOUT)
    if p.returncode:
        partial.unlink(missing_ok=True)
        die(f"DuckDB falhou; veja {log}",30)

    pq_rows=parquet_count(partial)
    if pq_rows!=src_rows:
        partial.unlink(missing_ok=True)
        die(f"count diverge: pg={src_rows} parquet={pq_rows}; veja {log}",31)

    os.replace(partial,out)
    bytes_=out.stat().st_size

    results=read_tsv(results_path)
    fields=list(csv.DictReader(results_path.open(encoding="utf-8"),delimiter="\t").fieldnames or [])
    idx=[i for i,x in enumerate(results) if (x.get("dbc") or "").lower()==dbc.lower()]
    if len(idx)!=1:
        die(f"results deve conter exatamente 1 linha para {dbc}; encontrados={len(idx)}",32)
    x=results[idx[0]]
    # Compatibilidade com o formato legado.
    if "source_rows" in fields: x["source_rows"]=str(src_rows)
    if "parquet_rows" in fields: x["parquet_rows"]=str(pq_rows)
    if "rows_pg" in fields: x["rows_pg"]=str(src_rows)
    if "rows_parquet" in fields: x["rows_parquet"]=str(pq_rows)
    if "bytes" in fields: x["bytes"]=str(bytes_)
    if "bytes_parquet" in fields: x["bytes_parquet"]=str(bytes_)
    x["status"]="OK"
    x["path"]=str(out)
    write_tsv_atomic(results_path,results,fields)

    print(f"SIH_REPAIR_OK dbc={dbc} rows={pq_rows} bytes={bytes_} path={out}")
    print(f"RESULTS_UPDATED {results_path}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
