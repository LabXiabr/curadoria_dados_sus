#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import os
import subprocess
from collections import defaultdict
from pathlib import Path

SERVICES=("bureta","pipeta")
VALID_PROMOTION={"OK","SKIP_QC_OK"}

def die(msg:str,code:int=2)->None:
    print(f"ERRO: {msg}")
    raise SystemExit(code)

def psql(service:str,sql:str)->str:
    p=subprocess.run(
        ["psql",f"service={service}","-X","-At","-F","\t","-P","pager=off","-c",sql],
        text=True,capture_output=True)
    if p.returncode:
        die(f"psql service={service}: {p.stderr.strip()}",20)
    return p.stdout

def latest_list(service:str)->str:
    return psql(service,r"""
SELECT table_schema||'.'||table_name
FROM information_schema.tables
WHERE table_schema='public' AND table_name ~ '^lista_dissemin_dbc_[0-9]{8}$'
ORDER BY table_name DESC LIMIT 1;
""").strip()

def expected_modern()->dict[str,dict[str,str]]:
    rows={}
    for service in SERVICES:
        tb=latest_list(service)
        cutoff="< 202000" if service=="bureta" else ">= 202000"
        sql=f"""
SELECT lower(coalesce(no_dbc_origem,'')),
       upper(coalesce(sg_subsistema,'')),
       upper(coalesce(sg_uf,'')),
       coalesce(nu_competencia,0)::text,
       coalesce(st_existe_sql,0)::text
FROM {tb}
WHERE upper(coalesce(sg_sistema,''))='SIH'
  AND lower(coalesce(sg_versao,''))='200801_'
  AND coalesce(nu_competencia,0) {cutoff}
  AND coalesce(no_dbc_origem,'')<>''
ORDER BY 1;
"""
        for line in psql(service,sql).splitlines():
            p=line.split("\t")
            if len(p)!=5: continue
            dbc=p[0]
            r=dict(service=service,dbc=dbc,subsystem=p[1],uf=p[2],
                   competencia=p[3],sql_present=p[4])
            old=rows.get(dbc)
            if old and old!=r:
                die(f"DBC esperado duplicado com metadados divergentes: {dbc}",21)
            rows[dbc]=r
    return rows

def read_tsv(path:Path)->list[dict[str,str]]:
    if not path.is_file(): return []
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def duck_count(path:Path)->int:
    q="'" + str(path).replace("'","''") + "'"
    p=subprocess.run(["duckdb","-csv","-noheader","-c",f"SELECT count(*) FROM read_parquet({q});"],
                     text=True,capture_output=True)
    if p.returncode:
        die(f"DuckDB falhou {path}: {p.stderr.strip()}",30)
    return int(p.stdout.strip() or 0)

def main()->int:
    ap=argparse.ArgumentParser(description="CQ de completude Bronze SIH serie 200801_")
    ap.add_argument("--lake-root",default="/dados/abertos/suslabx")
    args=ap.parse_args()

    lake=Path(args.lake_root).resolve()
    root=lake/"bronze"/"sih"/"200801_"
    if not root.is_dir():
        die(f"Bronze SIH moderno ausente: {root}",3)

    exp=expected_modern()
    found=defaultdict(list)
    for p in root.rglob("*.parquet"):
        if p.name.lower().endswith(".dbc.parquet"):
            dbc=p.name[:-len(".parquet")].lower()
            found[dbc].append(p)

    partials=list(root.rglob("*.partial*"))
    promotion_reports=list((lake/"state"/"sih").glob("bronze_from_staging_*.tsv"))
    if not promotion_reports:
        die("relatorio bronze_from_staging ausente",31)
    promotion=max(promotion_reports,key=lambda p:p.stat().st_mtime)
    prom={r.get("dbc","").lower():r for r in read_tsv(promotion) if r.get("dbc")}

    zero_report=lake/"state"/"sih"/"direct_zero_sources_current.tsv"
    zero={r.get("dbc","").lower():r for r in read_tsv(zero_report) if r.get("dbc")}

    outrows=[]
    bad=0
    for dbc,r in sorted(exp.items(),key=lambda kv:(kv[1]["subsystem"],kv[1]["competencia"],kv[1]["uf"],kv[0])):
        paths=found.get(dbc,[])
        status="ok"
        detail=""
        source_kind="psql_snapshot" if r["sql_present"]=="1" else "raw_dbc_zero"

        if len(paths)!=1:
            status="missing_bronze" if not paths else "duplicate_bronze"
            detail=f"paths={len(paths)}"
        elif r["sql_present"]=="1":
            pr=prom.get(dbc)
            if not pr:
                status="missing_promotion_report"
            elif pr.get("promotion_status") not in VALID_PROMOTION:
                status="bad_promotion_status"; detail=pr.get("promotion_status","")
            elif str(pr.get("rows_parquet",""))!=str(pr.get("rows_bronze","")):
                status="row_count_mismatch"
                detail=f"staging={pr.get('rows_parquet','')} bronze={pr.get('rows_bronze','')}"
        else:
            zr=zero.get(dbc)
            if not zr:
                status="missing_zero_report"
            elif zr.get("status") not in {"OK","SKIP_OK"}:
                status="bad_zero_status"; detail=zr.get("status","")
            elif zr.get("verified_records")!="0":
                status="source_not_zero"; detail=zr.get("verified_records","")
            elif duck_count(paths[0])!=0:
                status="bronze_not_zero"

        if status!="ok": bad+=1
        outrows.append({
            **r,"source_kind":source_kind,
            "bronze_path":str(paths[0]) if len(paths)==1 else "|".join(map(str,paths)),
            "status":status,"detail":detail
        })

    extra=sorted(set(found)-set(exp))
    bad += len(extra) + len(partials)

    state=lake/"state"/"sih"; state.mkdir(parents=True,exist_ok=True)
    ts=dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report=state/f"qc_bronze_modern_{ts}.tsv"
    fields=["service","dbc","subsystem","uf","competencia","sql_present","source_kind","bronze_path","status","detail"]
    with report.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(outrows)

    sql_count=sum(r["sql_present"]=="1" for r in exp.values())
    zero_count=len(exp)-sql_count
    print(
        f"SIH_BRONZE_MODERN_QC expected={len(exp)} sql_present={sql_count} "
        f"direct_zero={zero_count} found={len(found)} extra={len(extra)} "
        f"partials={len(partials)} bad={bad} report={report}"
    )
    if extra:
        print("EXTRA_DBC " + " ".join(extra[:50]))
    if partials:
        print(f"PARTIALS {len(partials)} primeiro={partials[0]}")
    if bad:
        return 10

    marker=state/"qc_bronze_modern_current.ok"
    tmp=marker.with_name(marker.name+f".partial.{os.getpid()}")
    tmp.write_text(
        "\n".join([
            f"timestamp={ts}",
            "series=200801_",
            f"expected={len(exp)}",
            f"sql_present={sql_count}",
            f"direct_zero={zero_count}",
            f"promotion_report={promotion}",
            f"zero_report={zero_report}",
            f"report={report}",
            "status=validated",""
        ]),encoding="utf-8")
    os.replace(tmp,marker)
    print(f"SIH_BRONZE_MODERN_QC_OK marker={marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
