#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import subprocess
from collections import Counter, defaultdict
from pathlib import Path

SERVICES = ("bureta", "pipeta")

def run_psql(service: str, sql: str) -> str:
    p = subprocess.run(
        ["psql", f"service={service}", "-X", "-At", "-F", "\t", "-P", "pager=off", "-c", sql],
        text=True, capture_output=True,
    )
    if p.returncode:
        raise SystemExit(f"psql service={service} falhou: {p.stderr.strip()}")
    return p.stdout

def qlit(s: str) -> str:
    return "'" + s.replace("'", "''") + "'"

def latest_list(service: str) -> str:
    sql = r"""
SELECT table_schema || '.' || table_name
FROM information_schema.tables
WHERE table_schema='public'
  AND table_name ~ '^lista_dissemin_dbc_[0-9]{8}$'
ORDER BY table_name DESC
LIMIT 1;
"""
    return run_psql(service, sql).strip()

def load_source(service: str, table: str) -> list[dict[str, str]]:
    # Split canonico historico do projeto: bureta < 2020; pipeta >= 2020.
    cutoff = "< 202000" if service == "bureta" else ">= 202000"
    sql = f"""
SELECT
  lower(coalesce(no_dbc_origem,'')),
  upper(coalesce(sg_sistema,'')),
  upper(coalesce(sg_versao,'')),
  upper(coalesce(sg_subsistema,'')),
  upper(coalesce(sg_uf,'')),
  coalesce(nu_competencia,0)::text,
  coalesce(st_existe_sql,0)::text,
  coalesce(no_schema,''),
  coalesce(no_tabela,'')
FROM {table}
WHERE coalesce(no_dbc_origem,'') <> ''
  AND coalesce(nu_competencia,0) {cutoff}
ORDER BY 2,3,5,4,1;
"""
    out = []
    for line in run_psql(service, sql).splitlines():
        p = line.split("\t")
        if len(p) != 9:
            continue
        out.append(dict(
            service=service, dbc=p[0], system=p[1], version=p[2],
            subsystem=p[3], uf=p[4], competencia=p[5], sql_present=p[6],
            schema=p[7], table=p[8],
        ))
    return out

def repository_id(r: dict[str, str]) -> str:
    """Repositorio logico = pasta/serie da fonte FTP, nunca apenas o sistema."""
    system = (r.get("system") or "").strip().lower()
    version = (r.get("version") or "").strip().lower()
    if version:
        return f"{system}__{version}"
    schema = (r.get("schema") or "").strip().lower()
    prefix = system + "_"
    if schema.startswith(prefix):
        rest = schema[len(prefix):]
        parts = rest.split("_")
        if len(parts) >= 2 and parts[0].isdigit():
            if len(parts) >= 3 and parts[1].isdigit():
                return f"{system}__{parts[0]}_{parts[1]}"
            return f"{system}__{parts[0]}_"
    return system or "unknown"

def read_tsv(path: Path) -> list[dict[str, str]]:
    try:
        with path.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f, delimiter="\t"))
    except Exception:
        return []

def parquet_tracked_from_state(lake: Path) -> set[str]:
    tracked: set[str] = set()
    state = lake / "state"
    if not state.is_dir():
        return tracked
    for p in state.rglob("*.tsv"):
        for r in read_tsv(p):
            for k in ("dbc", "no_dbc_origem", "source_dbc"):
                v = (r.get(k) or "").strip().lower()
                if v:
                    tracked.add(v)
    return tracked

def recorded_counts(r: dict[str, str]) -> tuple[str, str]:
    """Compatibilidade com runs novos (rows_*) e overnight legado (source/parquet_rows)."""
    pg = r.get("rows_pg") or r.get("source_rows") or ""
    pq = r.get("rows_parquet") or r.get("parquet_rows") or ""
    return pg, pq

def overnight_sih(lake: Path) -> dict:
    state = lake / "state" / "overnight"
    latest = state / "LATEST"
    if not latest.is_file():
        return {"available": False}
    run = Path(latest.read_text(encoding="utf-8").strip())
    if not run.is_dir():
        return {"available": False, "run": str(run)}
    manifest = read_tsv(run / "sih_manifest.tsv")
    results = read_tsv(run / "sih_parquet_results.tsv")
    done = False
    mainlog = run / "main.log"
    if mainlog.is_file():
        done = "OVERNIGHT_DONE" in mainlog.read_text(encoding="utf-8", errors="replace").splitlines()
    ok = 0
    problems = []
    for r in results:
        pg_recorded, pq_recorded = recorded_counts(r)
        valid = (
            r.get("status") in {"OK", "SKIP_OK"}
            and bool(pg_recorded)
            and bool(pq_recorded)
            and pg_recorded == pq_recorded
        )
        if valid:
            ok += 1
        else:
            problems.append({
                "service": r.get("service", ""),
                "subsystem": r.get("subsystem", ""),
                "uf": r.get("uf", ""),
                "competencia": r.get("competencia", ""),
                "dbc": r.get("dbc", ""),
                "schema": r.get("schema", ""),
                "table": r.get("table", ""),
                "status": r.get("status", ""),
                "rows_pg": pg_recorded,
                "rows_parquet": pq_recorded,
                "path": r.get("path", ""),
            })
    return {
        "available": True,
        "run": str(run),
        "overnight_done": done,
        "manifest_files": len(manifest),
        "results_files": len(results),
        "qc_ok_files": ok,
        "pending_or_failed": max(len(manifest) - ok, 0),
        "problems": problems,
    }

def main() -> int:
    ap = argparse.ArgumentParser(description="Status objetivo da migracao BDSUS PostgreSQL -> SUSLabX Parquet")
    ap.add_argument("--lake-root", default="/dados/abertos/suslabx")
    ap.add_argument("--system", action="append", help="Filtra sistema; pode repetir (ex.: --system SIH)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument(
        "--details",
        action="store_true",
        help="Lista SQL ausente e problemas do overnight, alem do resumo",
    )
    args = ap.parse_args()

    lake = Path(args.lake_root)
    systems = {x.upper() for x in (args.system or [])}

    rows: list[dict[str, str]] = []
    lists = {}
    for svc in SERVICES:
        tb = latest_list(svc)
        if not tb:
            raise SystemExit(f"Nenhuma lista_dissemin_dbc encontrada em {svc}")
        lists[svc] = tb
        rows.extend(load_source(svc, tb))

    # Dedup defensivo do inventario canonico.
    dedup = {}
    duplicates = 0
    for r in rows:
        r["repository"] = repository_id(r)
        key = (
            r["dbc"], r["system"], r["repository"], r["subsystem"],
            r["uf"], r["competencia"]
        )
        if key in dedup:
            duplicates += 1
            # Preferir a linha que confirma SQL existente.
            if dedup[key]["sql_present"] != "1" and r["sql_present"] == "1":
                dedup[key] = r
        else:
            dedup[key] = r
    rows = list(dedup.values())

    if systems:
        rows = [r for r in rows if r["system"] in systems]

    tracked = parquet_tracked_from_state(lake)
    summary = defaultdict(lambda: Counter())
    for r in rows:
        s = summary[(r["system"], r["repository"])]
        s["dbc_expected"] += 1
        if r["sql_present"] == "1":
            s["sql_present"] += 1
        else:
            s["sql_missing"] += 1
        if r["dbc"] in tracked:
            s["parquet_tracked"] += 1
        else:
            s["parquet_untracked"] += 1

    total = Counter()
    for s in summary.values():
        total.update(s)

    missing_sql = [
        r for r in rows
        if r["sql_present"] != "1"
    ]
    untracked = [
        r for r in rows
        if r["dbc"] not in tracked
    ]

    result = {
        "lake_root": str(lake),
        "source_lists": lists,
        "canonical_duplicates_removed": duplicates,
        "totals": dict(total),
        "by_repository": {
            f"{system}|{repository}": dict(v)
            for (system, repository), v in sorted(summary.items())
        },
        "sih_overnight": overnight_sih(lake),
        "sql_missing_rows": missing_sql if args.details else [],
        "parquet_untracked_rows": untracked if args.details else [],
        "note": (
            "parquet_tracked usa manifestos TSV em state; nao equivale a varredura fisica "
            "de todo o lake. O overnight SIH legado cobriu 200801..202610 com SQL presente; "
            "DBC historico fora dessa janela pode aparecer como parquet_untracked sem ser falha."
        ),
    }

    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    print(f"SUSLABX_STATUS lake={lake}")
    print("listas:", " | ".join(f"{k}={v}" for k,v in lists.items()))
    print(f"duplicatas_canonicas_removidas={duplicates}")
    print("system\trepository\tdbc_expected\tsql_present\tsql_missing\tparquet_tracked\tparquet_untracked")
    for (system, repository), s in sorted(summary.items()):
        print("\t".join(str(x) for x in (
            system, repository, s["dbc_expected"], s["sql_present"], s["sql_missing"],
            s["parquet_tracked"], s["parquet_untracked"],
        )))
    print("TOTAL\t" + "\t".join(str(total[x]) for x in (
        "dbc_expected","sql_present","sql_missing","parquet_tracked","parquet_untracked"
    )))
    sih = result["sih_overnight"]
    if sih.get("available"):
        print(
            "SIH_OVERNIGHT "
            f"done={int(bool(sih['overnight_done']))} "
            f"manifest={sih['manifest_files']} results={sih['results_files']} "
            f"ok={sih['qc_ok_files']} pending={sih['pending_or_failed']} "
            f"run={sih['run']}"
        )
    else:
        print("SIH_OVERNIGHT indisponivel")

    if args.details:
        print()
        print("SQL_MISSING")
        if missing_sql:
            for r in sorted(
                missing_sql,
                key=lambda x: (
                    x["system"], x["subsystem"], x["competencia"], x["uf"], x["dbc"]
                ),
            ):
                print(
                    "\t".join([
                        str(r.get("service") or ""), str(r.get("system") or ""),
                        str(r.get("repository") or ""), str(r.get("subsystem") or ""),
                        str(r.get("uf") or ""), str(r.get("competencia") or ""),
                        str(r.get("dbc") or ""), str(r.get("schema") or ""),
                        str(r.get("table") or ""),
                    ])
                )
        else:
            print("nenhum")

        print()
        print("SIH_OVERNIGHT_PROBLEMS")
        problems = sih.get("problems", []) if sih.get("available") else []
        if problems:
            for r in problems:
                print(
                    "\t".join([
                        str(r.get("service") or ""), str(r.get("subsystem") or ""),
                        str(r.get("uf") or ""), str(r.get("competencia") or ""),
                        str(r.get("dbc") or ""), str(r.get("schema") or ""),
                        str(r.get("table") or ""), str(r.get("status") or ""),
                        str(r.get("rows_pg") or ""), str(r.get("rows_parquet") or ""),
                        str(r.get("path") or ""),
                    ])
                )
        else:
            print("nenhum")

        # Resumo por repositorio/serie FTP. Eras distintas nunca sao somadas como
        # cobertura de um unico repositorio.
        outside = Counter()
        for r in untracked:
            state = "sql_ausente" if r["sql_present"] != "1" else "sql_presente_nao_rastreado"
            outside[(r["system"], r["repository"], r["subsystem"], state)] += 1
        print()
        print("PARQUET_UNTRACKED_RESUMO")
        if outside:
            for (system, repository, subsystem, state), n in sorted(outside.items()):
                print(f"{system}\t{repository}\t{subsystem}\t{state}\t{n}")
        else:
            print("nenhum")

    return 0

if __name__ == "__main__":
    raise SystemExit(main())
