#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import struct
import zipfile
from pathlib import Path

def read_marker(path: Path):
    out = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k, v = line.split("=", 1)
            out[k] = v
    return out

def decode(data: bytes):
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace"), "latin-1-replace"

def dbf_fields(data: bytes):
    if len(data) < 33:
        return []
    hlen = struct.unpack("<H", data[8:10])[0]
    out = []
    off = 32
    while off + 32 <= min(hlen, len(data)) and data[off] != 0x0D:
        d = data[off:off+32]
        name = d[:11].split(b"\x00",1)[0].decode("cp1252",errors="replace").strip()
        if name:
            out.append(f"{name}:{chr(d[11])}:{d[16]}:{d[17]}")
        off += 32
    return out

def main():
    ap = argparse.ArgumentParser(description="Inspeciona amostras reais de auxiliares DATASUS")
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    ap.add_argument("--max-per-class", type=int, default=3)
    args = ap.parse_args()

    lake = Path(args.lake_root)
    state = lake/"state"/"reference"/"datasus_auxiliary"
    out = state/"inspection.tsv"
    rows = []

    for m in sorted(state.glob("*_current.ok")):
        if m.name in {"inventory_current.ok"}:
            continue
        meta = read_marker(m)
        path = meta.get("path","")
        if not path or not Path(path).is_file() or Path(path).suffix.lower() != ".zip":
            continue
        source_id = meta.get("source_id","")
        system = meta.get("system","")
        counts = {}
        with zipfile.ZipFile(path) as z:
            for info in z.infolist():
                if info.is_dir():
                    continue
                ext = Path(info.filename).suffix.lower().lstrip(".")
                cls = ext if ext in {"def","cnv","dbf","dbd","txt"} else "other"
                counts.setdefault(cls,0)
                if counts[cls] >= args.max_per_class:
                    continue
                counts[cls] += 1
                data = z.read(info)
                sample = ""
                encoding = ""
                fields = ""
                if ext == "dbf":
                    fields = "|".join(dbf_fields(data))
                else:
                    text, encoding = decode(data[:65536])
                    sample = "\\n".join(
                        x.strip() for x in text.splitlines() if x.strip()
                    )[:4000]
                rows.append({
                    "system":system,"source_id":source_id,"member":info.filename,
                    "extension":ext,"bytes":str(info.file_size),"encoding":encoding,
                    "dbf_fields":fields,"sample":sample,
                })

    fields=["system","source_id","member","extension","bytes","encoding","dbf_fields","sample"]
    with out.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(rows)
    print(f"DATASUS_AUX_INSPECTION_OK rows={len(rows)} report={out}")
    for r in rows:
        print(
            f"{r['system']} {r['source_id']} {r['extension']} "
            f"{r['member']} bytes={r['bytes']}"
        )
    return 0

if __name__=="__main__":
    raise SystemExit(main())
