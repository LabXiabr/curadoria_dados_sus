#!/usr/bin/env python3
from __future__ import annotations

import csv
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def die(msg: str) -> None:
    raise SystemExit(f"ERRO: {msg}")

def validate_tsv(path: Path) -> tuple[int, int]:
    with path.open(encoding="utf-8", newline="") as f:
        rows = [
            row for row in csv.reader(f, delimiter="\t")
            if any(x != "" for x in row)
            and not (row and row[0].lstrip().startswith("#"))
        ]
    if not rows:
        die(f"TSV vazio: {path}")
    width = len(rows[0])
    if width == 0:
        die(f"cabecalho vazio: {path}")
    for i, row in enumerate(rows[1:], 2):
        if len(row) != width:
            die(f"{path}:{i}: colunas={len(row)} esperado={width}")
        if row == rows[0]:
            die(f"{path}:{i}: cabecalho duplicado")
    return len(rows) - 1, width

def main() -> int:
    tsvs = sorted(
        list((ROOT / "catalog").glob("*.tsv"))
        + list((ROOT / "config" / "reference").glob("*.tsv"))
        + list((ROOT / "systems").glob("**/*.tsv"))
    )
    total_rows = 0
    for path in tsvs:
        rows, _ = validate_tsv(path)
        total_rows += rows

    contract = ROOT / "catalog" / "source_schema_contract.tsv"
    with contract.open(encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f, delimiter="\t"))
    if not rows:
        die("source_schema_contract.tsv vazio")
    patterns = []
    for i, row in enumerate(rows, 2):
        pat = row.get("schema_pattern", "")
        if not pat:
            die(f"{contract}:{i}: schema_pattern vazio")
        try:
            rx = re.compile(pat)
        except re.error as e:
            die(f"{contract}:{i}: regex invalida {pat!r}: {e}")
        patterns.append((pat, rx))

    qrules = ROOT / "catalog" / "quality_rules.tsv"
    with qrules.open(encoding="utf-8", newline="") as f:
        qrows = list(csv.DictReader(f, delimiter="\t"))
    ids = [r["rule_id"] for r in qrows]
    dup = sorted({x for x in ids if ids.count(x) > 1})
    if dup:
        die("quality rule_id duplicado: " + ",".join(dup))

    print(
        f"MODEL_CONTRACT_QC_OK tsv_files={len(tsvs)} "
        f"tsv_rows={total_rows} schema_patterns={len(patterns)} "
        f"quality_rules={len(qrows)}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
