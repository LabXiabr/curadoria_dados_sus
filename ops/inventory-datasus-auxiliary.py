#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import subprocess
from collections import Counter
from pathlib import Path

def marker(path: Path) -> dict[str, str]:
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def main() -> int:
    ap = argparse.ArgumentParser(description="Inventaria fontes auxiliares DATASUS adquiridas")
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"))
    args = ap.parse_args()

    lake = Path(args.lake_root)
    state = lake / "state" / "reference" / "datasus_auxiliary"
    state.mkdir(parents=True, exist_ok=True)

    rows = []
    totals = Counter()

    for m in sorted(state.glob("*_current.ok")):
        if m.name == "inventory_current.ok":
            continue
        meta = marker(m)
        source_id = meta.get("source_id", m.name.removesuffix("_current.ok"))
        system = meta.get("system", "")
        status = meta.get("status", "")
        sha = meta.get("sha256", "")
        path = meta.get("path", "")
        listing = meta.get("listing", "")
        members = meta.get("members", "")

        counts = Counter()
        member_rows = 0
        if members and Path(members).is_file():
            for r in read_tsv(Path(members)):
                counts[r.get("member_class", "unknown")] += 1
                member_rows += 1
                totals[r.get("member_class", "unknown")] += 1

        rows.append({
            "system": system,
            "source_id": source_id,
            "status": status,
            "sha256": sha,
            "archive_path": path,
            "listing_path": listing,
            "members": member_rows,
            "def": counts["tabwin_definition"],
            "cnv": counts["conversion_domain"],
            "dbd": counts["database_definition"],
            "dbf": counts["domain_or_tabular_dbf"],
            "tabular": counts["tabular_csv"] + counts["text_or_fixed_width"],
            "documentation": counts["documentation"],
            "other": counts["other"],
        })

    ts = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"],
        text=True, capture_output=True, check=True
    ).stdout.strip()

    report = state / f"inventory_{ts}.tsv"
    fields = [
        "system","source_id","status","sha256","archive_path","listing_path",
        "members","def","cnv","dbd","dbf","tabular","documentation","other"
    ]
    with report.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    current = state / "inventory_current.ok"
    current.write_text(
        "\n".join([
            f"timestamp={ts}",
            f"sources={len(rows)}",
            f"report={report}",
            "status=complete",
            "",
        ]),
        encoding="utf-8"
    )

    print(f"DATASUS_AUX_INVENTORY_OK sources={len(rows)} report={report}")
    print("\t".join(fields))
    for r in rows:
        print("\t".join(str(r[x]) for x in fields))
    print(
        "TOTAL_CLASSES "
        + " ".join(f"{k}={v}" for k,v in sorted(totals.items()))
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
