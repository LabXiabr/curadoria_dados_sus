#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import re
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "catalog" / "datasets.tsv"


def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Valida datasets publicaveis in-place sob /dados/abertos/suslabx. "
            "Nao cria mais /dados/abertos/{bronze,silver}."
        )
    )
    ap.add_argument("--root", default="/dados/abertos")
    ap.add_argument("--dataset", action="append")
    args = ap.parse_args()

    root = Path(args.root).resolve()
    wanted = set(args.dataset or [])
    counts = Counter()

    for r in read_tsv(CATALOG):
        ds = r["dataset_id"]
        if r.get("status") != "published":
            continue
        if wanted and ds not in wanted:
            continue
        if r.get("layer") not in {"bronze", "silver"}:
            continue

        rel = Path(r["discovery_path"])
        if not rel.parts or rel.parts[0] != "suslabx":
            raise SystemExit(
                f"ERRO dataset publicado fora de suslabx: {ds} path={rel}"
            )

        src_root = root / rel
        if not src_root.is_dir():
            print(
                f"PUBLIC_IN_PLACE_SKIP dataset={ds} "
                f"reason=source_absent:{src_root}"
            )
            continue

        rx = re.compile(r.get("file_regex") or r".*")
        matched = sum(
            1
            for p in src_root.rglob("*")
            if p.is_file() and rx.search(p.name)
        )
        counts[ds] += matched
        print(
            f"PUBLIC_IN_PLACE_OK dataset={ds} files={matched} path={src_root}"
        )

    if wanted:
        absent = wanted - set(counts)
        if absent:
            print("PUBLIC_IN_PLACE_NOTICE no_files=" + ",".join(sorted(absent)))

    print(
        f"PUBLIC_IN_PLACE_COMPLETE files={sum(counts.values())} "
        f"datasets={len(counts)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
