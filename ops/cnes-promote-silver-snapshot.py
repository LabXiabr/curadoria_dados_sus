#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import errno
import os
import re
import subprocess
import sys
from pathlib import Path

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def read_marker(path: Path) -> dict[str, str]:
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def hardlink_immutable(src: Path, dst: Path) -> str:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if os.path.samefile(src, dst):
                return "existing_same_inode"
        except OSError:
            pass
        die(
            f"snapshot historico ja existe com outro inode: {dst}; "
            "nao sobrescrever historico automaticamente",
            30,
        )
    try:
        os.link(src, dst)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            die(f"hardlink impossivel entre filesystems: {src} -> {dst}", 31)
        raise
    return "linked"

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Promove Silver CNES current homologada para snapshot historico por competencia"
    )
    ap.add_argument("--competencia", required=True)
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslabx"),
    )
    args = ap.parse_args()

    if not re.fullmatch(r"\d{6}", args.competencia):
        die("competencia deve ser YYYYMM", 2)

    lake = Path(args.lake_root).resolve()
    state = lake / "state" / "cnes"
    silver = lake / "silver" / "cnes"

    global_marker = state / f"qc_global_{args.competencia}.ok"
    global_meta = read_marker(global_marker)
    if (
        global_meta.get("competencia") != args.competencia
        or global_meta.get("status") != "validated"
    ):
        die(f"QC global nao homologado: {global_marker}", 4)

    current_marker = state / "silver_current.ok"
    current_meta = read_marker(current_marker)
    if (
        current_meta.get("competencia") != args.competencia
        or current_meta.get("status") != "complete"
    ):
        die(
            f"Silver current nao corresponde a {args.competencia}: {current_marker}",
            5,
        )

    report = Path(current_meta.get("report", ""))
    if not report.is_file():
        die(f"relatorio Silver ausente: {report}", 6)

    with report.open(encoding="utf-8", newline="") as f:
        report_rows = list(csv.DictReader(f, delimiter="\t"))

    rows = []
    for row in report_rows:
        if row.get("status") != "ok":
            die(f"objeto Silver nao homologado: {row}", 7)
        obj = row["object"]
        src = silver / obj / "current.parquet"
        if not src.is_file():
            die(f"current.parquet ausente: {src}", 8)
        dst = silver / obj / f"competencia={args.competencia}" / "part-000.parquet"
        action = hardlink_immutable(src, dst)
        st = src.stat()
        rows.append(
            {
                "object": obj,
                "rows": row["silver_rows"],
                "bytes": str(st.st_size),
                "device": str(st.st_dev),
                "inode": str(st.st_ino),
                "action": action,
                "snapshot": str(dst),
            }
        )
        print(
            f"CNES_SILVER_SNAPSHOT object={obj} rows={row['silver_rows']} "
            f"action={action}"
        )

    ts = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    manifest = state / f"silver_snapshot_{args.competencia}_{ts}.tsv"
    with manifest.open("w", encoding="utf-8", newline="") as f:
        fields = ["object", "rows", "bytes", "device", "inode", "action", "snapshot"]
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(rows)

    marker = state / f"silver_snapshot_{args.competencia}.ok"
    marker.write_text(
        "\n".join(
            [
                f"competencia={args.competencia}",
                f"timestamp={ts}",
                f"objects={len(rows)}",
                f"manifest={manifest}",
                f"source_marker={current_marker}",
                f"global_qc_marker={global_marker}",
                "storage=hardlink_current_to_competencia_partition",
                "immutability=existing_different_inode_blocks_promotion",
                "status=complete",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(
        f"CNES_SILVER_SNAPSHOT_OK competencia={args.competencia} "
        f"objects={len(rows)}"
    )
    print(f"marker={marker}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
