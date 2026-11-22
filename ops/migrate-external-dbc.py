#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from urllib.parse import urlparse

SERVICES=("bureta","pipeta")
FIELDS=[
    "source","filename","bytes_source","sha256_source",
    "inventory_service","system","series","subsystem","uf","competencia",
    "ftp_url","ftp_bytes_catalog","ftp_sha256",
    "target","target_preexisting","bytes_target","sha256_target",
    "local_match","ftp_match","copied","deleted","status","note"
]

def run_psql(service:str, sql:str)->str:
    p=subprocess.run(
        ["psql",f"service={service}","-X","-At","-F","\t","-P","pager=off","-c",sql],
        text=True,capture_output=True
    )
    if p.returncode:
        raise RuntimeError(f"psql service={service}: {p.stderr.strip()}")
    return p.stdout

def latest_list(service:str)->str:
    return run_psql(service,r"""
SELECT table_schema||'.'||table_name
FROM information_schema.tables
WHERE table_schema='public'
  AND table_name ~ '^lista_dissemin_dbc_[0-9]{8}$'
ORDER BY table_name DESC
LIMIT 1;
""").strip()

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(4*1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def inventory_for_names(names:set[str])->dict[str,list[dict[str,str]]]:
    by=defaultdict(list)
    if not names:
        return by
    # nomes DBC nao contem aspas na fonte; ainda escapamos defensivamente.
    lits=",".join("'" + x.replace("'","''") + "'" for x in sorted(names))
    for svc in SERVICES:
        table=latest_list(svc)
        if not table:
            continue
        sql=f"""
SELECT
 lower(no_dbc_origem),
 upper(coalesce(sg_sistema,'')),
 coalesce(sg_versao,''),
 upper(coalesce(sg_subsistema,'')),
 upper(coalesce(sg_uf,'')),
 coalesce(nu_competencia,0)::text,
 coalesce(ds_url,''),
 coalesce(qt_bytes_ftp,0)::text,
 coalesce(dt_ftp::text,''),
 coalesce(hr_ftp::text,''),
 coalesce(st_modificado,0)::text
FROM {table}
WHERE lower(no_dbc_origem) IN ({lits})
ORDER BY 1,2,3,4,5,6;
"""
        for line in run_psql(svc,sql).splitlines():
            p=line.split("\t")
            if len(p)!=11:
                continue
            by[p[0]].append({
                "inventory_service":svc,"system":p[1],"series":p[2],
                "subsystem":p[3],"uf":p[4],"competencia":p[5],
                "ds_url":p[6],"ftp_bytes_catalog":p[7],
                "dt_ftp":p[8],"hr_ftp":p[9],"st_modificado":p[10],
            })
    return by

def choose_inventory(rows:list[dict[str,str]])->tuple[dict[str,str]|None,str]:
    if not rows:
        return None,"sem_inventario"
    # Dedup por metadado sem considerar servidor; preferir registro mais recente
    # e URL oficial de dissemin/publicos.
    uniq={}
    for r in rows:
        key=(r["system"],r["series"],r["subsystem"],r["uf"],r["competencia"],r["ds_url"])
        uniq[key]=r
    vals=list(uniq.values())
    official=[r for r in vals if "/dissemin/publicos/" in r["ds_url"]]
    if len(official)==1:
        return official[0],""
    if len(vals)==1:
        return vals[0],""
    return None,"inventario_ambiguo"

def target_from_url(lake:Path, ds_url:str, filename:str)->Path|None:
    marker="/dissemin/publicos/"
    if marker not in ds_url:
        return None
    rel=ds_url.split(marker,1)[1].lstrip("/")
    # Espelha literalmente a arvore publicada depois de dissemin/publicos.
    return lake/"raw"/"dissemin"/"dbc"/Path(rel)/filename

def ftp_download(url:str, timeout:int)->tuple[Path|None,str,int,str]:
    fd,tmpname=tempfile.mkstemp(prefix="suslabx_ftp_",suffix=".dbc")
    os.close(fd)
    tmp=Path(tmpname)
    p=subprocess.run(
        ["curl","-fsSL","--connect-timeout",str(timeout),"--max-time",str(max(timeout*4,60)),
         "-o",str(tmp),url],
        text=True,capture_output=True
    )
    if p.returncode:
        tmp.unlink(missing_ok=True)
        return None,"",0,p.stderr.strip() or f"curl_rc={p.returncode}"
    return tmp,sha256(tmp),tmp.stat().st_size,""

def write_report(path:Path, rows:list[dict[str,str]])->None:
    path.parent.mkdir(parents=True,exist_ok=True)
    tmp=path.with_name(path.name+f".partial.{os.getpid()}")
    with tmp.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=FIELDS,delimiter="\t",lineterminator="\n",extrasaction="ignore")
        w.writeheader(); w.writerows(rows)
    os.replace(tmp,path)

def main()->int:
    ap=argparse.ArgumentParser(
        description="Drena DBC legado de disco externo para Raw SUSLabX com gate SHA-256 local + FTP"
    )
    ap.add_argument("--source-dir",default="/mnt/sdb/tmp/DBF2025-06-26")
    ap.add_argument("--lake-root",default="/dados/abertos/suslake")
    ap.add_argument("--report")
    ap.add_argument("--verify-ftp",action="store_true",
                    help="baixa temporariamente o DBC do FTP oficial e compara SHA-256")
    ap.add_argument("--copy",action="store_true",
                    help="copia para Raw canonico quando alvo ainda nao existe")
    ap.add_argument("--delete-verified",action="store_true",
                    help="remove a origem SOMENTE quando source == target == FTP por SHA-256")
    ap.add_argument("--timeout",type=int,default=30)
    ap.add_argument("--limit",type=int,default=0)
    args=ap.parse_args()

    srcdir=Path(args.source_dir).resolve()
    lake=Path(args.lake_root).resolve()
    if not srcdir.is_dir():
        raise SystemExit(f"source-dir ausente: {srcdir}")
    if args.delete_verified and not args.verify_ftp:
        raise SystemExit("--delete-verified exige --verify-ftp")
    if args.delete_verified and not args.copy:
        # Permitimos apagar sem --copy apenas se o alvo ja existir e bater,
        # mas exigir --copy torna a intencao operacional explicita.
        raise SystemExit("--delete-verified exige tambem --copy")

    # Preflight de escrita: falhar antes de qualquer copia/remocao se a raiz Raw
    # nao puder ser criada ou escrita pelo usuario corrente.
    raw_root=lake/"raw"/"dissemin"/"dbc"
    try:
        raw_root.mkdir(parents=True,exist_ok=True)
        probe=raw_root/f".write-test.{os.getpid()}"
        probe.write_text("ok\n",encoding="utf-8")
        probe.unlink()
    except PermissionError:
        raise SystemExit(
            "sem permissao de escrita em "+str(raw_root)+"; "
            "crie/ajuste a arvore antes de executar --copy/--delete-verified"
        )

    files=sorted(p for p in srcdir.rglob("*") if p.is_file() and p.suffix.lower()==".dbc")
    if args.limit>0:
        files=files[:args.limit]
    names={p.name.lower() for p in files}
    inv=inventory_for_names(names)

    report_path=Path(args.report) if args.report else (
        lake/"state"/"external_migration"/"sdb_DBF2025-06-26.tsv"
    )
    rows=[]

    for i,src in enumerate(files,1):
        row={k:"" for k in FIELDS}
        row["source"]=str(src); row["filename"]=src.name
        row["bytes_source"]=str(src.stat().st_size)
        sh=sha256(src); row["sha256_source"]=sh

        meta,note=choose_inventory(inv.get(src.name.lower(),[]))
        if not meta:
            row["status"]="KEEP"
            row["note"]=note
            rows.append(row); write_report(report_path,rows)
            print(f"[{i}/{len(files)}] KEEP {src.name} {note}",flush=True)
            continue

        row.update({k:str(meta.get(k,"")) for k in (
            "inventory_service","system","series","subsystem","uf","competencia","ftp_bytes_catalog"
        )})
        ftp_url=meta["ds_url"].rstrip("/")+"/"+src.name
        row["ftp_url"]=ftp_url
        target=target_from_url(lake,meta["ds_url"],src.name)
        if target is None:
            row["status"]="KEEP"; row["note"]="url_ftp_nao_mapeavel"
            rows.append(row); write_report(report_path,rows)
            print(f"[{i}/{len(files)}] KEEP {src.name} url_ftp_nao_mapeavel",flush=True)
            continue
        row["target"]=str(target)
        row["target_preexisting"]="1" if target.exists() else "0"

        # Quando solicitado, verificar FTP ANTES de escrever no caminho canonico.
        ftp_tmp=None
        if args.verify_ftp:
            ftp_tmp,fh,fb,err=ftp_download(ftp_url,args.timeout)
            row["ftp_sha256"]=fh
            if fb:
                row["note"]=(row["note"]+";" if row["note"] else "")+f"ftp_bytes_download={fb}"
            if err:
                row["status"]="KEEP"; row["ftp_match"]="0"
                row["note"]=(row["note"]+";" if row["note"] else "")+"ftp_error="+err.replace("\t"," ")
                rows.append(row); write_report(report_path,rows)
                print(f"[{i}/{len(files)}] KEEP {src.name} ftp_error",flush=True)
                continue
            row["ftp_match"]="1" if fh==sh else "0"
            if fh!=sh:
                ftp_tmp.unlink(missing_ok=True)
                row["status"]="KEEP"
                row["note"]=(row["note"]+";" if row["note"] else "")+"FTP_ATUAL_DIVERGE"
                rows.append(row); write_report(report_path,rows)
                print(f"[{i}/{len(files)}] KEEP {src.name} ftp_diverge",flush=True)
                continue

        try:
            if target.exists():
                th=sha256(target); row["sha256_target"]=th
                row["bytes_target"]=str(target.stat().st_size)
                row["local_match"]="1" if th==sh else "0"
                if th!=sh:
                    row["status"]="KEEP"
                    row["note"]=(row["note"]+";" if row["note"] else "")+"CONFLITO_target_diverge"
                    rows.append(row); write_report(report_path,rows)
                    print(f"[{i}/{len(files)}] KEEP {src.name} target_diverge",flush=True)
                    continue
            elif args.copy:
                target.parent.mkdir(parents=True,exist_ok=True)
                partial=target.with_name(target.name+f".partial.{os.getpid()}")
                shutil.copy2(src,partial)
                th=sha256(partial)
                if th!=sh:
                    partial.unlink(missing_ok=True)
                    row["status"]="KEEP"; row["note"]=(row["note"]+";" if row["note"] else "")+"copy_sha256_diverge"
                    rows.append(row); write_report(report_path,rows)
                    print(f"[{i}/{len(files)}] KEEP {src.name} copy_sha256_diverge",flush=True)
                    continue
                os.replace(partial,target)
                row["copied"]="1"; row["sha256_target"]=th
                row["bytes_target"]=str(target.stat().st_size); row["local_match"]="1"
            else:
                row["status"]="COPY_REQUIRED"; row["note"]=(row["note"]+";" if row["note"] else "")+"target_ausente"
                rows.append(row); write_report(report_path,rows)
                print(f"[{i}/{len(files)}] COPY_REQUIRED {src.name} -> {target}",flush=True)
                continue
        finally:
            if ftp_tmp is not None:
                ftp_tmp.unlink(missing_ok=True)

        if args.delete_verified:
            # Gate destrutivo estrito: origem, alvo e FTP precisam ter o mesmo SHA-256.
            if row["local_match"]=="1" and row["ftp_match"]=="1":
                src.unlink()
                row["deleted"]="1"; row["status"]="DELETED_VERIFIED"
                print(f"[{i}/{len(files)}] DELETED_VERIFIED {src.name}",flush=True)
            else:
                row["status"]="KEEP"; row["note"]=(row["note"]+";" if row["note"] else "")+"delete_gate_failed"
        else:
            row["status"]="VERIFIED" if row["local_match"]=="1" and row["ftp_match"]=="1" else "LOCAL_OK"

        rows.append(row); write_report(report_path,rows)

    counts=defaultdict(int)
    for r in rows: counts[r["status"]]+=1
    print(f"EXTERNAL_DBC_DONE files={len(rows)} report={report_path}")
    for k in sorted(counts):
        print(f"status={k} count={counts[k]}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
