#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import datetime as dt
import subprocess
from collections import defaultdict
from pathlib import Path

def die(msg: str, code: int = 2) -> None:
    print(f"ERRO: {msg}")
    raise SystemExit(code)

def qident(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'

def qlit(v: str) -> str:
    return "'" + v.replace("'", "''") + "'"

def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))

def psql_count(service: str, schema: str, table: str) -> int:
    sql = f"SELECT count(*) FROM {qident(schema)}.{qident(table)};"
    p = subprocess.run(
        ["psql", f"service={service}", "-X", "-At", "-P", "pager=off", "-c", sql],
        text=True, capture_output=True,
    )
    if p.returncode:
        die(f"psql {service} {schema}.{table}: {p.stderr.strip()}", 30)
    return int(p.stdout.strip())

def parquet_count(path: Path) -> int:
    sql = f"SELECT count(*) FROM read_parquet({qlit(str(path))});"
    p = subprocess.run(
        ["duckdb", "-csv", "-noheader", "-c", sql],
        text=True, capture_output=True,
    )
    if p.returncode:
        die(f"duckdb {path}: {p.stderr.strip()}", 31)
    return int(p.stdout.strip())

def choose_sample(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    groups: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        groups[(r["service"], r["subsystem"])].append(r)
    out = []
    seen = set()
    for key, vals in sorted(groups.items()):
        vals = sorted(vals, key=lambda x: (x["competencia"], x["uf"], x["dbc"]))
        picks = [vals[0], vals[len(vals)//2], vals[-1]]
        for r in picks:
            ident = (r["service"], r["schema"], r["table"], r["dbc"])
            if ident not in seen:
                seen.add(ident)
                out.append(r)
    return out

def main() -> int:
    ap = argparse.ArgumentParser(
        description="CQ live BDSUS PostgreSQL versus staging Parquet SIH"
    )
    ap.add_argument("--lake-root", default="/dados/abertos/suslabx")
    ap.add_argument("--run")
    args = ap.parse_args()

    lake = Path(args.lake_root).resolve()
    state = lake / "state" / "overnight"
    if args.run:
        run = Path(args.run).resolve()
    else:
        latest = state / "LATEST"
        if not latest.is_file():
            die(f"LATEST ausente: {latest}", 20)
        run = Path(latest.read_text(encoding="utf-8").strip()).resolve()

    results = run / "sih_parquet_results.tsv"
    mainlog = run / "main.log"
    if not results.is_file() or not mainlog.is_file():
        die(f"run incompleto: {run}", 21)
    if "OVERNIGHT_DONE" not in mainlog.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        die("overnight ainda nao terminou", 22)

    rows = read_tsv(results)
    if not rows:
        die("results vazio", 23)

    bad_results = []
    bad_split = []
    duplicate_dbc = []
    dbc_seen = set()

    for r in rows:
        if (
            r.get("status") not in {"OK", "SKIP_OK"}
            or r.get("rows_pg") != r.get("rows_parquet")
        ):
            bad_results.append(r)
        comp = int(r["competencia"])
        expected_service = "bureta" if comp < 202000 else "pipeta"
        if r["service"] != expected_service:
            bad_split.append(r)
        if r["dbc"] in dbc_seen:
            duplicate_dbc.append(r["dbc"])
        dbc_seen.add(r["dbc"])

    if bad_results:
        die(f"results com divergencia PG/Parquet: {len(bad_results)}", 24)
    if bad_split:
        die(f"split canonico bureta/pipeta violado: {len(bad_split)}", 25)
    if duplicate_dbc:
        die(f"DBC duplicado no snapshot: {len(set(duplicate_dbc))}", 26)

    sample = choose_sample(rows)
    report_rows = []
    bad_live = 0

    for r in sample:
        path = Path(r["path"])
        if not path.is_file():
            die(f"Parquet ausente: {path}", 27)
        pg_now = psql_count(r["service"], r["schema"], r["table"])
        pq_now = parquet_count(path)
        expected = int(r["rows_parquet"])
        ok = int(pg_now == pq_now == expected)
        bad_live += 0 if ok else 1
        report_rows.append({
            "service": r["service"],
            "subsystem": r["subsystem"],
            "uf": r["uf"],
            "competencia": r["competencia"],
            "dbc": r["dbc"],
            "schema": r["schema"],
            "table": r["table"],
            "rows_recorded": str(expected),
            "rows_pg_live": str(pg_now),
            "rows_parquet_live": str(pq_now),
            "ok": str(ok),
        })
        print(
            f"LIVE {r['service']} {r['subsystem']} {r['uf']} "
            f"{r['competencia']} {r['dbc']} pg={pg_now} pq={pq_now} ok={ok}"
        )

    outdir = lake / "state" / "sih"
    outdir.mkdir(parents=True, exist_ok=True)
    ts = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    report = outdir / f"qc_source_staging_live_{ts}.tsv"
    fields = list(report_rows[0].keys())
    with report.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields, delimiter="\t", lineterminator="\n")
        w.writeheader()
        w.writerows(report_rows)

    if bad_live:
        die(f"amostra live divergente: {bad_live}; report={report}", 40)

    marker = outdir / "qc_source_staging_live_current.ok"
    marker.write_text(
        "\n".join([
            f"timestamp={ts}",
            f"run={run}",
            f"files_full_gate={len(rows)}",
            f"live_sample={len(sample)}",
            f"report={report}",
            "canonical_split=validated",
            "recorded_pg_vs_parquet=validated",
            "live_pg_vs_parquet_sample=validated",
            "status=validated",
            "",
        ]),
        encoding="utf-8",
    )
    print(
        f"SIH_SOURCE_STAGING_LIVE_QC_OK files={len(rows)} "
        f"sample={len(sample)} report={report}"
    )
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
