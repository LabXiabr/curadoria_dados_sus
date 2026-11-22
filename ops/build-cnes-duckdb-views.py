#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_SQL = ROOT / "sql" / "duckdb" / "generated" / "cnes_silver_views.sql"

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def duck(database: Path, sql: str, capture: bool = False) -> str:
    p = subprocess.run(
        ["duckdb", str(database), "-csv", "-noheader", "-c", sql],
        text=True,
        capture_output=True,
    )
    if p.returncode:
        if p.stdout:
            print(p.stdout, file=sys.stderr)
        if p.stderr:
            print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Cria catalogo DuckDB privado com views Silver CNES"
    )
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslabx"),
    )
    ap.add_argument("--database", type=Path)
    ap.add_argument("--output-sql", type=Path, default=DEFAULT_SQL)
    args = ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente", 3)

    lake = Path(args.lake_root)
    database = (
        args.database or (lake / "silver" / "suslabx.duckdb")
    ).expanduser().resolve()
    sql_path = args.output_sql.expanduser().resolve()
    state = lake / "state" / "cnes"

    paths = {
        "dim_territorio": (
            lake / "silver" / "reference" / "dim_territorio" / "current.parquet"
        ),
        "dim_estabelecimento": (
            lake / "silver" / "cnes" / "dim_estabelecimento" / "current.parquet"
        ),
        "dim_tipo_estabelecimento": (
            lake / "silver" / "cnes" / "dim_tipo_estabelecimento" / "current.parquet"
        ),
        "dim_natureza_juridica": (
            lake / "silver" / "cnes" / "dim_natureza_juridica" / "current.parquet"
        ),
        "fact_estabelecimento_servico": (
            lake
            / "silver"
            / "cnes"
            / "fact_estabelecimento_servico"
            / "current.parquet"
        ),
        "fact_estabelecimento_equipamento": (
            lake
            / "silver"
            / "cnes"
            / "fact_estabelecimento_equipamento"
            / "current.parquet"
        ),
        "fact_estabelecimento_leito": (
            lake
            / "silver"
            / "cnes"
            / "fact_estabelecimento_leito"
            / "current.parquet"
        ),
        "fact_equipe": (
            lake / "silver" / "cnes" / "fact_equipe" / "current.parquet"
        ),
        "bridge_estabelecimento_equipe_profissional": (
            lake
            / "silver"
            / "cnes"
            / "bridge_estabelecimento_equipe_profissional"
            / "current.parquet"
        ),
        "dim_profissional": (
            lake / "silver" / "cnes" / "dim_profissional" / "current.parquet"
        ),
        "fact_profissional_vinculo": (
            lake
            / "silver"
            / "cnes"
            / "fact_profissional_vinculo"
            / "current.parquet"
        ),
    }

    missing = [str(path) for path in paths.values() if not path.is_file()]
    if missing:
        die("Parquet Silver ausente: " + ", ".join(missing))

    database.parent.mkdir(parents=True, exist_ok=True)
    if database.stem.lower() == "cnes":
        die(
            "nome de catalogo DuckDB 'cnes' conflita com o schema 'cnes'; "
            "use silver/suslabx.duckdb",
            4,
        )

    sql_path.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    p = {key: qs(str(value.resolve())) for key, value in paths.items()}

    hierarchy = """
  t.co_territorio_key,
  t.tp_territorio,
  t.nr_nivel_drill,
  t.co_territorio_pai_key,
  t.co_regiao_key,
  t.co_regiao,
  t.no_regiao,
  t.co_uf_key,
  t.co_uf,
  t.sg_uf,
  t.no_uf,
  t.co_macrorregiao_saude_key,
  t.co_macrorregiao_saude,
  t.no_macrorregiao_saude,
  t.co_regiao_saude_key,
  t.co_regiao_saude_drill_key,
  t.co_regiao_saude,
  t.no_regiao_saude,
  t.co_municipio_key,
  t.co_municipio,
  t.co_municipio_ibge,
  t.no_municipio,
  t.co_ra_key,
  t.co_ra_ibge,
  t.no_ra,
  t.co_microrregiao_ibge,
  t.no_microrregiao_ibge,
  t.co_regiao_metropolitana,
  t.no_regiao_metropolitana,
  t.co_territorio_cidadania,
  t.no_territorio_cidadania,
  t.co_pndr,
  t.no_pndr,
  t.co_dsei,
  t.no_dsei,
  t.in_capital,
  t.in_amazonia_legal,
  t.in_semiarido,
  t.in_frontzn
""".strip()

    sql = f"""-- GERADO AUTOMATICAMENTE. Nao editar manualmente.
-- Silver CNES privada. As views referenciam Parquet por caminho absoluto.
CREATE SCHEMA IF NOT EXISTS cnes;

CREATE OR REPLACE VIEW cnes.dim_territorio AS
SELECT * FROM read_parquet({p["dim_territorio"]});

CREATE OR REPLACE VIEW cnes.dim_estabelecimento AS
SELECT * FROM read_parquet({p["dim_estabelecimento"]});

CREATE OR REPLACE VIEW cnes.dim_tipo_estabelecimento AS
SELECT * FROM read_parquet({p["dim_tipo_estabelecimento"]});

CREATE OR REPLACE VIEW cnes.dim_natureza_juridica AS
SELECT * FROM read_parquet({p["dim_natureza_juridica"]});

CREATE OR REPLACE VIEW cnes.fact_estabelecimento_servico AS
SELECT * FROM read_parquet({p["fact_estabelecimento_servico"]});

CREATE OR REPLACE VIEW cnes.fact_estabelecimento_equipamento AS
SELECT * FROM read_parquet({p["fact_estabelecimento_equipamento"]});

CREATE OR REPLACE VIEW cnes.fact_estabelecimento_leito AS
SELECT * FROM read_parquet({p["fact_estabelecimento_leito"]});

CREATE OR REPLACE VIEW cnes.fact_equipe AS
SELECT * FROM read_parquet({p["fact_equipe"]});

CREATE OR REPLACE VIEW cnes.bridge_estabelecimento_equipe_profissional AS
SELECT * FROM read_parquet({p["bridge_estabelecimento_equipe_profissional"]});

CREATE OR REPLACE VIEW cnes.dim_profissional AS
SELECT * FROM read_parquet({p["dim_profissional"]});

CREATE OR REPLACE VIEW cnes.fact_profissional_vinculo AS
SELECT * FROM read_parquet({p["fact_profissional_vinculo"]});

CREATE OR REPLACE VIEW cnes.vw_estabelecimento_drill AS
SELECT
  e.co_unidade_key,
  e.co_cnes_key,
  e.co_localidade_gestor_cnes,
  e.territory_status,
  {hierarchy}
FROM cnes.dim_estabelecimento e
JOIN cnes.dim_territorio t
  ON t.co_territorio_key=e.co_territorio_key;

CREATE OR REPLACE VIEW cnes.vw_servico_drill AS
SELECT d.*, f.* EXCLUDE (co_unidade_key, co_cnes_key)
FROM cnes.fact_estabelecimento_servico f
JOIN cnes.vw_estabelecimento_drill d
  ON d.co_unidade_key=f.co_unidade_key;

CREATE OR REPLACE VIEW cnes.vw_equipamento_drill AS
SELECT d.*, f.* EXCLUDE (co_unidade_key, co_cnes_key)
FROM cnes.fact_estabelecimento_equipamento f
JOIN cnes.vw_estabelecimento_drill d
  ON d.co_unidade_key=f.co_unidade_key;

CREATE OR REPLACE VIEW cnes.vw_leito_drill AS
SELECT d.*, f.* EXCLUDE (co_unidade_key, co_cnes_key)
FROM cnes.fact_estabelecimento_leito f
JOIN cnes.vw_estabelecimento_drill d
  ON d.co_unidade_key=f.co_unidade_key;

CREATE OR REPLACE VIEW cnes.vw_equipe_drill AS
SELECT d.*, f.* EXCLUDE (co_unidade_key, co_cnes_key)
FROM cnes.fact_equipe f
JOIN cnes.vw_estabelecimento_drill d
  ON d.co_unidade_key=f.co_unidade_key;

CREATE OR REPLACE VIEW cnes.vw_equipe_profissional_drill AS
SELECT d.*, f.* EXCLUDE (co_unidade_key, co_cnes_key)
FROM cnes.bridge_estabelecimento_equipe_profissional f
JOIN cnes.vw_estabelecimento_drill d
  ON d.co_unidade_key=f.co_unidade_key;

CREATE OR REPLACE VIEW cnes.vw_profissional_vinculo_drill AS
SELECT d.*, f.* EXCLUDE (co_unidade_key, co_cnes_key)
FROM cnes.fact_profissional_vinculo f
JOIN cnes.vw_estabelecimento_drill d
  ON d.co_unidade_key=f.co_unidade_key;

"""

    sql_path.write_text(sql, encoding="utf-8")
    subprocess.run(["duckdb", str(database), "-f", str(sql_path)], check=True)

    stats = duck(
        database,
        """
SELECT
  (SELECT count(*) FROM cnes.dim_territorio),
  (SELECT count(*) FROM cnes.dim_estabelecimento),
  (SELECT count(*) FROM cnes.vw_estabelecimento_drill),
  (
    SELECT count(*)
    FROM cnes.dim_estabelecimento e
    LEFT JOIN cnes.dim_territorio t
      ON t.co_territorio_key=e.co_territorio_key
    WHERE e.co_territorio_key IS NULL
       OR t.co_territorio_key IS NULL
  );
""",
        True,
    ).strip()

    territorio, estab, drill, orphans = map(
        int,
        next(csv.reader([stats])),
    )

    if estab != drill or orphans != 0:
        die(
            f"QC views falhou dim_estabelecimento={estab} "
            f"vw_estabelecimento_drill={drill} "
            f"territory_orphans={orphans}",
            30,
        )

    ts = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    marker = state / "duckdb_views_current.ok"
    marker.write_text(
        "\n".join(
            [
                f"timestamp={ts}",
                f"database={database}",
                f"sql={sql_path}",
                f"dim_territorio_rows={territorio}",
                f"dim_estabelecimento_rows={estab}",
                f"vw_estabelecimento_drill_rows={drill}",
                f"territory_orphans={orphans}",
                (
                    "views="
                    "cnes.dim_territorio|"
                    "cnes.dim_estabelecimento|"
                    "cnes.dim_tipo_estabelecimento|"
                    "cnes.dim_natureza_juridica|"
                    "cnes.fact_estabelecimento_servico|"
                    "cnes.fact_estabelecimento_equipamento|"
                    "cnes.fact_estabelecimento_leito|"
                    "cnes.fact_equipe|"
                    "cnes.bridge_estabelecimento_equipe_profissional|"
                    "cnes.dim_profissional|"
                    "cnes.fact_profissional_vinculo|"
                    "cnes.vw_estabelecimento_drill|"
                    "cnes.vw_servico_drill|"
                    "cnes.vw_equipamento_drill|"
                    "cnes.vw_leito_drill|"
                    "cnes.vw_equipe_drill|"
                    "cnes.vw_equipe_profissional_drill|"
                    "cnes.vw_profissional_vinculo_drill|"
                ),
                "storage=views_only_no_fact_materialization",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"CNES_DUCKDB_VIEWS_OK database={database}")
    print(f"sql={sql_path}")
    print(f"marker={marker}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
