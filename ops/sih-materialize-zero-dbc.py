#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

SERVICES=("bureta","pipeta")
FIELDS=[
    "service","subsystem","uf","competencia","dbc","qt_registro_dbc_catalog",
    "raw_path","sha256_raw","verified_records","template_bronze","bronze_path","status"
]

def die(msg:str, code:int=2)->None:
    print(f"ERRO: {msg}")
    raise SystemExit(code)

def qlit(v:str)->str:
    return "'" + str(v).replace("'","''") + "'"

def psql(service:str, sql:str)->str:
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

def missing_modern()->list[dict[str,str]]:
    rows=[]
    for service in SERVICES:
        table=latest_list(service)
        if not table:
            die(f"lista_dissemin ausente em {service}",21)
        cutoff="< 202000" if service=="bureta" else ">= 202000"
        sql=f"""
SELECT upper(coalesce(sg_subsistema,'')),
       upper(coalesce(sg_uf,'')),
       coalesce(nu_competencia,0)::text,
       lower(coalesce(no_dbc_origem,'')),
       coalesce(qt_registro_dbc,-1)::text
FROM {table}
WHERE upper(coalesce(sg_sistema,''))='SIH'
  AND lower(coalesce(sg_versao,''))='200801_'
  AND coalesce(nu_competencia,0) {cutoff}
  AND coalesce(st_existe_sql,0)<>1
  AND coalesce(no_dbc_origem,'')<>''
ORDER BY 1,2,3,4;
"""
        for line in psql(service,sql).splitlines():
            p=line.split("\t")
            if len(p)==5:
                rows.append(dict(
                    service=service,subsystem=p[0],uf=p[1],competencia=p[2],
                    dbc=p[3],qt_registro_dbc_catalog=p[4]))
    dedup={}
    for r in rows:
        dedup[(r["dbc"],r["subsystem"],r["uf"],r["competencia"])]=r
    return list(dedup.values())

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(4*1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def parse_dbview_records(path:Path)->int|None:
    p=subprocess.run(["dbview","-i","-o",str(path)],text=True,capture_output=True)
    txt=(p.stdout or "")+"\n"+(p.stderr or "")
    m=re.search(r"\brecs\s*[:=]?\s*(\d+)\b",txt,re.I)
    if not m:
        m=re.search(r"\b(\d+)\s+recs\b",txt,re.I)
    return int(m.group(1)) if m else None

def locate_converter()->Path:
    env=os.environ.get("DBF2DBC_EXE","").strip()
    if env and Path(env).is_file():
        return Path(env)
    if not shutil.which("locate"):
        die("dbf2dbc.exe nao informado em DBF2DBC_EXE e comando locate ausente",31)
    p=subprocess.run(["locate","-i","TAB415/dbf2dbc.exe"],text=True,capture_output=True)
    candidates=[Path(x.strip()) for x in p.stdout.splitlines() if x.strip()]
    candidates=[x for x in candidates if x.is_file()]
    if not candidates:
        die("dbf2dbc.exe nao localizado; defina DBF2DBC_EXE",31)
    return candidates[-1]

def records_via_wine(dbc:Path,lake:Path)->int:
    if not shutil.which("wine") or not shutil.which("wineboot"):
        die("wine/wineboot ausente para validar DBC",32)
    exe=locate_converter()
    fp=subprocess.run(["file","-b",str(exe)],text=True,capture_output=True)
    arch="win64" if "PE32+" in fp.stdout else "win32"
    prefix=Path(os.environ.get("WINEPREFIX_ETL",str(lake/"work"/f"wine-{arch}")))
    prefix.mkdir(parents=True,exist_ok=True)
    env=os.environ.copy()
    env.pop("WINEARCH",None); env.pop("WINEPREFIX",None)
    env.update({"WINEDEBUG":"-all","WINEARCH":arch,"WINEPREFIX":str(prefix)})
    if not (prefix/"system.reg").is_file():
        p=subprocess.run(["wineboot","-u"],env=env,text=True,capture_output=True)
        if p.returncode:
            die(f"wineboot falhou: {p.stderr.strip()}",33)
    workroot=lake/"work"/"sih_zero_source"
    workroot.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="dbc_",dir=workroot) as td:
        td=Path(td)
        local=td/dbc.name
        shutil.copy2(dbc,local)
        p=subprocess.run(["wine",str(exe),local.name],cwd=td,env=env,text=True,capture_output=True)
        if p.returncode:
            die(f"Wine dbf2dbc falhou para {dbc.name}: {p.stderr.strip()}",34)
        dbfs=[x for x in td.iterdir() if x.is_file() and x.suffix.lower()==".dbf"]
        if not dbfs:
            die(f"DBF nao gerado para {dbc.name}",35)
        n=parse_dbview_records(dbfs[0])
        if n is None:
            die(f"dbview nao retornou contagem para {dbfs[0]}",36)
        return n

def verify_records(dbc:Path,lake:Path)->int:
    n=parse_dbview_records(dbc)
    return n if n is not None else records_via_wine(dbc,lake)

def raw_path(lake:Path,dbc:str)->Path:
    root=lake/"raw"/"dissemin"/"dbc"/"SIHSUS"/"200801_"/"Dados"
    exact=root/dbc.upper().replace(".DBC",".dbc")
    if exact.is_file():
        return exact
    matches=[p for p in root.glob("*") if p.is_file() and p.name.lower()==dbc.lower()]
    if len(matches)!=1:
        die(f"Raw canonico deve conter exatamente um {dbc}; encontrados={len(matches)} em {root}",40)
    return matches[0]

def part_value(path:Path,key:str)->str:
    pref=key+"="
    for p in path.parts:
        if p.startswith(pref):
            return p[len(pref):]
    return ""

def ym(competencia:str)->int:
    return int(competencia[:4])*12+int(competencia[4:6])-1

def choose_template(root:Path,subsystem:str,uf:str,comp:str,target_name:str)->Path:
    base=root/subsystem.lower()
    candidates=[p for p in base.rglob("*.dbc.parquet") if p.name.lower()!=target_name.lower()+".parquet"]
    if not candidates:
        die(f"nenhum template Bronze para subsistema {subsystem}",41)
    def score(p:Path):
        pu=part_value(p,"uf")
        pc=part_value(p,"competencia")
        gap=999999
        if re.fullmatch(r"\d{6}",pc):
            gap=abs(ym(pc)-ym(comp))
        return (0 if pu.upper()==uf.upper() else 1,gap,str(p))
    return min(candidates,key=score)

def duck_count(path:Path)->int:
    p=subprocess.run(
        ["duckdb","-csv","-noheader","-c",f"SELECT count(*) FROM read_parquet({qlit(str(path))});"],
        text=True,capture_output=True)
    if p.returncode:
        die(f"duckdb count falhou {path}: {p.stderr.strip()}",42)
    return int(p.stdout.strip() or 0)

def write_tsv(path:Path,rows:list[dict[str,str]])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f".partial.{os.getpid()}")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    os.replace(tmp,path)

def main()->int:
    ap=argparse.ArgumentParser(description="Materializa no Bronze DBC SIH 200801_ oficiais, vazios e sem tabela PostgreSQL")
    ap.add_argument("--lake-root",default="/dados/abertos/suslabx")
    ap.add_argument("--execute",action="store_true")
    args=ap.parse_args()

    if not shutil.which("dbview"):
        die("dbview ausente",3)
    if not shutil.which("duckdb"):
        die("duckdb ausente",3)

    lake=Path(args.lake_root).resolve()
    missing=missing_modern()
    if not missing:
        print("SIH_ZERO_SOURCE: nenhum DBC moderno sem SQL")
        return 0

    print(f"SIH_ZERO_SOURCE_PLAN files={len(missing)} execute={int(args.execute)}")
    report=[]
    for i,r in enumerate(sorted(missing,key=lambda x:(x["subsystem"],x["uf"],x["competencia"],x["dbc"])),1):
        cat=int(r["qt_registro_dbc_catalog"] or -1)
        if cat>0:
            die(f"{r['dbc']}: SQL ausente mas catalogo informa qt_registro_dbc={cat}; nao e fonte vazia",50)
        raw=raw_path(lake,r["dbc"])
        n=verify_records(raw,lake)
        if n!=0:
            die(f"{r['dbc']}: DBC oficial possui {n} registros; fluxo zero-row bloqueado",51)

        bronze_root=lake/"bronze"/"sih"/"200801_"
        template=choose_template(bronze_root,r["subsystem"],r["uf"],r["competencia"],r["dbc"])
        dest=(
            bronze_root/r["subsystem"].lower()/f"uf={r['uf']}"/f"competencia={r['competencia']}"
            /"source_service=raw_dbc"/"source_schema=official_dbc"/"source_table=zero_rows"
            /f"{r['dbc']}.parquet"
        )
        print(f"[{i}/{len(missing)}] ZERO_OK {r['dbc']} raw={raw} template={template} -> {dest}")
        status="PLAN"
        if args.execute:
            dest.parent.mkdir(parents=True,exist_ok=True)
            if dest.is_file():
                if duck_count(dest)!=0:
                    die(f"Bronze zero-row existente nao esta vazio: {dest}",52)
                status="SKIP_OK"
            else:
                partial=dest.with_name(dest.name+f".partial.{os.getpid()}")
                partial.unlink(missing_ok=True)
                sql=(
                    f"COPY (SELECT * FROM read_parquet({qlit(str(template))}) LIMIT 0) "
                    f"TO {qlit(str(partial))} (FORMAT PARQUET, COMPRESSION ZSTD);"
                )
                p=subprocess.run(["duckdb","-c",sql],text=True,capture_output=True)
                if p.returncode:
                    partial.unlink(missing_ok=True)
                    die(f"DuckDB zero-row falhou {r['dbc']}: {p.stderr.strip()}",53)
                if duck_count(partial)!=0:
                    partial.unlink(missing_ok=True)
                    die(f"Parquet zero-row gerado com registros: {partial}",54)
                os.replace(partial,dest)
                status="OK"
        report.append({
            **r,
            "raw_path":str(raw),
            "sha256_raw":sha256(raw),
            "verified_records":str(n),
            "template_bronze":str(template),
            "bronze_path":str(dest),
            "status":status,
        })

    if args.execute:
        state=lake/"state"/"sih"
        current=state/"direct_zero_sources_current.tsv"
        write_tsv(current,report)
        marker=state/"direct_zero_sources_current.ok"
        marker.write_text(
            f"files={len(report)}\nverified_records=0\nreport={current}\nstatus=validated\n",
            encoding="utf-8")
        print(f"SIH_ZERO_SOURCE_OK files={len(report)} report={current} marker={marker}")
    else:
        print("DRY_RUN: nenhum Bronze alterado")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
