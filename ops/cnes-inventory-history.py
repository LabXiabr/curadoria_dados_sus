#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
from pathlib import Path

RE_COMP = re.compile(r"^(\d{6})$")

def marker(path: Path) -> dict[str, str]:
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def comps_from_raw_zips(root: Path) -> set[str]:
    out = set()
    if not root.is_dir():
        return out
    for p in root.glob("competencia=*/BASE_DE_DADOS_CNES_*.ZIP"):
        if not p.is_file():
            continue
        parent = p.parent.name
        comp = parent.split("=", 1)[1] if "=" in parent else ""
        if RE_COMP.fullmatch(comp):
            out.add(comp)
    return out

def comps_from_markers(state: Path, prefix: str) -> set[str]:
    out = set()
    for p in state.glob(prefix + "_*.ok"):
        m = re.search(r"_(\d{6})\.ok$", p.name)
        if m:
            out.add(m.group(1))
    return out

def count_files(root: Path, comp: str) -> int:
    if not root.is_dir():
        return 0
    return sum(
        1
        for p in root.glob(f"*/competencia={comp}/part-*.parquet")
        if p.is_file()
    )

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Inventaria cobertura temporal CNES Raw/Bronze/Silver/publicacao"
    )
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslabx"),
    )
    ap.add_argument(
        "--public-root",
        default=os.environ.get("PARQUET_PUBLIC_ROOT", "/dados/abertos"),
    )
    args = ap.parse_args()

    lake = Path(args.lake_root)
    public = Path(args.public_root)
    state = lake / "state" / "cnes"
    raw = lake / "raw" / "cnes" / "base_dados"
    bronze = lake / "bronze" / "cnes"
    silver = lake / "silver" / "cnes"

    comps = set()
    comps |= comps_from_raw_zips(raw)
    comps |= comps_from_markers(state, "raw_base")
    comps |= comps_from_markers(state, "qc_bronze")
    comps |= comps_from_markers(state, "base_complete")
    comps |= comps_from_markers(state, "qc_global")
    comps |= comps_from_markers(state, "silver_snapshot")

    rows = []
    for comp in sorted(comps):
        raw_zip = raw / f"competencia={comp}" / f"BASE_DE_DADOS_CNES_{comp}.ZIP"
        bronze_meta = marker(state / f"qc_bronze_{comp}.ok")
        base_meta = marker(state / f"base_complete_{comp}.ok")
        global_meta = marker(state / f"qc_global_{comp}.ok")
        snap_meta = marker(state / f"silver_snapshot_{comp}.ok")

        bronze_tables = count_files(bronze, comp)
        silver_objects = count_files(silver, comp)
        public_bronze = count_files(public / "bronze" / "cnes", comp)
        public_silver = count_files(public / "silver" / "cnes", comp)

        status = "raw_only"
        if bronze_meta.get("competencia") == comp:
            status = "bronze_qc"
        if base_meta.get("competencia") == comp and base_meta.get("status") == "complete":
            status = "base_complete"
        if global_meta.get("competencia") == comp and global_meta.get("status") == "validated":
            status = "global_qc"
        if snap_meta.get("competencia") == comp and snap_meta.get("status") == "complete":
            status = "silver_snapshot"

        rows.append(
            {
                "competencia": comp,
                "raw_zip": int(raw_zip.is_file()),
                "bronze_tables": bronze_tables,
                "qc_bronze": int(bool(bronze_meta)),
                "base_complete": int(base_meta.get("status") == "complete"),
                "qc_global": int(global_meta.get("status") == "validated"),
                "silver_objects": silver_objects,
                "silver_snapshot": int(snap_meta.get("status") == "complete"),
                "public_bronze_files": public_bronze,
                "public_silver_files": public_silver,
                "status": status,
            }
        )

    ts = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    state.mkdir(parents=True, exist_ok=True)
    report = state / f"history_inventory_{ts}.tsv"
    fields = [
        "competencia", "raw_zip", "bronze_tables", "qc_bronze",
        "base_complete", "qc_global", "silver_objects", "silver_snapshot",
        "public_bronze_files", "public_silver_files", "status",
    ]
    with report.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    latest = state / "history_inventory_current.ok"
    latest.write_text(
        "\n".join(
            [
                f"timestamp={ts}",
                f"competencias={len(rows)}",
                f"report={report}",
                "status=complete",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"CNES_HISTORY_INVENTORY_OK competencias={len(rows)} report={report}")
    print("\t".join(fields))
    for row in rows:
        print("\t".join(str(row[x]) for x in fields))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
