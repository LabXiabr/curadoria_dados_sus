#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import ftplib
import os
import posixpath
import re
import sys
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_HOST="ftp.datasus.gov.br"
DEFAULT_BASE="/dissemin/publicos"

def norm_rel(p: str) -> str:
    p=p.strip().replace("\\","/")
    p=re.sub(r"/+","/",p).strip("/")
    return p

def read_policy(path: Path):
    rows=[]
    with path.open("r",encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f,delimiter="\t"):
            root=norm_rel(r.get("source_root",""))
            if not root:
                continue
            r["source_root"]=root
            rows.append(r)
    return rows

def ftp_connect(host: str, timeout: int) -> ftplib.FTP:
    ftp=ftplib.FTP(timeout=timeout)
    ftp.connect(host,21)
    ftp.login()
    ftp.set_pasv(True)
    return ftp

def mlsd_dir(ftp: ftplib.FTP, remote_dir: str):
    try:
        items=[]
        for name,facts in ftp.mlsd(remote_dir,facts=["type","size","modify"]):
            if name in (".",".."):
                continue
            items.append((name,facts))
        return items
    except (ftplib.error_perm, ftplib.error_temp, OSError):
        return None

def list_fallback(ftp: ftplib.FTP, remote_dir: str):
    old=ftp.pwd()
    try:
        ftp.cwd(remote_dir)
        names=ftp.nlst()
        out=[]
        for raw in names:
            name=posixpath.basename(raw.rstrip("/"))
            if not name or name in (".",".."):
                continue
            facts={}
            try:
                ftp.cwd(name)
                ftp.cwd("..")
                facts["type"]="dir"
            except ftplib.error_perm:
                facts["type"]="file"
                try:
                    sz=ftp.size(name)
                    if sz is not None:
                        facts["size"]=str(sz)
                except Exception:
                    pass
                try:
                    resp=ftp.sendcmd(f"MDTM {name}")
                    m=re.match(r"213\s+(\d{14})",resp)
                    if m:
                        facts["modify"]=m.group(1)
                except Exception:
                    pass
            out.append((name,facts))
        return out
    finally:
        ftp.cwd(old)

def walk_root(ftp: ftplib.FTP, base: str, source_root: str):
    start=posixpath.join(base,source_root)
    stack=[start]
    while stack:
        d=stack.pop()
        items=mlsd_dir(ftp,d)
        if items is None:
            items=list_fallback(ftp,d)
        dirs=[]
        for name,facts in items:
            typ=(facts.get("type") or "").lower()
            full=posixpath.join(d,name)
            if typ in ("dir","cdir","pdir"):
                if typ=="dir":
                    dirs.append(full)
                continue
            if typ and typ!="file":
                continue
            rel=full[len(base.rstrip("/")+"/"):] if full.startswith(base.rstrip("/")+"/") else full.lstrip("/")
            yield {
                "source_root":source_root,
                "relative_path":rel,
                "filename":name,
                "bytes":facts.get("size",""),
                "modify_utc":facts.get("modify",""),
            }
        stack.extend(sorted(dirs,reverse=True))

def main() -> int:
    ap=argparse.ArgumentParser(description="Inventario fresco dos DBC do FTP dissemin/publicos")
    ap.add_argument("--policy",type=Path,default=Path("systems/dissemin/source_policy.tsv"))
    ap.add_argument("--host",default=DEFAULT_HOST)
    ap.add_argument("--base",default=DEFAULT_BASE)
    ap.add_argument("--state-root",type=Path,default=Path("/dados/abertos/suslake/state/dissemin"))
    ap.add_argument("--timeout",type=int,default=60)
    ap.add_argument("--all-files",action="store_true",help="inclui arquivos nao DBC")
    args=ap.parse_args()

    policy=read_policy(args.policy)
    # Evita varrer raiz filha se outra raiz da mesma policy ja a cobre.
    roots=[]
    for r in policy:
        root=r["source_root"]
        if any(root==x["source_root"] or root.startswith(x["source_root"].rstrip("/")+"/") for x in roots):
            continue
        roots.append(r)

    ts=datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    args.state_root.mkdir(parents=True,exist_ok=True)
    out=args.state_root/f"ftp_publicos_dbc_{ts}.tsv"
    roots_out=args.state_root/f"ftp_publicos_roots_{ts}.tsv"
    tmp=out.with_suffix(".partial.tsv")
    roots_tmp=roots_out.with_suffix(".partial.tsv")

    ftp=ftp_connect(args.host,args.timeout)
    n=0
    missing=0
    try:
        with tmp.open("w",encoding="utf-8",newline="") as f, roots_tmp.open("w",encoding="utf-8",newline="") as rf:
            w=csv.DictWriter(f,delimiter="\t",lineterminator="\n",fieldnames=[
                "system","role","etl_policy","retention","source_root",
                "relative_path","filename","bytes","modify_utc","ftp_url"
            ])
            rw=csv.DictWriter(rf,delimiter="\t",lineterminator="\n",fieldnames=[
                "system","source_root","status","detail"
            ])
            w.writeheader(); rw.writeheader()

            for idx,r in enumerate(roots,start=1):
                root=r["source_root"]
                remote=posixpath.join(args.base,root)
                try:
                    ftp.cwd(remote)
                    ftp.cwd("/")
                except ftplib.error_perm as e:
                    missing+=1
                    rw.writerow({"system":r.get("system",""),"source_root":root,"status":"missing","detail":str(e)})
                    print(f"[{idx}/{len(roots)}] MISSING {root}: {e}",file=sys.stderr)
                    continue

                count=0
                try:
                    for x in walk_root(ftp,args.base,root):
                        if not args.all_files and not x["filename"].lower().endswith(".dbc"):
                            continue
                        row={
                            "system":r.get("system",""),
                            "role":r.get("role",""),
                            "etl_policy":r.get("etl_policy",""),
                            "retention":r.get("retention",""),
                            **x,
                            "ftp_url":f"ftp://{args.host}{args.base}/{x['relative_path']}",
                        }
                        w.writerow(row)
                        count+=1; n+=1
                    rw.writerow({"system":r.get("system",""),"source_root":root,"status":"ok","detail":str(count)})
                    print(f"[{idx}/{len(roots)}] OK {root} dbc={count}")
                except Exception as e:
                    rw.writerow({"system":r.get("system",""),"source_root":root,"status":"error","detail":repr(e)})
                    raise

        os.replace(tmp,out)
        os.replace(roots_tmp,roots_out)
    finally:
        try: ftp.quit()
        except Exception: ftp.close()

    marker=args.state_root/"ftp_publicos_dbc_latest.ok"
    marker.write_text("\n".join([
        f"timestamp_utc={ts}",
        f"host={args.host}",
        f"base={args.base}",
        f"policy={args.policy}",
        f"roots={len(roots)}",
        f"missing_roots={missing}",
        f"dbc_files={n}",
        f"inventory={out}",
        f"roots_report={roots_out}",
        "status=complete",
        ""
    ]),encoding="utf-8")

    print(f"FTP_PUBLICOS_INVENTORY_OK files={n} missing_roots={missing}")
    print(f"inventory={out}")
    print(f"roots_report={roots_out}")
    print(f"marker={marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
