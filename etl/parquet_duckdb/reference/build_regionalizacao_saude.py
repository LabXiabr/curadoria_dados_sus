#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"

def run(sql: str, capture: bool = False) -> str:
    p = subprocess.run(["duckdb","-csv","-noheader","-c",sql], text=True, capture_output=True)
    if p.returncode:
        if p.stderr: print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def marker(path: Path) -> dict[str,str]:
    out={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out

def tname(name: str) -> str:
    s=unicodedata.normalize("NFKD",Path(name).stem)
    s="".join(c for c in s if not unicodedata.combining(c))
    s=re.sub(r"[^A-Za-z0-9_]+","_",s).strip("_").lower()
    return s or "regionalizacao_saude"

def detect(sample: bytes) -> tuple[str,str]:
    enc="utf-8-sig"
    try:
        text=sample.decode(enc)
    except UnicodeDecodeError:
        enc="cp1252"
        try: text=sample.decode(enc)
        except UnicodeDecodeError:
            enc="latin-1"; text=sample.decode(enc)
    try:
        delim=csv.Sniffer().sniff(text,delimiters=";,\t|").delimiter
    except csv.Error:
        delim=";"
    return enc,delim

def main() -> int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslabx"))
    args=ap.parse_args()
    if not shutil.which("duckdb"): die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    state=lake/"state"/"reference"
    m=marker(state/"regionalizacao_saude_latest.ok")
    zp=Path(m["path"]); sha=m["sha256"]; version=m["version"]
    if not zp.is_file(): die(f"ZIP ausente: {zp}",4)

    workroot=lake/"work"/"regionalizacao_saude"
    workroot.mkdir(parents=True,exist_ok=True)
    work=Path(tempfile.mkdtemp(prefix=version+"_",dir=workroot))
    rows_report=[]
    try:
        with zipfile.ZipFile(zp) as zf:
            bad=zf.testzip()
            if bad: die(f"ZIP corrompido: {bad}",5)
            entries=[x for x in zf.infolist() if not x.is_dir() and x.filename.lower().endswith(".csv")]
            if not entries: die("ZIP sem CSV",6)

            for i,info in enumerate(sorted(entries,key=lambda x:x.filename.lower()),1):
                table=tname(info.filename)
                with zf.open(info) as f: sample=f.read(262144)
                enc,delim=detect(sample)
                src=work/(table+".csv")
                with zf.open(info) as raw:
                    reader=io.TextIOWrapper(raw,encoding=enc,errors="strict",newline="")
                    with src.open("w",encoding="utf-8",newline="") as out:
                        shutil.copyfileobj(reader,out,1024*1024)
                with src.open(encoding="utf-8",newline="") as f:
                    rr=csv.reader(f,delimiter=delim)
                    try: next(rr)
                    except StopIteration: rows_src=0
                    else: rows_src=sum(1 for row in rr if row and any(x.strip() for x in row))

                bdir=lake/"bronze"/"reference"/"regionalizacao_saude"/table/f"version={version}"
                bdir.mkdir(parents=True,exist_ok=True)
                bronze=bdir/"part-000.parquet"
                tmp=bronze.with_name(bronze.name+f".partial.{os.getpid()}")
                run(f"""
COPY (
 SELECT *,
        {sqls(sha)}::VARCHAR AS _source_sha256,
        {sqls(info.filename)}::VARCHAR AS _source_file,
        current_timestamp AS _ingested_at
 FROM read_csv_auto({sqls(str(src))}, delim={sqls(delim)}, header=true,
                    all_varchar=true, sample_size=-1, null_padding=true)
)
TO {sqls(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
                rows_pq=int(run(f"SELECT count(*) FROM read_parquet({sqls(str(tmp))});",True).strip())
                if rows_pq != rows_src:
                    raise RuntimeError(f"{table}: CSV={rows_src} Parquet={rows_pq}")
                os.replace(tmp,bronze)

                sdir=lake/"silver"/"reference"/"regionalizacao_saude"/table
                sdir.mkdir(parents=True,exist_ok=True)
                current=sdir/"current.parquet"
                ctmp=current.with_name(current.name+f".partial.{os.getpid()}")
                run(f"COPY (SELECT * FROM read_parquet({sqls(str(bronze))})) TO {sqls(str(ctmp))} (FORMAT PARQUET, COMPRESSION ZSTD);")
                os.replace(ctmp,current)
                rows_report.append((table,info.filename,rows_src,str(bronze),str(current)))
                print(f"[{i}/{len(entries)}] OK {table} rows={rows_src}")

        ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
        report=state/f"regionalizacao_saude_{ts}.tsv"
        with report.open("w",encoding="utf-8",newline="") as f:
            w=csv.writer(f,delimiter="\t",lineterminator="\n")
            w.writerow(["table","source_file","rows","bronze","silver_current"])
            w.writerows(rows_report)
        ok=state/"regionalizacao_saude_current.ok"
        ok.write_text("\n".join([
            f"timestamp={ts}",f"version={version}",f"sha256={sha}",
            f"tables={len(rows_report)}",f"report={report}",""
        ]),encoding="utf-8")
        print(f"REGIONALIZACAO_SAUDE_OK tables={len(rows_report)} marker={ok}")
        return 0
    finally:
        shutil.rmtree(work,ignore_errors=True)

if __name__=="__main__":
    raise SystemExit(main())
