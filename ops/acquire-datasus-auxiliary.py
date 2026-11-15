#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "catalog" / "auxiliary_sources.tsv"

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def read_tsv(path: Path):
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()

def classify_member(name: str) -> str:
    ext = Path(name).suffix.lower().lstrip(".")
    return {
        "def": "tabwin_definition",
        "cnv": "conversion_domain",
        "dbd": "database_definition",
        "dbf": "domain_or_tabular_dbf",
        "csv": "tabular_csv",
        "txt": "text_or_fixed_width",
        "pdf": "documentation",
        "doc": "documentation",
        "docx": "documentation",
    }.get(ext, "other")

def curl_download(url: str, dest: Path):
    cmd = [
        "curl", "--fail", "--location", "--retry", "4", "--retry-all-errors",
        "--retry-delay", "3", "--connect-timeout", "30", "--progress-bar",
        "--output", str(dest), url,
    ]
    subprocess.run(cmd, check=True)

def curl_list(url: str) -> str:
    p = subprocess.run(
        ["curl", "--fail", "--silent", "--show-error", "--list-only", url],
        check=True, text=True, capture_output=True,
    )
    return p.stdout.replace("\r", "")

def write_zip_manifest(path: Path, source_id: str, archive_sha: str, state: Path) -> Path:
    out = state / f"{source_id}_{archive_sha}.members.tsv"
    with zipfile.ZipFile(path) as z:
        with out.open("w", encoding="utf-8", newline="") as f:
            w = csv.writer(f, delimiter="\t", lineterminator="\n")
            w.writerow(["source_id","archive_sha256","member","member_bytes","crc32","extension","member_class"])
            for i in z.infolist():
                if i.is_dir():
                    continue
                ext = Path(i.filename).suffix.lower().lstrip(".")
                w.writerow([
                    source_id, archive_sha, i.filename, i.file_size,
                    f"{i.CRC:08x}", ext, classify_member(i.filename),
                ])
    return out

def current_marker(state: Path, source_id: str) -> Path:
    return state / f"{source_id}_current.ok"

def marker_path(marker: Path) -> Path | None:
    if not marker.is_file():
        return None
    vals = {}
    for line in marker.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            vals[k] = v
    p = vals.get("path")
    return Path(p) if p else None

def main() -> int:
    ap = argparse.ArgumentParser(description="Adquire e versiona fontes auxiliares DATASUS")
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"))
    ap.add_argument("--system", action="append", help="Filtra sistema; repetivel")
    ap.add_argument("--source", action="append", help="Filtra source_id; repetivel")
    ap.add_argument("--refresh", action="store_true", help="Baixa novamente fontes rolling")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not shutil.which("curl"):
        die("curl ausente", 3)

    lake = Path(args.lake_root).resolve()
    raw_root = lake / "raw" / "reference" / "datasus_auxiliary"
    state = lake / "state" / "reference" / "datasus_auxiliary"
    state.mkdir(parents=True, exist_ok=True)

    wanted_systems = {x.upper() for x in (args.system or [])}
    wanted_sources = set(args.source or [])
    rules = read_tsv(args.catalog)
    selected = [
        r for r in rules
        if r.get("status") in {"active", "discover"}
        and (not wanted_systems or r["system"].upper() in wanted_systems)
        and (not wanted_sources or r["source_id"] in wanted_sources)
    ]
    if not selected:
        die("nenhuma fonte selecionada", 4)

    for r in selected:
        system, source_id, url = r["system"], r["source_id"], r["url"]
        temporal = r["temporal_mode"]

        if r["kind"] == "auxiliary_directory":
            print(f"AUX_DISCOVER source={source_id} url={url}")
            if args.dry_run:
                continue
            listing = curl_list(url)
            ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            out = state / f"{source_id}_{ts}.listing.txt"
            out.write_text(listing, encoding="utf-8")
            current_marker(state, source_id).write_text(
                "\n".join([
                    f"system={system}", f"source_id={source_id}", f"url={url}",
                    f"listing={out}", f"observed_at={datetime.now(timezone.utc).isoformat()}",
                    "status=discovered", "",
                ]), encoding="utf-8",
            )
            continue

        marker = current_marker(state, source_id)
        existing = marker_path(marker)
        if existing and existing.is_file() and temporal == "fixed_period" and not args.refresh:
            print(f"AUX_SKIP_FIXED source={source_id} path={existing}")
            continue
        if existing and existing.is_file() and temporal in {"fixed_snapshot"} and not args.refresh:
            print(f"AUX_SKIP_FIXED source={source_id} path={existing}")
            continue
        if existing and existing.is_file() and temporal == "rolling_snapshot" and not args.refresh:
            print(f"AUX_SKIP_CURRENT source={source_id} path={existing} hint=use_--refresh")
            continue

        name = Path(urlparse(url).path).name
        if not name:
            die(f"URL sem filename: {url}", 5)
        print(f"AUX_DOWNLOAD system={system} source={source_id} url={url}")
        if args.dry_run:
            continue

        with tempfile.TemporaryDirectory(prefix="datasus_aux_") as td:
            tmp = Path(td) / name
            curl_download(url, tmp)
            digest = sha256(tmp)
            destdir = raw_root / f"system={system}" / f"source={source_id}" / f"sha256={digest}"
            destdir.mkdir(parents=True, exist_ok=True)
            dest = destdir / name
            if not dest.exists():
                os.replace(tmp, dest)

        member_manifest = ""
        suffix = dest.suffix.lower()
        if suffix == ".zip":
            try:
                member_manifest = str(write_zip_manifest(dest, source_id, digest, state))
            except zipfile.BadZipFile:
                die(f"ZIP invalido: {dest}", 21)

        marker.write_text(
            "\n".join([
                f"system={system}", f"source_id={source_id}", f"url={url}",
                f"temporal_mode={temporal}", f"sha256={digest}", f"path={dest}",
                f"members={member_manifest}",
                f"observed_at={datetime.now(timezone.utc).isoformat()}",
                "status=validated", "",
            ]), encoding="utf-8",
        )
        print(f"AUX_OK system={system} source={source_id} sha256={digest} path={dest}")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
