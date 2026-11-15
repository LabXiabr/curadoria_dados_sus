#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def duck(sql: str, capture: bool = False) -> str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        if p.stdout: print(p.stdout,file=sys.stderr)
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def build_one(lake: Path, rel_table: str, code_col: str, slug: str) -> tuple[Path,Path]:
    pattern=lake/"bronze"/"reference"/"territorio"/rel_table/"snapshot=*"/"part-000.parquet"
    matches=sorted((lake/"bronze"/"reference"/"territorio"/rel_table).glob("snapshot=*/part-000.parquet"))
    if not matches:
        raise RuntimeError(f"sem snapshots para {rel_table}")

    outdir=lake/"silver"/"reference"/"regionalizacao_historico"
    evdir=lake/"silver"/"reference"/"regionalizacao_eventos"
    outdir.mkdir(parents=True,exist_ok=True)
    evdir.mkdir(parents=True,exist_ok=True)
    hist=outdir/f"municipio_{slug}.parquet"
    events=evdir/f"municipio_{slug}.parquet"

    base=f"""
WITH obs AS (
 SELECT DISTINCT
   trim(cast(CO_MUNICIP as varchar)) AS co_municipio,
   trim(cast({code_col} as varchar)) AS codigo,
   cast(snapshot as varchar) AS snapshot_key
 FROM read_parquet(
   {sqls(str(pattern))},
   hive_partitioning=true,
   union_by_name=true
 )
 WHERE CO_MUNICIP IS NOT NULL
   AND {code_col} IS NOT NULL
),
ordered AS (
 SELECT *,
        lag(codigo) OVER (PARTITION BY co_municipio ORDER BY snapshot_key) AS prev_codigo,
        lag(snapshot_key) OVER (PARTITION BY co_municipio ORDER BY snapshot_key) AS prev_snapshot
 FROM obs
),
flagged AS (
 SELECT *,
        CASE WHEN prev_codigo IS NULL OR codigo <> prev_codigo THEN 1 ELSE 0 END AS new_group
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

    hsql=base+f"""
SELECT
 co_municipio,
 codigo AS co_{slug},
 min(snapshot_key) AS observed_from_snapshot,
 max(snapshot_key) AS observed_to_snapshot,
 count(*) AS observed_snapshots,
 (max(snapshot_key)= (SELECT max(snapshot_key) FROM obs)) AS is_current_observation
FROM grp
GROUP BY co_municipio,codigo,grp
ORDER BY co_municipio,observed_from_snapshot
"""
    tmp=hist.with_name(hist.name+f".partial.{os.getpid()}")
    duck(f"COPY ({hsql}) TO {sqls(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);")
    os.replace(tmp,hist)

    esql=base+f"""
SELECT
 co_municipio,
 prev_codigo AS co_{slug}_anterior,
 codigo AS co_{slug}_novo,
 prev_snapshot AS ultima_observacao_anterior,
 snapshot_key AS primeira_observacao_nova,
 'snapshot_change'::VARCHAR AS tp_evento
FROM ordered
WHERE prev_codigo IS NOT NULL AND codigo <> prev_codigo
ORDER BY snapshot_key,co_municipio
"""
    etmp=events.with_name(events.name+f".partial.{os.getpid()}")
    duck(f"COPY ({esql}) TO {sqls(str(etmp))} (FORMAT PARQUET, COMPRESSION ZSTD);")
    os.replace(etmp,events)

    return hist,events

def main() -> int:
    ap=argparse.ArgumentParser(description="Constrói histórico temporal da regionalização a partir dos snapshots DATASUS")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()
    if not shutil.which("duckdb"): die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    state=lake/"state"/"reference"
    state.mkdir(parents=True,exist_ok=True)

    gate=state/"territorio_backfill_complete.ok"
    if not gate.is_file():
        die(
            f"backfill territorial ainda nao homologado: {gate}. "
            "Conclua ops/territorio-backfill.sh antes de gerar a memoria temporal.",
            20,
        )

    specs=[
      ("rl_municip_regsaud","CO_REGSAUD","regiao_saude"),
      ("rl_municip_macsaud","CO_MACSAUD","macrorregiao_saude"),
    ]
    outputs=[]
    for rel,col,slug in specs:
        h,e=build_one(lake,rel,col,slug)
        outputs.append((slug,h,e))
        print(f"OK {slug} historico={h} eventos={e}")

    summary=lake/"silver"/"reference"/"regionalizacao_historico"/"snapshot_resumo.parquet"
    reg_pattern=lake/"bronze"/"reference"/"territorio"/"rl_municip_regsaud"/"snapshot=*"/"part-000.parquet"
    mac_pattern=lake/"bronze"/"reference"/"territorio"/"rl_municip_macsaud"/"snapshot=*"/"part-000.parquet"
    tmp=summary.with_name(summary.name+f".partial.{os.getpid()}")
    duck(f"""
COPY (
 WITH r AS (
   SELECT cast("snapshot" as varchar) AS snapshot_key,
          count(DISTINCT trim(cast(CO_MUNICIP as varchar))) municipios_regiao,
          count(DISTINCT trim(cast(CO_REGSAUD as varchar))) regioes_saude
   FROM read_parquet({sqls(str(reg_pattern))},hive_partitioning=true,union_by_name=true)
   GROUP BY 1
 ),
 m AS (
   SELECT cast("snapshot" as varchar) AS snapshot_key,
          count(DISTINCT trim(cast(CO_MUNICIP as varchar))) municipios_macro,
          count(DISTINCT trim(cast(CO_MACSAUD as varchar))) macrorregioes_saude
   FROM read_parquet({sqls(str(mac_pattern))},hive_partitioning=true,union_by_name=true)
   GROUP BY 1
 )
 SELECT coalesce(r.snapshot_key,m.snapshot_key) AS snapshot_key,
        r.municipios_regiao,
        r.regioes_saude,
        m.municipios_macro,
        m.macrorregioes_saude
 FROM r FULL OUTER JOIN m USING(snapshot_key)
 ORDER BY snapshot_key
)
TO {sqls(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
    os.replace(tmp,summary)

    stats=duck(f"SELECT count(*), min(snapshot_key), max(snapshot_key) FROM read_parquet({sqls(str(summary))});",True).strip()
    n,first,last=next(csv.reader([stats]))
    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    marker=state/"regionalizacao_historico.ok"
    marker.write_text("\n".join([
      f"timestamp={ts}",
      f"snapshots={n}",
      f"first_snapshot={first}",
      f"last_snapshot={last}",
      f"summary={summary}",
      "semantics=observed_snapshots_not_normative_effective_dates",
      ""
    ]),encoding="utf-8")
    print(f"REGIONALIZACAO_HISTORICO_OK snapshots={n} first={first} last={last}")
    print(f"summary={summary}")
    print(f"marker={marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
