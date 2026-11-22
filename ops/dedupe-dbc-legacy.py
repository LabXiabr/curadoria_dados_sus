#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import os
import sys
from pathlib import Path

STATE=Path("/dados/abertos/suslabx/state/dissemin")
HOME=Path("/dados/abertos/suslabx/raw/dissemin/dbc/_legacy/from_home")
SDB=Path("/dados/abertos/suslabx/raw/dissemin/dbc/_legacy/from_sdb")

def latest(pattern: str) -> Path:
    xs=sorted(STATE.glob(pattern))
    if not xs:
        raise SystemExit(f"manifest ausente: {pattern}")
    return xs[-1]

def parse_manifest(path: Path) -> dict[str,str]:
    out={}
    with path.open("r",encoding="utf-8",errors="replace") as f:
        for line in f:
            line=line.rstrip("\n")
            if not line:
                continue
            try:
                digest,rel=line.split(None,1)
            except ValueError:
                continue
            rel=rel.strip()
            if rel.startswith("*"):
                rel=rel[1:]
            if rel.startswith("./"):
                rel=rel[2:]
            out[rel]=digest.lower()
    return out

def sha256(path: Path, bufsize: int=8*1024*1024) -> str:
    h=hashlib.sha256()
    with path.open("rb") as f:
        while True:
            b=f.read(bufsize)
            if not b:
                break
            h.update(b)
    return h.hexdigest()

def human(n: int) -> str:
    units=["B","KiB","MiB","GiB","TiB"]
    x=float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.2f} {u}"
        x/=1024
    return str(n)

def main() -> int:
    ap=argparse.ArgumentParser(
        description=(
            "Deduplica SOMENTE o mesmo relative_path com SHA-256 identico "
            "entre from_home e from_sdb. Dry-run por padrao."
        )
    )
    ap.add_argument("--home-root",type=Path,default=HOME)
    ap.add_argument("--sdb-root",type=Path,default=SDB)
    ap.add_argument("--home-manifest",type=Path)
    ap.add_argument("--sdb-manifest",type=Path)
    ap.add_argument("--apply",action="store_true")
    ap.add_argument(
        "--verify-hash",
        action="store_true",
        help="recalcula SHA-256 dos dois arquivos antes de cada hardlink; muito mais lento",
    )
    ap.add_argument("--limit",type=int,default=0)
    ap.add_argument(
        "--report",
        type=Path,
        default=STATE/"dbc_legacy_dedupe.tsv",
    )
    args=ap.parse_args()

    hm=args.home_manifest or latest("dbc_from_home_sha256_*.txt")
    sm=args.sdb_manifest or latest("dbc_from_sdb_sha256_*.txt")
    hmap=parse_manifest(hm)
    smap=parse_manifest(sm)
    hm_mtime=hm.stat().st_mtime
    sm_mtime=sm.stat().st_mtime

    candidates=[]
    for rel,h in hmap.items():
        if smap.get(rel)==h:
            candidates.append((rel,h))
    candidates.sort()
    if args.limit > 0:
        candidates=candidates[:args.limit]

    args.report.parent.mkdir(parents=True,exist_ok=True)
    mode="apply" if args.apply else "dry_run"

    scanned=eligible=already_linked=linked=skipped=0
    nominal_bytes=potential_bytes=0

    with args.report.open("w",encoding="utf-8") as out:
        out.write(
            "relative_path\tsha256\tbytes\tstatus\treason\t"
            "home_inode\tsdb_inode_before\tsdb_inode_after\t"
            "home_mtime_ns_before\tsdb_mtime_ns_before\t"
            "home_nlink_before\tsdb_nlink_before\n"
        )
        for rel,digest in candidates:
            scanned+=1
            hp=args.home_root/rel
            sp=args.sdb_root/rel
            try:
                hs=hp.stat()
                ss=sp.stat()
            except FileNotFoundError as e:
                skipped+=1
                out.write(f"{rel}\t{digest}\t0\tskip\tmissing:{e.filename}\t0\t0\t0\t0\t0\t0\t0\n")
                continue

            if not hp.is_file() or not sp.is_file():
                skipped+=1
                out.write(f"{rel}\t{digest}\t0\tskip\tnot_regular\t{hs.st_ino}\t{ss.st_ino}\t{ss.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")
                continue
            if hs.st_dev != ss.st_dev:
                skipped+=1
                out.write(f"{rel}\t{digest}\t{ss.st_size}\tskip\tdifferent_filesystem\t{hs.st_ino}\t{ss.st_ino}\t{ss.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")
                continue
            if hs.st_size != ss.st_size:
                skipped+=1
                out.write(f"{rel}\t{digest}\t{ss.st_size}\tskip\tsize_changed_since_manifest\t{hs.st_ino}\t{ss.st_ino}\t{ss.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")
                continue
            if hs.st_mtime > hm_mtime or ss.st_mtime > sm_mtime:
                skipped+=1
                out.write(f"{rel}\t{digest}\t{ss.st_size}\tskip\tfile_newer_than_manifest\t{hs.st_ino}\t{ss.st_ino}\t{ss.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")
                continue
            if hs.st_ino == ss.st_ino and hs.st_dev == ss.st_dev:
                already_linked+=1
                out.write(f"{rel}\t{digest}\t{ss.st_size}\tok\talready_hardlinked\t{hs.st_ino}\t{ss.st_ino}\t{ss.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")
                continue

            if args.verify_hash:
                hh=sha256(hp)
                sh=sha256(sp)
                if hh != digest or sh != digest:
                    skipped+=1
                    out.write(f"{rel}\t{digest}\t{ss.st_size}\tskip\tcurrent_hash_mismatch\t{hs.st_ino}\t{ss.st_ino}\t{ss.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")
                    continue

            eligible+=1
            nominal_bytes+=ss.st_size
            if ss.st_nlink == 1:
                potential_bytes+=ss.st_blocks*512

            if not args.apply:
                out.write(f"{rel}\t{digest}\t{ss.st_size}\tdry_run\teligible\t{hs.st_ino}\t{ss.st_ino}\t{ss.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")
                continue

            tmp=sp.with_name(sp.name+f".dedupe.{os.getpid()}")
            try:
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
                os.link(hp,tmp)
                ts=tmp.stat()
                if ts.st_ino != hs.st_ino or ts.st_size != hs.st_size:
                    raise RuntimeError("hardlink temporario inconsistente")
                os.replace(tmp,sp)
                fs=sp.stat()
                if fs.st_ino != hs.st_ino or fs.st_size != hs.st_size:
                    raise RuntimeError("hardlink final inconsistente")
                linked+=1
                out.write(f"{rel}\t{digest}\t{ss.st_size}\tok\thardlinked\t{hs.st_ino}\t{ss.st_ino}\t{fs.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")
            except Exception as e:
                skipped+=1
                try:
                    tmp.unlink()
                except FileNotFoundError:
                    pass
                out.write(f"{rel}\t{digest}\t{ss.st_size}\terror\t{type(e).__name__}:{e}\t{hs.st_ino}\t{ss.st_ino}\t{ss.st_ino}\t{hs.st_mtime_ns}\t{ss.st_mtime_ns}\t{hs.st_nlink}\t{ss.st_nlink}\n")

    print(f"mode={mode}")
    print(f"home_manifest={hm}")
    print(f"sdb_manifest={sm}")
    print(f"same_path_same_hash_candidates={len(candidates)}")
    print(f"scanned={scanned}")
    print(f"eligible={eligible}")
    print(f"already_hardlinked={already_linked}")
    print(f"linked={linked}")
    print(f"skipped={skipped}")
    print(f"nominal_duplicate_bytes={nominal_bytes}")
    print(f"nominal_duplicate_human={human(nominal_bytes)}")
    print(f"potential_blocks_freed_bytes={potential_bytes}")
    print(f"potential_blocks_freed_human={human(potential_bytes)}")
    print(f"report={args.report}")
    print("policy=only_same_relative_path_and_same_manifest_sha256")
    if not args.apply:
        print("status=dry_run_no_files_changed")
    elif skipped:
        print("status=apply_completed_with_skips")
    else:
        print("status=apply_ok")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
