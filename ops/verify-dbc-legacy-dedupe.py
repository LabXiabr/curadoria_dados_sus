#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from pathlib import Path

STATE=Path("/dados/abertos/suslake/state/dissemin")
HOME=Path("/dados/abertos/suslake/raw/dissemin/dbc/_legacy/from_home")
SDB=Path("/dados/abertos/suslake/raw/dissemin/dbc/_legacy/from_sdb")

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

def human(n: int) -> str:
    units=["B","KiB","MiB","GiB","TiB"]
    x=float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.2f} {u}"
        x/=1024
    return str(n)

def main() -> int:
    ap=argparse.ArgumentParser(description="Verifica hardlinks criados na deduplicacao DBC legado")
    ap.add_argument("--home-root",type=Path,default=HOME)
    ap.add_argument("--sdb-root",type=Path,default=SDB)
    ap.add_argument("--home-manifest",type=Path)
    ap.add_argument("--sdb-manifest",type=Path)
    ap.add_argument("--out",type=Path,default=STATE/"dbc_legacy_dedupe_verify.tsv")
    args=ap.parse_args()

    hm=args.home_manifest or latest("dbc_from_home_sha256_*.txt")
    sm=args.sdb_manifest or latest("dbc_from_sdb_sha256_*.txt")
    hmap=parse_manifest(hm)
    smap=parse_manifest(sm)

    candidates=sorted((rel,h) for rel,h in hmap.items() if smap.get(rel)==h)
    ok=missing=not_linked=size_diff=0
    logical=blocks=0

    args.out.parent.mkdir(parents=True,exist_ok=True)
    with args.out.open("w",encoding="utf-8") as out:
        out.write("relative_path\tsha256\tstatus\thome_inode\tsdb_inode\tbytes\tnlink\n")
        for rel,digest in candidates:
            hp=args.home_root/rel
            sp=args.sdb_root/rel
            try:
                hs=hp.stat()
                ss=sp.stat()
            except FileNotFoundError:
                missing+=1
                out.write(f"{rel}\t{digest}\tmissing\t0\t0\t0\t0\n")
                continue

            if hs.st_size != ss.st_size:
                size_diff+=1
                out.write(
                    f"{rel}\t{digest}\tsize_diff\t{hs.st_ino}\t{ss.st_ino}\t"
                    f"{ss.st_size}\t{ss.st_nlink}\n"
                )
                continue

            if hs.st_dev != ss.st_dev or hs.st_ino != ss.st_ino:
                not_linked+=1
                out.write(
                    f"{rel}\t{digest}\tnot_linked\t{hs.st_ino}\t{ss.st_ino}\t"
                    f"{ss.st_size}\t{ss.st_nlink}\n"
                )
                continue

            ok+=1
            logical+=ss.st_size
            blocks+=ss.st_blocks*512
            out.write(
                f"{rel}\t{digest}\tok\t{hs.st_ino}\t{ss.st_ino}\t"
                f"{ss.st_size}\t{ss.st_nlink}\n"
            )

    print(f"candidates={len(candidates)}")
    print(f"hardlink_ok={ok}")
    print(f"missing={missing}")
    print(f"not_linked={not_linked}")
    print(f"size_diff={size_diff}")
    print(f"logical_duplicate_bytes={logical}")
    print(f"logical_duplicate_human={human(logical)}")
    print(f"shared_blocks_bytes={blocks}")
    print(f"shared_blocks_human={human(blocks)}")
    print(f"report={args.out}")

    if missing or not_linked or size_diff or ok != len(candidates):
        print("status=verify_fail")
        return 20

    marker=STATE/"dbc_legacy_dedupe_complete.ok"
    marker.write_text("\n".join([
        f"home_manifest={hm}",
        f"sdb_manifest={sm}",
        f"candidates={len(candidates)}",
        f"hardlink_ok={ok}",
        f"logical_duplicate_bytes={logical}",
        "policy=same_relative_path_and_same_sha256_hardlinked",
        "status=complete",
        ""
    ]),encoding="utf-8")
    print(f"marker={marker}")
    print("status=verify_ok")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
