#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from collections import Counter
from pathlib import Path

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def q(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"

def duck_scalar(sql: str) -> int:
    p = subprocess.run(["duckdb","-noheader","-csv","-c",sql],text=True,capture_output=True)
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return int(p.stdout.strip() or 0)

def main() -> int:
    ap=argparse.ArgumentParser(description="QC Silver de dominios/layouts DATASUS")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()
    lake=Path(args.lake_root)
    state=lake/"state"/"reference"/"datasus_auxiliary"
    domain=lake/"silver"/"reference"/"datasus_domain"/"current.parquet"
    layout=lake/"silver"/"reference"/"datasus_layout_field"/"current.parquet"
    issues=state/"build_issues.tsv"

    if not domain.is_file():
        die(f"domain ausente: {domain}",4)
    if not layout.is_file():
        die(f"layout ausente: {layout}",5)

    domain_rows=duck_scalar(f"SELECT count(*) FROM read_parquet({q(str(domain))})")
    layout_rows=duck_scalar(f"SELECT count(*) FROM read_parquet({q(str(layout))})")
    missing_code=duck_scalar(
        f"SELECT count(*) FROM read_parquet({q(str(domain))}) "
        "WHERE code_literal IS NULL OR code_literal=''"
    )
    missing_prov=duck_scalar(
        f"SELECT count(*) FROM read_parquet({q(str(domain))}) "
        "WHERE system IS NULL OR source_id IS NULL OR source_sha256 IS NULL "
        "OR system='' OR source_id='' OR source_sha256=''"
    )
    conflicts=duck_scalar(
        f"SELECT count(*) FROM read_parquet({q(str(domain))}) "
        "WHERE conflicting_label='1'"
    )
    partial_layout=duck_scalar(
        f"SELECT count(*) FROM read_parquet({q(str(layout))}) "
        "WHERE parse_status <> 'parsed'"
    )

    issue_counts=Counter()
    if issues.is_file():
        with issues.open(encoding="utf-8",newline="") as f:
            for r in csv.DictReader(f,delimiter="\t"):
                issue_counts[r.get("issue_class","unknown")]+=1

    print(f"domain_rows={domain_rows}")
    print(f"layout_rows={layout_rows}")
    print(f"missing_code={missing_code}")
    print(f"missing_provenance={missing_prov}")
    print(f"conflicting_label_rows={conflicts}")
    print(f"partial_layout_rows={partial_layout}")
    for k,v in sorted(issue_counts.items()):
        print(f"issue_{k}={v}")

    if domain_rows == 0 or layout_rows == 0 or missing_code or missing_prov:
        die("DATASUS_REFERENCE_QC_FAIL",30)

    marker=state/"reference_qc.ok"
    marker.write_text(
        "\n".join([
            f"domain_rows={domain_rows}",
            f"layout_rows={layout_rows}",
            f"conflicting_label_rows={conflicts}",
            f"partial_layout_rows={partial_layout}",
            "status=validated",
            "",
        ]),
        encoding="utf-8"
    )
    print(f"DATASUS_REFERENCE_QC_OK marker={marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
