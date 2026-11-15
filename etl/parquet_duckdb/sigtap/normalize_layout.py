#!/usr/bin/env python3
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPLACE_RE = re.compile(
    r"^REPLACE\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*CHR\(\s*\d+\s*\)\s*,\s*NULL\s*\)$",
    re.I,
)

def normalize_field(expr: str) -> str:
    expr = expr.strip()
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", expr):
        return expr.lower()
    m = REPLACE_RE.fullmatch(expr)
    if m:
        return m.group(1).lower()
    raise ValueError(f"expressao de coluna nao suportada: {expr}")

def parse_layout(path: Path):
    rows = []
    with path.open("r", encoding="latin-1", newline="") as f:
        for lineno, raw in enumerate(f, start=1):
            line = raw.rstrip("\r\n")
            if lineno == 1:
                continue
            if not line.strip():
                continue
            parts = [x.strip() for x in line.split(",")]
            if len(parts) < 5:
                raise ValueError(f"linha {lineno}: menos de 5 campos: {line}")
            field_expr = ",".join(parts[:-4]).strip()
            width_s, start_s, end_s, source_type = parts[-4:]
            try:
                width = int(width_s)
                start = int(start_s)
                end = int(end_s)
            except ValueError as exc:
                raise ValueError(
                    f"linha {lineno}: largura/inicio/fim invalidos: {line}"
                ) from exc
            field = normalize_field(field_expr)
            if width != end - start + 1:
                raise ValueError(
                    f"linha {lineno}: width={width} start={start} end={end}: {line}"
                )
            if rows and start != rows[-1][3] + 1:
                raise ValueError(
                    f"linha {lineno}: gap/overlap prev_end={rows[-1][3]} start={start}: {line}"
                )
            rows.append((field, width, start, end, source_type, field_expr))
    if not rows:
        raise ValueError("layout sem campos")
    return rows

def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("layout", type=Path)
    args = ap.parse_args()
    try:
        rows = parse_layout(args.layout)
    except Exception as exc:
        print(f"LAYOUT_PARSE_ERROR {args.layout.name}: {exc}", file=sys.stderr)
        return 11
    print("field\twidth\tstart\tend\tsource_type\tsource_expr")
    for row in rows:
        print("\t".join(map(str, row)))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
