#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FIXED = ROOT / "systems" / "sih" / "fixed_width_fields.tsv"

RESULT_FIELDS = [
    "service", "subsystem", "uf", "competencia", "dbc",
    "schema", "table", "status", "rows_pg", "rows_parquet",
    "bytes_parquet", "path",
]


def die(msg: str, code: int = 2) -> None:
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)


def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"


def qi(v: str) -> str:
    return '"' + str(v).replace('"', '""') + '"'


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f, delimiter="\t"))


def scalar(sql: str) -> str:
    p = subprocess.run(
        ["duckdb", "-csv", "-noheader", "-c", sql],
        text=True, capture_output=True,
    )
    if p.returncode:
        raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return p.stdout.strip()


def columns(path: Path) -> list[str]:
    out = scalar(f"DESCRIBE SELECT * FROM read_parquet({qs(str(path))});")
    return [r[0] for r in csv.reader(out.splitlines()) if r]


def count(path: Path) -> int:
    return int(scalar(f"SELECT count(*) FROM read_parquet({qs(str(path))});") or 0)


def load_fixed_width() -> dict[str, dict[str, int]]:
    out: dict[str, dict[str, int]] = {}
    for r in read_tsv(FIXED):
        if r.get("status") != "validated":
            continue
        out.setdefault(r["subsystem"].upper(), {})[r["field"].upper()] = int(
            r["logical_width"]
        )
    return out


def normalized_expr(col: str, width: int) -> str:
    q = qi(col)
    raw = f"trim(cast({q} as varchar))"
    return (
        "CASE "
        f"WHEN {q} IS NULL THEN NULL "
        f"WHEN {raw}='' THEN '' "
        f"WHEN regexp_full_match({raw}, '^[0-9]+$') "
        f"THEN lpad({raw}, {width}, '0') "
        f"ELSE {raw} END AS {q}"
    )


def validate_run(run: Path) -> tuple[Path, Path, list[dict[str, str]]]:
    manifest = run / "sih_manifest.tsv"
    results = run / "sih_parquet_results.tsv"
    mainlog = run / "main.log"

    for p in (manifest, results, mainlog):
        if not p.is_file():
            die(f"arquivo de gate ausente: {p}", 20)

    if "OVERNIGHT_DONE" not in mainlog.read_text(
        encoding="utf-8", errors="replace"
    ).splitlines():
        die("overnight ainda nao concluiu: OVERNIGHT_DONE ausente", 21)

    m = read_tsv(manifest)
    r = read_tsv(results)

    if len(m) != len(r):
        die(f"manifest/results divergem: manifest={len(m)} results={len(r)}", 22)

    bad = [
        x for x in r
        if x.get("status") not in {"OK", "SKIP_OK"}
        or x.get("rows_pg") != x.get("rows_parquet")
    ]
    if bad:
        die(f"resultados nao homologados: {len(bad)}", 23)

    partial = list((run.parent.parent.parent / "staging" / "psql_snapshot" / "sih").rglob("*.partial*"))
    if partial:
        die(f"arquivos partial encontrados: {len(partial)}", 24)

    return manifest, results, r


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Promove snapshot PostgreSQL SIH homologado de staging para Bronze"
    )
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslake"),
    )
    ap.add_argument(
        "--run",
        help="diretorio da execucao overnight; por padrao usa state/overnight/LATEST",
    )
    ap.add_argument("--execute", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)
    if not FIXED.is_file():
        die(f"contrato de largura fixa ausente: {FIXED}", 4)

    lake = Path(args.lake_root).resolve()
    state = lake / "state" / "overnight"
    if args.run:
        run = Path(args.run).resolve()
    else:
        latest = state / "LATEST"
        if not latest.is_file():
            die(f"LATEST ausente: {latest}", 5)
        run = Path(latest.read_text(encoding="utf-8").strip()).resolve()

    _, results_path, rows = validate_run(run)
    fixed = load_fixed_width()

    plan = []
    for r in rows:
        src = Path(r["path"]).resolve()
        if not src.is_file():
            die(f"staging ausente: {src}", 30)

        sub = r["subsystem"].upper()
        uf = r["uf"].upper()
        comp = r["competencia"]
        service = r["service"].lower()
        schema = r["schema"]
        table = r["table"]
        dbc = r["dbc"]

        if not re.fullmatch(r"[A-Z0-9_]+", sub):
            die(f"subsystem invalido: {sub}", 31)
        if not re.fullmatch(r"[A-Z]{2}", uf):
            die(f"UF invalida: {uf}", 31)
        if not re.fullmatch(r"\d{6}", comp):
            die(f"competencia invalida: {comp}", 31)

        dest = (
            lake / "bronze" / "sih" / sub.lower()
            / f"uf={uf}" / f"competencia={comp}"
            / f"source_service={service}"
            / f"source_schema={schema}"
            / f"source_table={table}"
            / f"{dbc}.parquet"
        )

        plan.append((r, src, dest))

    print(
        f"SIH_STAGING_BRONZE_PLAN run={run} files={len(plan)} "
        f"execute={int(args.execute)}"
    )

    if not args.execute:
        for r, src, dest in plan[:20]:
            print(
                f"PLAN {r['service']} {r['subsystem']} {r['uf']} "
                f"{r['competencia']} {r['dbc']} -> {dest}"
            )
        if len(plan) > 20:
            print(f"PLAN ... {len(plan)-20} arquivos adicionais")
        print("DRY_RUN: nenhum arquivo alterado")
        return 0

    report_rows = []

    for i, (r, src, dest) in enumerate(plan, 1):
        dest.parent.mkdir(parents=True, exist_ok=True)

        src_rows = count(src)
        expected = int(r["rows_parquet"])
        if src_rows != expected:
            die(
                f"staging mudou apos CQ: {src} result={expected} atual={src_rows}",
                40,
            )

        if dest.is_file() and not args.force:
            dst_rows = count(dest)
            if dst_rows != src_rows:
                die(
                    f"Bronze existente diverge: {dest} staging={src_rows} "
                    f"bronze={dst_rows}",
                    41,
                )
            print(f"[{i}/{len(plan)}] SKIP_QC_OK {dest} rows={dst_rows}")
            report_rows.append({
                **r,
                "bronze_path": str(dest),
                "rows_bronze": str(dst_rows),
                "normalized_fields": "",
                "promotion_status": "SKIP_QC_OK",
            })
            continue

        cols = columns(src)
        by_upper = {c.upper(): c for c in cols}
        widths = fixed.get(r["subsystem"].upper(), {})

        reserved = {"ID_REGISTRO_FONTE", "NU_LINHA_FONTE"}
        collision = reserved & set(by_upper)
        if collision:
            die(
                f"{src}: campos tecnicos reservados ja existem: "
                + ",".join(sorted(collision)),
                42,
            )

        projection = []
        normalized = []

        for c in cols:
            w = widths.get(c.upper())
            if w:
                projection.append(normalized_expr(c, w))
                normalized.append(c)
            else:
                projection.append(qi(c))

        seed = f"{r['service']}|{r['schema']}|{r['table']}|{r['dbc']}|"
        projection.extend([
            "__suslake_rn::BIGINT AS nu_linha_fonte",
            (
                f"md5({qs(seed)} || cast(__suslake_rn as varchar)) "
                "AS id_registro_fonte"
            ),
        ])

        # Detecta valores incompatíveis nos campos declarados; não mascara
        # caracteres nao numericos e nao permite truncamento.
        for upper, w in widths.items():
            actual = by_upper.get(upper)
            if not actual:
                continue
            q = qi(actual)
            raw = f"trim(cast({q} as varchar))"
            bad = int(scalar(
                f"SELECT count(*) FROM read_parquet({qs(str(src))}) "
                f"WHERE {q} IS NOT NULL AND {raw}<>'' "
                f"AND NOT regexp_full_match({raw}, '^[0-9]+$');"
            ) or 0)
            if bad:
                die(
                    f"{src}: campo {actual} possui {bad} valores nao numericos; "
                    "normalizacao bloqueada",
                    43,
                )
            too_long = int(scalar(
                f"SELECT count(*) FROM read_parquet({qs(str(src))}) "
                f"WHERE {q} IS NOT NULL AND {raw}<>'' "
                f"AND regexp_full_match({raw}, '^[0-9]+        partial.unlink(missing_ok=True)

        sql = (
            "COPY (SELECT "
            + ", ".join(projection)
            + " FROM (SELECT *, row_number() OVER () AS __suslake_rn "
            + f"FROM read_parquet({qs(str(src))})) s) "
            + f"TO {qs(str(partial))} "
            + "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880);"
        )
        p = subprocess.run(["duckdb", "-c", sql], text=True, capture_output=True)
        if p.returncode:
            partial.unlink(missing_ok=True)
            raise RuntimeError(p.stderr.strip() or p.stdout.strip())

        dst_rows = count(partial)
        if dst_rows != src_rows:
            partial.unlink(missing_ok=True)
            die(
                f"promocao alterou grão: {src} staging={src_rows} "
                f"bronze={dst_rows}",
                45,
            )

        os.replace(partial, dest)
        print(
            f"[{i}/{len(plan)}] SIH_BRONZE_OK {r['subsystem']} {r['uf']} "
            f"{r['competencia']} {r['dbc']} rows={dst_rows} "
            f"normalized={','.join(normalized) or '-'}"
        )

        report_rows.append({
            **r,
            "bronze_path": str(dest),
            "rows_bronze": str(dst_rows),
            "normalized_fields": ",".join(normalized),
            "promotion_status": "OK",
        })

    outdir = lake / "state" / "sih"
    outdir.mkdir(parents=True, exist_ok=True)
    report = outdir / f"bronze_from_staging_{run.name}.tsv"
    fields = RESULT_FIELDS + [
        "bronze_path", "rows_bronze", "normalized_fields", "promotion_status"
    ]
    with report.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(report_rows)

    marker = outdir / f"bronze_from_staging_{run.name}.ok"
    marker.write_text(
        "\n".join([
            f"run={run}",
            f"source_results={results_path}",
            f"files={len(report_rows)}",
            f"report={report}",
            "row_count_gate=validated",
            "fixed_width_contract=systems/sih/fixed_width_fields.tsv",
            "status=complete",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        f"SIH_STAGING_BRONZE_OK files={len(report_rows)} "
        f"report={report} marker={marker}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
) "
                f"AND length({raw}) > {w};"
            ) or 0)
            if too_long:
                die(
                    f"{src}: campo {actual} possui {too_long} valores com "
                    f"mais de {w} digitos; truncamento bloqueado",
                    44,
                )

        partial = dest.with_name(dest.name + f".partial.{os.getpid()}")
        partial.unlink(missing_ok=True)

        sql = (
            "COPY (SELECT "
            + ", ".join(projection)
            + f" FROM read_parquet({qs(str(src))})) "
            + f"TO {qs(str(partial))} "
            + "(FORMAT PARQUET, COMPRESSION ZSTD, ROW_GROUP_SIZE 122880);"
        )
        p = subprocess.run(["duckdb", "-c", sql], text=True, capture_output=True)
        if p.returncode:
            partial.unlink(missing_ok=True)
            raise RuntimeError(p.stderr.strip() or p.stdout.strip())

        dst_rows = count(partial)
        if dst_rows != src_rows:
            partial.unlink(missing_ok=True)
            die(
                f"promocao alterou grão: {src} staging={src_rows} "
                f"bronze={dst_rows}",
                43,
            )

        os.replace(partial, dest)
        print(
            f"[{i}/{len(plan)}] SIH_BRONZE_OK {r['subsystem']} {r['uf']} "
            f"{r['competencia']} {r['dbc']} rows={dst_rows} "
            f"normalized={','.join(normalized) or '-'}"
        )

        report_rows.append({
            **r,
            "bronze_path": str(dest),
            "rows_bronze": str(dst_rows),
            "normalized_fields": ",".join(normalized),
            "promotion_status": "OK",
        })

    outdir = lake / "state" / "sih"
    outdir.mkdir(parents=True, exist_ok=True)
    report = outdir / f"bronze_from_staging_{run.name}.tsv"
    fields = RESULT_FIELDS + [
        "bronze_path", "rows_bronze", "normalized_fields", "promotion_status"
    ]
    with report.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f, fieldnames=fields, delimiter="\t", lineterminator="\n"
        )
        w.writeheader()
        w.writerows(report_rows)

    marker = outdir / f"bronze_from_staging_{run.name}.ok"
    marker.write_text(
        "\n".join([
            f"run={run}",
            f"source_results={results_path}",
            f"files={len(report_rows)}",
            f"report={report}",
            "row_count_gate=validated",
            "fixed_width_contract=systems/sih/fixed_width_fields.tsv",
            "status=complete",
            "",
        ]),
        encoding="utf-8",
    )

    print(
        f"SIH_STAGING_BRONZE_OK files={len(report_rows)} "
        f"report={report} marker={marker}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
