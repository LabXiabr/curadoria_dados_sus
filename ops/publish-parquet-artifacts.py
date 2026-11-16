#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import errno
import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_POLICY = ROOT / "catalog" / "parquet_publication.tsv"

FIELDS = [
    "dataset_id", "system", "layer", "object", "competencia", "filename",
    "bytes", "public_url", "link_type", "published_at", "description",
]

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def read_marker(path: Path) -> dict[str, str]:
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def competencia_from_path(path: Path) -> str:
    for part in path.parts:
        m = re.fullmatch(r"competencia=(\d{6})", part)
        if m:
            return m.group(1)
    return ""

def gate_allows(rule: dict[str, str], src: Path, lake: Path) -> tuple[bool, str]:
    policy = (rule.get("gate_policy") or "").strip()
    comp = competencia_from_path(src)
    if not comp:
        return False, "competencia ausente no path"

    if policy == "cnes_bronze_base_complete":
        marker = lake / "state" / "cnes" / f"base_complete_{comp}.ok"
        meta = read_marker(marker)
        if meta.get("competencia") != comp or meta.get("status") != "complete":
            return False, f"base_complete ausente/invalido: {marker}"
        return True, marker.name

    if policy == "cnes_silver_snapshot_global":
        snap = lake / "state" / "cnes" / f"silver_snapshot_{comp}.ok"
        glob = lake / "state" / "cnes" / f"qc_global_{comp}.ok"
        smeta = read_marker(snap)
        gmeta = read_marker(glob)
        if smeta.get("competencia") != comp or smeta.get("status") != "complete":
            return False, f"snapshot Silver ausente/invalido: {snap}"
        if gmeta.get("competencia") != comp or gmeta.get("status") != "validated":
            return False, f"QC global ausente/invalido: {glob}"
        return True, f"{snap.name}+{glob.name}"

    return False, f"gate_policy desconhecida: {policy}"

def hardlink(src: Path, dst: Path):
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        try:
            if os.path.samefile(src, dst):
                return
        except OSError:
            pass
        dst.unlink()
    try:
        os.link(src, dst)
    except OSError as exc:
        if exc.errno == errno.EXDEV:
            die(
                f"hardlink impossivel entre filesystems: {src} -> {dst}; "
                "nao foi feita copia",
                30,
            )
        raise

def http_qc(rows: list[dict[str, str]], host: str, base: str):
    if not rows or not shutil.which("curl"):
        return
    seen = set()
    for row in rows:
        ds = row["dataset_id"]
        if ds in seen:
            continue
        seen.add(ds)
        url = base.rstrip("/") + "/" + row["public_url"].split("/files/", 1)[1]
        common = ["curl", "-sS", "-o", "/dev/null", "-H", f"Host: {host}"]
        head = subprocess.run(
            common + ["-I", "-w", "%{http_code}", url],
            text=True,
            capture_output=True,
        )
        hcode = head.stdout.strip()[-3:] if head.returncode == 0 else ""
        rng = subprocess.run(
            common + ["-H", "Range: bytes=0-0", "-w", "%{http_code}", url],
            text=True,
            capture_output=True,
        )
        rcode = rng.stdout.strip()[-3:] if rng.returncode == 0 else ""
        if hcode not in {"200", "206"} or rcode != "206":
            die(
                f"QC HTTP falhou dataset={ds} HEAD={hcode} Range={rcode} url={url}",
                40,
            )
        print(f"HTTP_QC_OK dataset={ds} head={hcode} range={rcode} url={url}")

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Projeta subconjuntos publicaveis por hardlink dentro da arvore /dados/abertos/suslake"
    )
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"),
    )
    ap.add_argument(
        "--public-root",
        default=os.environ.get("PARQUET_PUBLIC_ROOT", "/dados/abertos"),
    )
    ap.add_argument("--policy", type=Path, default=DEFAULT_POLICY)
    ap.add_argument("--dataset", action="append")
    ap.add_argument(
        "--catalog",
        default=os.environ.get(
            "PARQUET_PUBLIC_CATALOG",
            "/dados/suslake_runtime/state/publication/parquet_catalog.tsv",
        ),
    )
    ap.add_argument(
        "--http-base",
        default=os.environ.get(
            "PARQUET_HTTP_TEST_BASE",
            "http://127.0.0.1:8766/files",
        ),
    )
    ap.add_argument(
        "--http-host",
        default=os.environ.get("PARQUET_HTTP_TEST_HOST", "dados.labx.ia.br"),
    )
    ap.add_argument("--skip-http-qc", action="store_true")
    args = ap.parse_args()

    lake = Path(args.lake_root).resolve()
    public = Path(args.public_root).resolve()
    catalog = Path(args.catalog).resolve()
    rules = read_tsv(args.policy)

    wanted = set(args.dataset or [])
    known = {r["dataset_id"] for r in rules}
    unknown = wanted - known
    if unknown:
        die("dataset desconhecido: " + ",".join(sorted(unknown)), 2)

    now = datetime.now(timezone.utc).isoformat()
    current_rows = []

    for rule in rules:
        if rule["status"].lower() != "published":
            continue
        if wanted and rule["dataset_id"] not in wanted:
            continue

        src_root = lake / rule["source_rel"]
        if not src_root.is_dir():
            print(
                f"PARQUET_PUBLIC_SKIP dataset={rule['dataset_id']} "
                f"object={rule['object']} reason=source_dir_absent:{src_root}"
            )
            continue

        matches = sorted(p for p in src_root.glob(rule["glob"]) if p.is_file())
        if not matches:
            print(
                f"PARQUET_PUBLIC_SKIP dataset={rule['dataset_id']} "
                f"object={rule['object']} reason=no_files"
            )
            continue

        for src in matches:
            allowed, note = gate_allows(rule, src, lake)
            if not allowed:
                print(
                    f"PARQUET_PUBLIC_SKIP dataset={rule['dataset_id']} "
                    f"object={rule['object']} file={src.name} reason={note}"
                )
                continue

            rel = src.relative_to(src_root)
            dst_rel = Path(rule["public_prefix"]) / rel
            dst = public / dst_rel
            hardlink(src, dst)
            comp = competencia_from_path(src)
            url = "https://dados.labx.ia.br/files/" + "/".join(
                quote(x) for x in dst_rel.parts
            )
            st = src.stat()
            current_rows.append(
                {
                    "dataset_id": rule["dataset_id"],
                    "system": rule["system"],
                    "layer": rule["layer"],
                    "object": rule["object"],
                    "competencia": comp,
                    "filename": src.name,
                    "bytes": str(st.st_size),
                    "public_url": url,
                    "link_type": "hardlink",
                    "published_at": now,
                    "description": rule["description"],
                }
            )
            print(
                f"PARQUET_PUBLIC_OK dataset={rule['dataset_id']} "
                f"object={rule['object']} competencia={comp} gate={note}"
            )

    if not current_rows:
        die("nenhum Parquet elegivel foi publicado", 5)

    rows = list(current_rows)
    if wanted and catalog.is_file():
        previous = read_tsv(catalog)
        rows = [r for r in previous if r.get("dataset_id") not in wanted] + rows

    rows.sort(
        key=lambda r: (
            r["dataset_id"], r["object"], r["competencia"], r["filename"]
        )
    )
    catalog.parent.mkdir(parents=True, exist_ok=True)
    tmp = catalog.with_name(catalog.name + f".partial.{os.getpid()}")
    with tmp.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=FIELDS, delimiter="\t", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(rows)
    os.replace(tmp, catalog)

    if not args.skip_http_qc:
        http_qc(current_rows, args.http_host, args.http_base)

    by_ds = {}
    for row in current_rows:
        by_ds[row["dataset_id"]] = by_ds.get(row["dataset_id"], 0) + 1

    print(
        f"PARQUET_PUBLICATION_COMPLETE published_files={len(current_rows)} "
        f"catalog_files={len(rows)} catalog={catalog}"
    )
    for ds, n in sorted(by_ds.items()):
        print(f"dataset={ds} files={n}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
