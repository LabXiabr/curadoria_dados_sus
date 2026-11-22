#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, hashlib, os, shutil, subprocess, tempfile
from pathlib import Path
from urllib.request import Request, urlopen

def sha256(path:Path)->str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        for b in iter(lambda:f.read(4*1024*1024),b""):
            h.update(b)
    return h.hexdigest()

def read_tsv(path:Path)->list[dict[str,str]]:
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def download(url:str,dst:Path,timeout:int)->None:
    req=Request(url,headers={"User-Agent":"Mozilla/5.0 SUSLabX raw reconciler"})
    with urlopen(req,timeout=timeout) as r, dst.open("wb") as f:
        shutil.copyfileobj(r,f,1024*1024)

def main()->int:
    ap=argparse.ArgumentParser(
        description="Repara Raw canonico quando copia externa historica diverge do FTP atual"
    )
    ap.add_argument("--lake-root",default="/dados/abertos/suslabx")
    ap.add_argument("--source-snapshot",default="DBF2025-06-26")
    ap.add_argument("--report")
    ap.add_argument("--execute",action="store_true")
    ap.add_argument("--timeout",type=int,default=120)
    args=ap.parse_args()

    lake=Path(args.lake_root).resolve()
    report=Path(args.report) if args.report else (
        lake/"state"/"external_migration"/"sdb_DBF2025-06-26.tsv"
    )
    rows=read_tsv(report)
    todo=[
        r for r in rows
        if r.get("status")=="KEEP" and "FTP_ATUAL_DIVERGE" in (r.get("note") or "")
    ]
    raw_root=lake/"raw"/"dissemin"/"dbc"
    legacy_root=raw_root/"_legacy"/"from_sdb"/args.source_snapshot

    if not todo:
        print("RECONCILE_RAW: nenhum FTP_ATUAL_DIVERGE")
        return 0

    problems=0
    for i,r in enumerate(todo,1):
        src=Path(r["source"])
        target=Path(r["target"])
        expected_src=r.get("sha256_source") or ""
        expected_ftp=r.get("ftp_sha256") or ""
        if not src.is_file():
            print(f"[{i}/{len(todo)}] ERROR source_ausente {src}")
            problems+=1; continue
        if not target.is_file():
            print(f"[{i}/{len(todo)}] ERROR target_ausente {target}")
            problems+=1; continue

        sh=sha256(src); th=sha256(target)
        if not expected_src or sh!=expected_src or th!=expected_src:
            print(f"[{i}/{len(todo)}] ERROR estado_local_mudou {src.name}")
            problems+=1; continue

        try:
            rel=target.relative_to(raw_root)
        except ValueError:
            print(f"[{i}/{len(todo)}] ERROR target_fora_raw {target}")
            problems+=1; continue
        legacy=legacy_root/rel

        fd,tmpname=tempfile.mkstemp(prefix=f".{src.stem}.ftp.",suffix=".dbc",dir=str(raw_root))
        os.close(fd); tmp=Path(tmpname)
        try:
            download(r["ftp_url"],tmp,args.timeout)
            fh=sha256(tmp)
            if expected_ftp and fh!=expected_ftp:
                print(
                    f"[{i}/{len(todo)}] ERROR ftp_mudou_novamente {src.name} "
                    f"report={expected_ftp[:12]} atual={fh[:12]}"
                )
                problems+=1; continue

            print(
                f"[{i}/{len(todo)}] PLAN {src.name}\n"
                f"  legacy: {target} -> {legacy}\n"
                f"  canonical: FTP -> {target}\n"
                f"  sha_legacy={sh[:16]} sha_ftp={fh[:16]}"
            )
            if not args.execute:
                continue

            legacy.parent.mkdir(parents=True,exist_ok=True)
            if legacy.exists():
                if sha256(legacy)!=sh:
                    print(f"  ERROR legacy_existente_diverge {legacy}")
                    problems+=1; continue
                # Ja preservado; o target ainda deve conter legado nesta etapa.
                target.unlink()
            else:
                os.replace(target,legacy)

            partial=target.with_name(target.name+f".partial.{os.getpid()}")
            shutil.copy2(tmp,partial)
            if sha256(partial)!=fh:
                partial.unlink(missing_ok=True)
                print(f"  ERROR copy_ftp_diverge {target}")
                problems+=1; continue
            os.replace(partial,target)

            # Gate final: source == legacy e canonical == FTP, mas source != FTP.
            if sha256(legacy)!=sh or sha256(target)!=fh:
                print(f"  ERROR gate_final {src.name}")
                problems+=1; continue
            print(f"  OK_RECONCILED {src.name}")
        finally:
            tmp.unlink(missing_ok=True)

    print(f"RECONCILE_RAW_DONE files={len(todo)} problems={problems} execute={int(args.execute)}")
    return 0 if problems==0 else 10

if __name__=="__main__":
    raise SystemExit(main())
