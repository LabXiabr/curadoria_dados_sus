#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import struct
import subprocess
import sys
import tempfile
import unicodedata
import zipfile
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
DEFAULT_CATALOG = ROOT / "catalog" / "auxiliary_sources.tsv"

DBF_VERSIONS = {
    0x02, 0x03, 0x04, 0x05, 0x30, 0x31, 0x32, 0x43, 0x63,
    0x7B, 0x83, 0x87, 0x8B, 0xCB, 0xF5,
}

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"

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

def decode_text(data: bytes) -> tuple[str, str]:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return data.decode(enc), enc
        except UnicodeDecodeError:
            pass
    return data.decode("latin-1", errors="replace"), "latin-1-replace"

def slug(v: str) -> str:
    s = unicodedata.normalize("NFKD", v)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^A-Za-z0-9]+", "_", s).strip("_").lower()
    return s or "member"

def is_dbf(data: bytes) -> bool:
    if len(data) < 33 or data[0] not in DBF_VERSIONS:
        return False

    # Evita falso positivo em CNV textual iniciado por digito ASCII
    # (por exemplo byte 0x30, que tambem e uma versao DBF valida).
    month = data[2]
    day = data[3]
    if not (1 <= month <= 12 and 1 <= day <= 31):
        return False

    nrec = struct.unpack("<I", data[4:8])[0]
    hlen = struct.unpack("<H", data[8:10])[0]
    rlen = struct.unpack("<H", data[10:12])[0]

    if hlen < 33 or hlen > len(data) or rlen < 1:
        return False
    if (hlen - 33) % 32 != 0:
        return False
    if data[hlen - 1] != 0x0D:
        return False
    if nrec >= 2_000_000_000:
        return False

    # O EOF 0x1A e opcional; o payload minimo precisa caber.
    minimum = hlen + nrec * rlen
    return minimum <= len(data)

def parse_dbf(data: bytes) -> tuple[list[dict[str, str]], list[dict[str, str]], dict[str, int | str]]:
    if not is_dbf(data):
        raise ValueError("not_dbf")
    nrec = struct.unpack("<I", data[4:8])[0]
    hlen = struct.unpack("<H", data[8:10])[0]
    rlen = struct.unpack("<H", data[10:12])[0]

    fields = []
    off = 32
    while off + 32 <= hlen and data[off] != 0x0D:
        d = data[off:off+32]
        raw_name = d[:11].split(b"\x00", 1)[0]
        name = raw_name.decode("cp1252", errors="replace").strip()
        ftype = chr(d[11]) if d[11] else ""
        flen = d[16]
        dec = d[17]
        if name:
            fields.append({
                "name": name,
                "type": ftype,
                "length": str(flen),
                "decimal": str(dec),
            })
        off += 32

    expected = 1 + sum(int(f["length"]) for f in fields)
    if fields and expected != rlen:
        raise ValueError(f"dbf_record_length_mismatch expected={expected} header={rlen}")

    rows = []
    pos = hlen
    for recno in range(1, nrec + 1):
        if pos + rlen > len(data):
            raise ValueError(f"dbf_truncated record={recno}/{nrec}")
        rec = data[pos:pos+rlen]
        pos += rlen
        row = {"_source_row_number": str(recno), "_deleted": "1" if rec[:1] == b"*" else "0"}
        p = 1
        for f in fields:
            ln = int(f["length"])
            raw = rec[p:p+ln]
            p += ln
            value = raw.decode("cp1252", errors="replace").rstrip(" \x00")
            row[f["name"]] = value
        rows.append(row)

    return rows, fields, {
        "records": nrec,
        "header_length": hlen,
        "record_length": rlen,
        "version_byte": data[0],
    }

def parse_cnv_text(text: str) -> tuple[list[dict[str, str]], dict[str, str]]:
    lines = text.splitlines()
    header = {}
    start = 0
    for i, raw in enumerate(lines):
        s = raw.strip()
        if not s or s.startswith(";"):
            continue
        m = re.match(r"^\s*(\d+)\s+(\d+)(?:\s+(\S+))?\s*$", raw)
        if m:
            header = {
                "declared_rows": m.group(1),
                "code_width": m.group(2),
                "header_flags": m.group(3) or "",
            }
            start = i + 1
        break

    rows = []
    for line_no, raw in enumerate(lines[start:], start + 1):
        if not raw.strip() or raw.lstrip().startswith(";"):
            continue
        m = re.match(r"^\s*(\d+)\s+(.*?)\s+(\S+)\s*$", raw)
        ordinal = ""
        label = ""
        code = ""
        if m:
            ordinal, label, code = m.group(1), m.group(2).strip(), m.group(3).strip()
        else:
            m2 = re.match(r"^\s*(.*?)\s{2,}(\S+)\s*$", raw)
            if not m2:
                rows.append({
                    "line_number": str(line_no),
                    "ordinal": "",
                    "label": "",
                    "code_literal": "",
                    "code_start": "",
                    "code_end": "",
                    "is_range": "0",
                    "parse_status": "unparsed",
                    "raw_line": raw,
                })
                continue
            label, code = m2.group(1).strip(), m2.group(2).strip()

        code_start = code
        code_end = code
        is_range = "0"
        rm = re.match(r"^([A-Za-z0-9.]+)-([A-Za-z0-9.]+)$", code)
        if rm:
            code_start, code_end, is_range = rm.group(1), rm.group(2), "1"

        rows.append({
            "line_number": str(line_no),
            "ordinal": ordinal,
            "label": label,
            "code_literal": code,
            "code_start": code_start,
            "code_end": code_end,
            "is_range": is_range,
            "parse_status": "parsed",
            "raw_line": raw,
        })
    return rows, header

def meaningful_def_lines(text: str) -> list[tuple[int, str]]:
    out = []
    for n, raw in enumerate(text.splitlines(), 1):
        s = raw.strip()
        if not s or s.startswith(";"):
            continue
        out.append((n, raw.rstrip()))
    return out

def split_def_fields(line: str) -> list[str]:
    return [x.strip() for x in line.rstrip().rstrip(",").split(",") if x.strip()]

def parse_def(text: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    lines = meaningful_def_lines(text)
    raw_rows = [{"line_number": str(n), "raw_line": raw} for n, raw in lines]
    refs = []

    for i, (line_no, raw) in enumerate(lines):
        rm = re.search(r"([^,\\/:\s]+\.(?:CNV|DBF))\s*,?\s*$", raw, re.I)
        if not rm:
            continue
        ref_file = rm.group(1)
        kind = Path(ref_file).suffix.lower().lstrip(".")

        prev = lines[max(0, i-4):i]
        prev_lines = [x[1] for x in prev]
        source_spec = prev_lines[-1] if prev_lines else ""
        label_spec = prev_lines[-2] if len(prev_lines) >= 2 else ""
        width = ""

        if re.fullmatch(r"\s*\d+\s*,?\s*", source_spec):
            width = re.sub(r"\D", "", source_spec)
            source_spec = prev_lines[-2] if len(prev_lines) >= 2 else ""
            label_spec = prev_lines[-3] if len(prev_lines) >= 3 else ""

        source_fields = split_def_fields(source_spec)
        source_field = source_fields[0] if source_fields else ""
        label_field = source_fields[1] if kind == "dbf" and len(source_fields) > 1 else ""

        command = ""
        display_label = label_spec.rstrip().rstrip(",").strip()
        cm = re.match(r"^\s*([LCSI])(.+)$", display_label, re.I)
        if cm:
            command = cm.group(1).upper()
            display_label = cm.group(2).strip()

        refs.append({
            "line_number": str(line_no),
            "command": command,
            "display_label": display_label,
            "source_field": source_field,
            "label_field": label_field,
            "code_width": width,
            "reference_file": ref_file,
            "reference_kind": kind,
            "parse_status": "parsed" if source_field else "partial",
            "raw_block": "\n".join(prev_lines + [raw]),
        })
    return raw_rows, refs

def jsonl_to_parquet(rows: list[dict], dest: Path):
    if not rows:
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", suffix=".jsonl", delete=False) as f:
        tmp = Path(f.name)
        for row in rows:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")
    try:
        sql = (
            f"COPY (SELECT * FROM read_json_auto({sqls(str(tmp))}, "
            "format='newline_delimited', maximum_object_size=16777216)) "
            f"TO {sqls(str(dest))} (FORMAT PARQUET, COMPRESSION ZSTD);"
        )
        p = subprocess.run(["duckdb", "-c", sql], text=True, capture_output=True)
        if p.returncode:
            raise RuntimeError((p.stderr or p.stdout).strip())
    finally:
        tmp.unlink(missing_ok=True)
    return True

def source_archives(raw_root: Path, system: str, source_id: str) -> list[tuple[str, Path]]:
    root = raw_root / f"system={system}" / f"source={source_id}"
    out = []
    if not root.is_dir():
        return out
    for d in sorted(root.glob("sha256=*")):
        sha = d.name.split("=", 1)[1]
        for p in sorted(d.iterdir()):
            if p.is_file():
                out.append((sha, p))
    return out

def ci_lookup(row: dict[str, str], field: str) -> str:
    target = field.casefold()
    for k, v in row.items():
        if k.casefold() == target:
            return v
    return ""

def main() -> int:
    ap = argparse.ArgumentParser(description="Materializa Bronze/Silver de auxiliares DATASUS")
    ap.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ap.add_argument("--lake-root", default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"))
    ap.add_argument("--system", action="append")
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root).resolve()
    raw_root = lake / "raw" / "reference" / "datasus_auxiliary"
    bronze_root = lake / "bronze" / "reference" / "datasus_auxiliary"
    silver_root = lake / "silver" / "reference"
    state = lake / "state" / "reference" / "datasus_auxiliary"
    state.mkdir(parents=True, exist_ok=True)

    wanted = {x.upper() for x in (args.system or [])}

    # Bronze auxiliar e totalmente derivada dos artefatos Raw versionados.
    # Limpa antes da reconstrucao para nao manter falsos positivos/stale files.
    if not wanted:
        shutil.rmtree(bronze_root, ignore_errors=True)
    else:
        for kind in ("cnv", "def", "dbf"):
            for system in wanted:
                shutil.rmtree(
                    bronze_root / kind / f"system={system}",
                    ignore_errors=True,
                )

    rules = [
        r for r in read_tsv(args.catalog)
        if r.get("status") in {"active", "discover"}
        and (not wanted or r["system"].upper() in wanted)
    ]

    domain_rows: list[dict[str, str]] = []
    layout_rows: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    counts = Counter()

    for rule in rules:
        system = rule["system"]
        source_id = rule["source_id"]
        valid_from = rule.get("valid_from", "")
        valid_to = rule.get("valid_to", "")
        archives = source_archives(raw_root, system, source_id)

        if not archives:
            if rule["kind"] != "auxiliary_directory":
                issues.append({
                    "system": system, "source_id": source_id, "source_sha256": "",
                    "member": "", "issue_class": "raw_archive_missing",
                    "detail": rule["url"],
                })
            continue

        for source_sha, archive in archives:
            if archive.suffix.lower() != ".zip":
                issues.append({
                    "system": system, "source_id": source_id,
                    "source_sha256": source_sha, "member": archive.name,
                    "issue_class": "archive_format_not_parsed",
                    "detail": archive.suffix.lower(),
                })
                continue

            try:
                zf = zipfile.ZipFile(archive)
            except zipfile.BadZipFile:
                issues.append({
                    "system": system, "source_id": source_id,
                    "source_sha256": source_sha, "member": archive.name,
                    "issue_class": "bad_zip", "detail": str(archive),
                })
                continue

            member_data: dict[str, bytes] = {}
            def_refs: list[dict[str, str]] = []
            def_raw_all: list[dict[str, str]] = []
            cnv_bronze: list[dict[str, str]] = []

            for info in zf.infolist():
                if info.is_dir():
                    continue
                member = info.filename
                ext = Path(member).suffix.lower()
                data = zf.read(info)
                member_data[member] = data

                common = {
                    "system": system,
                    "source_id": source_id,
                    "source_sha256": source_sha,
                    "source_archive": archive.name,
                    "member": member,
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                }

                if ext == ".def":
                    text, enc = decode_text(data)
                    raw_rows, refs = parse_def(text)
                    for r in raw_rows:
                        def_raw_all.append({**common, "encoding": enc, **r})
                    for r in refs:
                        rr = {**common, "encoding": enc, **r}
                        def_refs.append(rr)
                        layout_rows.append(rr)
                    counts["def_members"] += 1

                elif ext == ".cnv":
                    if is_dbf(data):
                        counts["cnv_binary_dbf_members"] += 1
                    else:
                        text, enc = decode_text(data)
                        parsed, hdr = parse_cnv_text(text)
                        for r in parsed:
                            rr = {**common, "encoding": enc, **hdr, **r}
                            cnv_bronze.append(rr)
                            if r["parse_status"] == "parsed" and r["code_literal"]:
                                domain_rows.append({
                                    **common,
                                    "domain_id": Path(member).stem,
                                    "domain_source_kind": "cnv_text",
                                    "code_literal": r["code_literal"],
                                    "code_start": r["code_start"],
                                    "code_end": r["code_end"],
                                    "is_range": r["is_range"],
                                    "label": r["label"],
                                    "ordinal": r["ordinal"],
                                    "domain_status": "source_explicit",
                                    "source_member": member,
                                })
                        counts["cnv_text_members"] += 1

            ref_by_file: dict[str, set[tuple[str, str]]] = defaultdict(set)
            for r in def_refs:
                if r["reference_kind"] == "dbf":
                    ref_by_file[Path(r["reference_file"]).name.casefold()].add(
                        (r["source_field"], r["label_field"])
                    )

            for member, data in member_data.items():
                ext = Path(member).suffix.lower()
                if ext not in {".dbf", ".cnv"} or not is_dbf(data):
                    continue
                common = {
                    "system": system,
                    "source_id": source_id,
                    "source_sha256": source_sha,
                    "source_archive": archive.name,
                    "member": member,
                    "valid_from": valid_from,
                    "valid_to": valid_to,
                }
                try:
                    dbf_rows, dbf_fields, dbf_meta = parse_dbf(data)
                except Exception as e:
                    issues.append({
                        **common, "issue_class": "dbf_parse_error", "detail": str(e)
                    })
                    continue

                out_rows = [
                    {**common, **dbf_meta, **row}
                    for row in dbf_rows
                ]
                dbf_dest = (
                    bronze_root / "dbf" / f"system={system}" / f"source={source_id}"
                    / f"sha256={source_sha}" / f"member={slug(member)}" / "part-000.parquet"
                )
                jsonl_to_parquet(out_rows, dbf_dest)
                counts["dbf_members"] += 1
                counts["dbf_rows"] += len(dbf_rows)

                names = [f["name"] for f in dbf_fields]
                refs = ref_by_file.get(Path(member).name.casefold(), set())
                usable = []
                for k, label in refs:
                    if k and label and any(x.casefold() == k.casefold() for x in names) and any(
                        x.casefold() == label.casefold() for x in names
                    ):
                        usable.append((k, label, "def_explicit"))

                if not usable and len(names) == 2:
                    usable.append((names[0], names[1], "fallback_unique_two_fields"))

                unique_pairs = {(k.casefold(), l.casefold()) for k, l, _ in usable}
                if len(unique_pairs) == 1 and usable:
                    key_field, label_field, infer = usable[0]
                    for ordno, row in enumerate(dbf_rows, 1):
                        code = ci_lookup(row, key_field)
                        label = ci_lookup(row, label_field)
                        if code == "" and label == "":
                            continue
                        domain_rows.append({
                            **common,
                            "domain_id": Path(member).stem,
                            "domain_source_kind": "dbf_related",
                            "code_literal": code,
                            "code_start": code,
                            "code_end": code,
                            "is_range": "0",
                            "label": label,
                            "ordinal": str(ordno),
                            "domain_status": infer,
                            "source_member": member,
                        })
                else:
                    issues.append({
                        **common,
                        "issue_class": "dbf_domain_mapping_ambiguous",
                        "detail": (
                            f"fields={'|'.join(names)} refs="
                            + "|".join(f"{k}:{l}" for k, l in sorted(refs))
                        ),
                    })

            if cnv_bronze:
                dest = (
                    bronze_root / "cnv" / f"system={system}" / f"source={source_id}"
                    / f"sha256={source_sha}" / "part-000.parquet"
                )
                jsonl_to_parquet(cnv_bronze, dest)
                counts["cnv_rows"] += len(cnv_bronze)

            if def_raw_all:
                dest = (
                    bronze_root / "def" / f"system={system}" / f"source={source_id}"
                    / f"sha256={source_sha}" / "part-000.parquet"
                )
                jsonl_to_parquet(def_raw_all, dest)
                counts["def_lines"] += len(def_raw_all)

    dup = defaultdict(list)
    for i, r in enumerate(domain_rows):
        key = (
            r["system"], r["source_id"], r["source_sha256"],
            r["domain_id"].casefold(), r["code_literal"]
        )
        dup[key].append(i)
    for indexes in dup.values():
        labels = {domain_rows[i]["label"] for i in indexes}
        for j, i in enumerate(indexes, 1):
            domain_rows[i]["duplicate_count"] = str(len(indexes))
            domain_rows[i]["duplicate_ordinal"] = str(j)
            domain_rows[i]["conflicting_label"] = "1" if len(labels) > 1 else "0"

    domain_dest = silver_root / "datasus_domain" / "current.parquet"
    layout_dest = silver_root / "datasus_layout_field" / "current.parquet"
    if domain_rows:
        jsonl_to_parquet(domain_rows, domain_dest)
    if layout_rows:
        jsonl_to_parquet(layout_rows, layout_dest)

    issue_path = state / "build_issues.tsv"
    fields = ["system","source_id","source_sha256","member","issue_class","detail"]
    with issue_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        for r in issues:
            w.writerow({k: r.get(k, "") for k in fields})

    marker = state / "reference_build.ok"
    marker.write_text(
        "\n".join([
            f"domain_rows={len(domain_rows)}",
            f"layout_rows={len(layout_rows)}",
            f"issues={len(issues)}",
            f"domain={domain_dest}",
            f"layout={layout_dest}",
            f"issues_report={issue_path}",
            "status=complete",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        f"DATASUS_REFERENCE_BUILD_OK domain_rows={len(domain_rows)} "
        f"layout_rows={len(layout_rows)} issues={len(issues)}"
    )
    for k, v in sorted(counts.items()):
        print(f"{k}={v}")
    print(f"domain={domain_dest}")
    print(f"layout={layout_dest}")
    print(f"issues={issue_path}")
    return 0

if __name__ == "__main__":
    import shutil
    raise SystemExit(main())
