#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

STATE=Path("/dados/abertos/suslake/state/dissemin")
HOME=Path("/dados/abertos/suslake/raw/dissemin/dbc/_legacy/from_home")
SDB=Path("/dados/abertos/suslake/raw/dissemin/dbc/_legacy/from_sdb")

def latest(pattern: str) -> Path:
    xs=sorted(STATE.glob(pattern))
    if not xs:
        raise SystemExit(f"arquivo ausente: {pattern}")
    return xs[-1]

def parse_manifest(path: Path) -> dict[str,str]:
    out={}
    with path.open("r",encoding="utf-8",errors="replace") as f:
        for line in f:
            line=line.rstrip("\n")
            if not line:
                continue
            try: digest,rel=line.split(None,1)
            except ValueError: continue
            rel=rel.strip()
            if rel.startswith("*"): rel=rel[1:]
            if rel.startswith("./"): rel=rel[2:]
            out[rel]=digest.lower()
    return out

def parse_modify(v: str) -> int | None:
    v=(v or "").strip()
    if not v:
        return None
    try:
        return int(datetime.strptime(v[:14],"%Y%m%d%H%M%S").replace(tzinfo=timezone.utc).timestamp())
    except ValueError:
        return None

def main() -> int:
    ap=argparse.ArgumentParser(description="Reconcilia inventario FTP atual com as duas arvores DBC legadas")
    ap.add_argument("--ftp-inventory",type=Path)
    ap.add_argument("--home-root",type=Path,default=HOME)
    ap.add_argument("--sdb-root",type=Path,default=SDB)
    ap.add_argument("--home-manifest",type=Path)
    ap.add_argument("--sdb-manifest",type=Path)
    ap.add_argument("--mtime-tolerance",type=int,default=120)
    ap.add_argument("--out",type=Path,default=STATE/"dbc_legacy_reconcile.tsv")
    args=ap.parse_args()

    ftp_inv=args.ftp_inventory or latest("ftp_publicos_dbc_*.tsv")
    hm=args.home_manifest or latest("dbc_from_home_sha256_*.txt")
    sm=args.sdb_manifest or latest("dbc_from_sdb_sha256_*.txt")
    hmap=parse_manifest(hm); smap=parse_manifest(sm)

    locals_by_base=defaultdict(list)
    for origin,root,mp in (("home",args.home_root,hmap),("sdb",args.sdb_root,smap)):
        for rel,digest in mp.items():
            p=root/rel
            try: st=p.stat()
            except FileNotFoundError: continue
            locals_by_base[Path(rel).name.lower()].append({
                "origin":origin,"rel":rel,"path":p,"sha256":digest,
                "bytes":st.st_size,"mtime":int(st.st_mtime),
                "dev":st.st_dev,"ino":st.st_ino,
            })

    remote=[]
    with ftp_inv.open("r",encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f,delimiter="\t"):
            try: size=int(r.get("bytes") or 0)
            except ValueError: size=0
            r["_bytes"]=size
            r["_mtime"]=parse_modify(r.get("modify_utc",""))
            remote.append(r)

    remote_by_base=defaultdict(list)
    for r in remote:
        remote_by_base[r["filename"].lower()].append(r)

    counts=defaultdict(int)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",encoding="utf-8",newline="") as f:
        fields=[
            "classification","system","role","etl_policy","relative_path","filename",
            "remote_bytes","remote_modify_utc","remote_basename_paths",
            "local_candidates","size_match_candidates","mtime_match_candidates",
            "selected_origin","selected_rel","selected_sha256","selected_bytes",
            "selected_mtime","selected_inode","reason"
        ]
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader()

        for r in sorted(remote,key=lambda x:x["relative_path"].lower()):
            base=r["filename"].lower()
            lc=locals_by_base.get(base,[])
            sm=[x for x in lc if r["_bytes"]>0 and x["bytes"]==r["_bytes"]]
            mm=[]
            if r["_mtime"] is not None:
                mm=[x for x in sm if abs(x["mtime"]-r["_mtime"]) <= args.mtime_tolerance]

            remote_paths=len(remote_by_base[base])
            selected=None; classification=""; reason=""

            if remote_paths > 1:
                classification="remote_basename_ambiguous"
                reason="mesmo basename aparece em mais de um caminho FTP"
            elif not lc:
                classification="missing_local"
                reason="basename remoto nao encontrado no legado"
            elif not sm:
                classification="remote_size_no_local_match"
                reason="ha basename local, mas nenhum arquivo tem o SIZE remoto"
            else:
                size_hashes={x["sha256"] for x in sm}
                mtime_hashes={x["sha256"] for x in mm}

                if len(mm)>0 and len(mtime_hashes)==1:
                    selected=mm[0]
                    classification="promote_size_mtime"
                    reason="basename remoto unico; SIZE e MDTM compativeis; hash local univoco"
                elif len(size_hashes)==1:
                    selected=sm[0]
                    classification="review_size_only"
                    reason="SIZE resolve para um unico hash local, mas MDTM nao confirma"
                elif len(mm)>0 and len(mtime_hashes)>1:
                    classification="ambiguous_same_size_mtime"
                    reason="mais de um hash local compartilha SIZE e MDTM remotos"
                else:
                    classification="ambiguous_same_size"
                    reason="mais de um hash local compartilha o SIZE remoto"

            counts[classification]+=1
            w.writerow({
                "classification":classification,
                "system":r.get("system",""),
                "role":r.get("role",""),
                "etl_policy":r.get("etl_policy",""),
                "relative_path":r["relative_path"],
                "filename":r["filename"],
                "remote_bytes":r["_bytes"],
                "remote_modify_utc":r.get("modify_utc",""),
                "remote_basename_paths":remote_paths,
                "local_candidates":len(lc),
                "size_match_candidates":len(sm),
                "mtime_match_candidates":len(mm),
                "selected_origin":selected["origin"] if selected else "",
                "selected_rel":selected["rel"] if selected else "",
                "selected_sha256":selected["sha256"] if selected else "",
                "selected_bytes":selected["bytes"] if selected else "",
                "selected_mtime":selected["mtime"] if selected else "",
                "selected_inode":selected["ino"] if selected else "",
                "reason":reason,
            })

    print(f"ftp_inventory={ftp_inv}")
    print(f"home_manifest={hm}")
    print(f"sdb_manifest={sm}")
    print(f"remote_files={len(remote)}")
    for k in sorted(counts):
        print(f"{k}={counts[k]}")
    print(f"out={args.out}")
    print("status=reconcile_plan_only_no_files_changed")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
