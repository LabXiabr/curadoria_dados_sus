#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
from collections import defaultdict
from pathlib import Path

def parse_manifest(path: Path):
    out = {}
    with path.open("r", encoding="utf-8", errors="replace") as f:
        for line in f:
            line = line.rstrip("\n")
            if not line:
                continue
            try:
                digest, rel = line.split(None, 1)
            except ValueError:
                continue
            rel = rel.strip()
            if rel.startswith("*"):
                rel = rel[1:]
            if rel.startswith("./"):
                rel = rel[2:]
            out[rel] = digest
    return out

def latest(pattern: str) -> Path:
    matches = sorted(Path("/dados/abertos/suslake/state/dissemin").glob(pattern))
    if not matches:
        raise SystemExit(f"manifest ausente: {pattern}")
    return matches[-1]

def stat_size(root: Path, rel: str) -> int:
    try:
        return (root / rel).stat().st_size
    except FileNotFoundError:
        return 0

def human(n: int) -> str:
    units = ["B","KiB","MiB","GiB","TiB"]
    x = float(n)
    for u in units:
        if x < 1024 or u == units[-1]:
            return f"{x:.2f} {u}"
        x /= 1024
    return str(n)

def main():
    ap = argparse.ArgumentParser(description="Audita duplicacao entre as duas arvores DBC legadas")
    ap.add_argument("--home-root", type=Path, default=Path("/dados/abertos/suslake/raw/dissemin/dbc/_legacy/from_home"))
    ap.add_argument("--sdb-root", type=Path, default=Path("/dados/abertos/suslake/raw/dissemin/dbc/_legacy/from_sdb"))
    ap.add_argument("--home-manifest", type=Path)
    ap.add_argument("--sdb-manifest", type=Path)
    ap.add_argument("--out", type=Path, default=Path("/dados/abertos/suslake/state/dissemin/dbc_legacy_overlap.tsv"))
    ap.add_argument("--conflicts-out", type=Path, default=Path("/dados/abertos/suslake/state/dissemin/dbc_legacy_conflicts.tsv"))
    args = ap.parse_args()

    hm = args.home_manifest or latest("dbc_from_home_sha256_*.txt")
    sm = args.sdb_manifest or latest("dbc_from_sdb_sha256_*.txt")
    home = parse_manifest(hm)
    sdb = parse_manifest(sm)

    home_hash = defaultdict(list)
    sdb_hash = defaultdict(list)
    for p,h in home.items(): home_hash[h].append(p)
    for p,h in sdb.items(): sdb_hash[h].append(p)

    shared_hashes = set(home_hash) & set(sdb_hash)
    only_home_hashes = set(home_hash) - set(sdb_hash)
    only_sdb_hashes = set(sdb_hash) - set(home_hash)

    same_path_same_hash = 0
    same_path_conflict = 0
    for p,h in home.items():
        if p in sdb:
            if sdb[p] == h:
                same_path_same_hash += 1
            else:
                same_path_conflict += 1

    duplicate_bytes_sdb = 0
    for h in shared_hashes:
        # potencial minimo liberavel: uma copia SDB por hash compartilhado.
        p = sdb_hash[h][0]
        duplicate_bytes_sdb += stat_size(args.sdb_root, p)

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8") as f:
        f.write("sha256\thome_paths\tsdb_paths\texample_home\texample_sdb\n")
        for h in sorted(shared_hashes):
            f.write(
                f"{h}\t{len(home_hash[h])}\t{len(sdb_hash[h])}\t"
                f"{home_hash[h][0]}\t{sdb_hash[h][0]}\n"
            )

    with args.conflicts_out.open("w", encoding="utf-8") as f:
        f.write(
            "relative_path\thome_sha256\tsdb_sha256\t"
            "home_bytes\tsdb_bytes\thome_mtime\tsdb_mtime\tsame_size\n"
        )
        for p,h in sorted(home.items()):
            if p not in sdb or sdb[p] == h:
                continue
            hp=args.home_root/p
            sp=args.sdb_root/p
            try:
                hs=hp.stat()
                hb=hs.st_size
                hmti=int(hs.st_mtime)
            except FileNotFoundError:
                hb=0; hmti=0
            try:
                ss=sp.stat()
                sb=ss.st_size
                smti=int(ss.st_mtime)
            except FileNotFoundError:
                sb=0; smti=0
            f.write(
                f"{p}\t{h}\t{sdb[p]}\t{hb}\t{sb}\t"
                f"{hmti}\t{smti}\t{1 if hb == sb and hb > 0 else 0}\n"
            )

    print(f"home_manifest={hm}")
    print(f"sdb_manifest={sm}")
    print(f"home_files={len(home)}")
    print(f"sdb_files={len(sdb)}")
    print(f"home_unique_hashes={len(home_hash)}")
    print(f"sdb_unique_hashes={len(sdb_hash)}")
    print(f"shared_hashes={len(shared_hashes)}")
    print(f"only_home_hashes={len(only_home_hashes)}")
    print(f"only_sdb_hashes={len(only_sdb_hashes)}")
    print(f"same_relative_path_same_hash={same_path_same_hash}")
    print(f"same_relative_path_conflict={same_path_conflict}")
    print(f"minimum_redundant_bytes_in_sdb={duplicate_bytes_sdb}")
    print(f"minimum_redundant_human={human(duplicate_bytes_sdb)}")
    print(f"overlap_report={args.out}")
    print(f"conflict_report={args.conflicts_out}")
    print("status=audit_only_no_files_deleted")

if __name__ == "__main__":
    main()
