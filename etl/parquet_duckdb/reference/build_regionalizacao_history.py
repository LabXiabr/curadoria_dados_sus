#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def duck(sql: str, capture: bool = False) -> str:
    p = subprocess.run(
        ["duckdb", "-csv", "-noheader", "-c", sql],
        text=True, capture_output=True
    )
    if p.returncode:
        if p.stdout:
            print(p.stdout, file=sys.stderr)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def build_one(
    lake: Path,
    rel_table: str,
    code_col: str,
    slug: str,
    work: Path,
    allowed_sql: str,
) -> tuple[Path, Path]:
    pattern = (
        lake / "bronze" / "reference" / "territorio" /
        rel_table / "snapshot=*" / "part-000.parquet"
    )
    matches = sorted(
        (lake / "bronze" / "reference" / "territorio" / rel_table)
        .glob("snapshot=*/part-000.parquet")
    )
    if not matches:
        raise RuntimeError(f"sem snapshots para {rel_table}")

    hist = work / f"municipio_{slug}.parquet"
    events = work / f"eventos_municipio_{slug}.parquet"

    base = f"""
WITH obs AS (
 SELECT DISTINCT
   trim(cast(CO_MUNICIP as varchar)) AS co_municipio,
   trim(cast({code_col} as varchar)) AS codigo,
   cast("snapshot" as varchar) AS snapshot_key
 FROM read_parquet(
   {sqls(str(pattern))},
   hive_partitioning=true,
   union_by_name=true
 )
 WHERE CO_MUNICIP IS NOT NULL
   AND {code_col} IS NOT NULL
   AND cast("snapshot" as varchar) IN ({allowed_sql})
),
ordered AS (
 SELECT *,
        lag(codigo) OVER (
          PARTITION BY co_municipio ORDER BY snapshot_key
        ) AS prev_codigo,
        lag(snapshot_key) OVER (
          PARTITION BY co_municipio ORDER BY snapshot_key
        ) AS prev_snapshot
 FROM obs
),
flagged AS (
 SELECT *,
        CASE
          WHEN prev_codigo IS NULL OR codigo <> prev_codigo THEN 1
          ELSE 0
        END AS new_group
 FROM ordered
),
grp AS (
 SELECT *,
        sum(new_group) OVER (
          PARTITION BY co_municipio
          ORDER BY snapshot_key
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW
        ) AS grp
 FROM flagged
)
"""

    hsql = base + f"""
SELECT
 co_municipio,
 codigo AS co_{slug},
 min(snapshot_key) AS observed_from_snapshot,
 max(snapshot_key) AS observed_to_snapshot,
 count(*) AS observed_snapshots,
 (
   max(snapshot_key) = (SELECT max(snapshot_key) FROM obs)
 ) AS is_current_observation
FROM grp
GROUP BY co_municipio, codigo, grp
ORDER BY co_municipio, observed_from_snapshot
"""
    duck(
        f"COPY ({hsql}) TO {sqls(str(hist))} "
        "(FORMAT PARQUET, COMPRESSION ZSTD);"
    )

    esql = base + f"""
SELECT
 co_municipio,
 prev_codigo AS co_{slug}_anterior,
 codigo AS co_{slug}_novo,
 prev_snapshot AS ultima_observacao_anterior,
 snapshot_key AS primeira_observacao_nova,
 'snapshot_change'::VARCHAR AS tp_evento
FROM ordered
WHERE prev_codigo IS NOT NULL
  AND codigo <> prev_codigo
ORDER BY snapshot_key, co_municipio
"""
    duck(
        f"COPY ({esql}) TO {sqls(str(events))} "
        "(FORMAT PARQUET, COMPRESSION ZSTD);"
    )
    return hist, events

def main() -> int:
    ap = argparse.ArgumentParser(
        description=(
            "Constrói memória temporal observada de CIR/macrorregião "
            "a partir de snapshots DATASUS homologados"
        )
    )
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslabx"),
    )
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root)
    state = lake / "state" / "reference"
    state.mkdir(parents=True, exist_ok=True)

    gate = state / "territorio_backfill_complete.ok"
    if not gate.is_file():
        die(
            f"backfill territorial ainda nao homologado: {gate}. "
            "Conclua ops/territorio-backfill.sh antes de gerar a memoria temporal.",
            20,
        )

    snapshot_markers = sorted(state.glob("territorio_*.bronze.ok"))
    allowed = []
    for marker in snapshot_markers:
        for line in marker.read_text(encoding="utf-8").splitlines():
            if line.startswith("snapshot="):
                allowed.append(line.split("=", 1)[1].strip())
                break
    allowed = sorted({x for x in allowed if x})
    if not allowed:
        die("nenhum snapshot territorial Bronze homologado", 20)
    allowed_sql = ",".join(sqls(x) for x in allowed)

    workroot = lake / "work" / "regionalizacao_history"
    workroot.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix="build_", dir=workroot))

    try:
        specs = [
            ("rl_municip_regsaud", "CO_REGSAUD", "regiao_saude"),
            ("rl_municip_macsaud", "CO_MACSAUD", "macrorregiao_saude"),
        ]
        staged = []
        for rel, col, slug in specs:
            hist, events = build_one(lake, rel, col, slug, work, allowed_sql)
            staged.append((slug, hist, events))

        reg_pattern = (
            lake / "bronze" / "reference" / "territorio" /
            "rl_municip_regsaud" / "snapshot=*" / "part-000.parquet"
        )
        mac_pattern = (
            lake / "bronze" / "reference" / "territorio" /
            "rl_municip_macsaud" / "snapshot=*" / "part-000.parquet"
        )
        summary = work / "snapshot_resumo.parquet"

        duck(f"""
COPY (
 WITH r AS (
   SELECT
     cast("snapshot" as varchar) AS snapshot_key,
     count(DISTINCT trim(cast(CO_MUNICIP as varchar))) AS municipios_regiao,
     count(DISTINCT trim(cast(CO_REGSAUD as varchar))) AS regioes_saude
   FROM read_parquet(
     {sqls(str(reg_pattern))},
     hive_partitioning=true,
     union_by_name=true
   )
   WHERE cast("snapshot" as varchar) IN ({allowed_sql})
   GROUP BY 1
 ),
 m AS (
   SELECT
     cast("snapshot" as varchar) AS snapshot_key,
     count(DISTINCT trim(cast(CO_MUNICIP as varchar))) AS municipios_macro,
     count(DISTINCT trim(cast(CO_MACSAUD as varchar))) AS macrorregioes_saude
   FROM read_parquet(
     {sqls(str(mac_pattern))},
     hive_partitioning=true,
     union_by_name=true
   )
   WHERE cast("snapshot" as varchar) IN ({allowed_sql})
   GROUP BY 1
 )
 SELECT
   coalesce(r.snapshot_key, m.snapshot_key) AS snapshot_key,
   r.municipios_regiao,
   r.regioes_saude,
   m.municipios_macro,
   m.macrorregioes_saude
 FROM r
 FULL OUTER JOIN m USING(snapshot_key)
 ORDER BY snapshot_key
)
TO {sqls(str(summary))}
(FORMAT PARQUET, COMPRESSION ZSTD);
""")

        stats = duck(
            f"SELECT count(*), min(snapshot_key), max(snapshot_key) "
            f"FROM read_parquet({sqls(str(summary))});",
            True,
        ).strip()
        n, first, last = next(csv.reader([stats]))
        if int(n) < 1:
            raise RuntimeError("resumo temporal vazio")

        out_hist = lake / "silver" / "reference" / "regionalizacao_historico"
        out_evt = lake / "silver" / "reference" / "regionalizacao_eventos"
        out_hist.mkdir(parents=True, exist_ok=True)
        out_evt.mkdir(parents=True, exist_ok=True)

        for slug, hist, events in staged:
            final_hist = out_hist / f"municipio_{slug}.parquet"
            final_evt = out_evt / f"municipio_{slug}.parquet"
            os.replace(hist, final_hist)
            os.replace(events, final_evt)
            print(
                f"OK {slug} historico={final_hist} eventos={final_evt}"
            )

        final_summary = out_hist / "snapshot_resumo.parquet"
        os.replace(summary, final_summary)

        ts = subprocess.run(
            ["date", "+%Y%m%d_%H%M%S"],
            text=True, capture_output=True, check=True
        ).stdout.strip()
        marker = state / "regionalizacao_historico.ok"
        marker.write_text(
            "\n".join([
                f"timestamp={ts}",
                f"snapshots={n}",
                f"first_snapshot={first}",
                f"last_snapshot={last}",
                f"summary={final_summary}",
                "semantics=observed_snapshots_not_normative_effective_dates",
                "publication=atomic_after_full_success",
                "",
            ]),
            encoding="utf-8",
        )
        print(
            f"REGIONALIZACAO_HISTORICO_OK "
            f"snapshots={n} first={first} last={last}"
        )
        print(f"summary={final_summary}")
        print(f"marker={marker}")
        return 0
    finally:
        shutil.rmtree(work, ignore_errors=True)

if __name__ == "__main__":
    raise SystemExit(main())
