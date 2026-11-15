#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import errno
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
CATALOG=ROOT/"catalog"/"datasets.tsv"
SKIP={"cnes_bronze_reference","cnes_silver_reference"}

def die(msg: str, code: int=2):
    print(f"ERRO: {msg}",file=sys.stderr); raise SystemExit(code)

def read_tsv(path: Path):
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def link(src: Path,dst: Path):
    dst.parent.mkdir(parents=True,exist_ok=True)
    if dst.exists():
        try:
            if os.path.samefile(src,dst): return
        except OSError:
            pass
        dst.unlink()
    try:
        os.link(src,dst)
    except OSError as exc:
        if exc.errno==errno.EXDEV:
            die(f"hardlink impossivel entre filesystems: {src} -> {dst}",30)
        raise

def main() -> int:
    ap=argparse.ArgumentParser(description="Projeta datasets publicos da lake em /dados/abertos/{bronze,silver}")
    ap.add_argument("--root",default="/dados/abertos")
    ap.add_argument("--dataset",action="append")
    args=ap.parse_args()

    root=Path(args.root).resolve(); wanted=set(args.dataset or [])
    counts=Counter()
    for r in read_tsv(CATALOG):
        ds=r["dataset_id"]
        if ds in SKIP or r.get("status")!="published": continue
        if wanted and ds not in wanted: continue
        if r.get("layer") not in {"bronze","silver"}: continue
        public_rel=Path(r["discovery_path"])
        if str(public_rel).startswith("suslake/"):
            public_rel=Path(*public_rel.parts[1:])
        if not public_rel.parts or public_rel.parts[0] not in {"bronze","silver"}:
            continue

        src_root=root/"suslake"/public_rel
        dst_root=root/public_rel
        if not src_root.is_dir():
            print(f"PUBLIC_PROJECTION_SKIP dataset={ds} reason=source_absent:{src_root}")
            continue
        rx=re.compile(r.get("file_regex") or r".*")
        matched=0
        for src in sorted(p for p in src_root.rglob("*") if p.is_file()):
            if not rx.search(src.name): continue
            rel=src.relative_to(src_root)
            link(src,dst_root/rel)
            matched+=1
        counts[ds]+=matched
        print(f"PUBLIC_PROJECTION_OK dataset={ds} files={matched} source={src_root} target={dst_root}")

    if wanted:
        absent=wanted-set(counts)
        if absent:
            print("PUBLIC_PROJECTION_NOTICE no_files=" + ",".join(sorted(absent)))
    print(f"PUBLIC_PROJECTION_COMPLETE files={sum(counts.values())} datasets={len(counts)}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
