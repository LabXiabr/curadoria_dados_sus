#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import re
import shutil
import subprocess
import sys
import unicodedata
from pathlib import Path

ALIASES = {
    "BRASILIA": "PLANOPILOTO",
    "RIACHOFUNDOI": "RIACHOFUNDO",
}

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def qi(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'

def duck(sql: str, capture: bool = False) -> str:
    p = subprocess.run(
        ["duckdb", "-csv", "-noheader", "-c", sql],
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

def cols(path: Path) -> dict[str, str]:
    out = duck(
        f"DESCRIBE SELECT * FROM read_parquet({qs(str(path))});",
        True,
    )
    return {r[0].upper(): r[0] for r in csv.reader(out.splitlines()) if r}

def choose(m: dict[str, str], *cands: str) -> str | None:
    for cand in cands:
        if cand.upper() in m:
            return m[cand.upper()]
    return None

def norm(value: str | None) -> str:
    s = unicodedata.normalize("NFKD", value or "")
    s = "".join(c for c in s if not unicodedata.combining(c)).upper()
    return re.sub(r"[^A-Z0-9]+", "", s)

def code6(value: str | None) -> str:
    digits = re.sub(r"[^0-9]", "", value or "")
    return digits[:6] if len(digits) >= 6 else digits

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Crosswalk localidades operacionais CNES do DF para RA IBGE"
    )
    ap.add_argument("--competencia", required=True)
    ap.add_argument(
        "--lake-root",
        default=os.environ.get("LAKE_ROOT", "/dados/abertos/suslabx"),
    )
    args = ap.parse_args()

    if not re.fullmatch(r"\d{6}", args.competencia):
        die("competencia deve ser YYYYMM", 2)

    lake = Path(args.lake_root)
    estab = (
        lake
        / "bronze"
        / "cnes"
        / "tb_estabelecimento"
        / f"competencia={args.competencia}"
        / "part-000.parquet"
    )
    mun = (
        lake
        / "silver"
        / "reference"
        / "territorio"
        / "tb_municip"
        / "current.parquet"
    )
    ra = lake / "silver" / "reference" / "ra_df" / "current.parquet"
    out = (
        lake
        / "silver"
        / "cnes"
        / "bridge_localidade_cnes_ra_df"
        / "current.parquet"
    )
    state = lake / "state" / "cnes"

    for path in (estab, mun, ra):
        if not path.is_file():
            die(f"arquivo ausente: {path}", 4)

    ec = cols(estab)
    mc = cols(mun)

    e_mun = choose(ec, "CO_MUNICIPIO_GESTOR", "CO_MUNICIP_GESTOR")
    e_cnes = choose(ec, "CO_CNES")
    m_code = choose(mc, "CO_MUNICIP", "CO_MUNICIPIO", "CO_MUN")
    m_name = choose(mc, "DS_NOME", "DS_NOMEPAD", "NO_MUNICIPIO", "NM_MUNICIPIO")

    if not all([e_mun, e_cnes, m_code, m_name]):
        die(
            "schema nao resolvido: "
            f"estabelecimento={sorted(ec.values())} "
            f"territorio_tb_municip={sorted(mc.values())}",
            5,
        )

    raw = (
        f"regexp_replace(trim(cast(e.{qi(e_mun)} as varchar)), "
        "'[^0-9]', '', 'g')"
    )

    used = duck(
        f"""
SELECT
  CASE
    WHEN length({raw})>=6 THEN substr({raw},1,6)
    ELSE {raw}
  END AS co_localidade_cnes,
  count(*) AS rows_estabelecimento,
  min(trim(cast(e.{qi(e_cnes)} as varchar))) AS exemplo_cnes
FROM read_parquet({qs(str(estab))}) e
WHERE substr(
  CASE
    WHEN length({raw})>=6 THEN substr({raw},1,6)
    ELSE {raw}
  END,
  1,
  2
)='53'
GROUP BY 1
ORDER BY 1;
""",
        True,
    )

    used_rows = [r for r in csv.reader(used.splitlines()) if r]

    catalog = duck(
        f"""
SELECT
  trim(cast({qi(m_code)} as varchar)) AS code,
  trim(cast({qi(m_name)} as varchar)) AS name
FROM read_parquet({qs(str(mun))})
WHERE substr(
  regexp_replace(
    trim(cast({qi(m_code)} as varchar)),
    '[^0-9]',
    '',
    'g'
  ),
  1,
  2
)='53';
""",
        True,
    )

    names: dict[str, str] = {}
    for code, name in csv.reader(catalog.splitlines()):
        names[code6(code)] = name

    ra_rows = duck(
        f"SELECT co_ra_ibge, no_ra FROM read_parquet({qs(str(ra))});",
        True,
    )

    ra_index: dict[str, list[tuple[str, str]]] = {}
    for code, name in csv.reader(ra_rows.splitlines()):
        ra_index.setdefault(norm(name), []).append((code, name))

    rows = []
    unresolved = 0
    ambiguous = 0

    for code, n, example in used_rows:
        source_name = names.get(code, "")
        source_norm = norm(source_name)
        target_norm = ALIASES.get(source_norm, source_norm)
        candidates = ra_index.get(target_norm, [])

        if len(candidates) == 1:
            ra_code, ra_name = candidates[0]
            status = "matched"
            method = "alias" if source_norm in ALIASES else "name_exact_normalized"
        elif len(candidates) > 1:
            ra_code = ""
            ra_name = ""
            status = "ambiguous"
            method = "name_ambiguous"
            ambiguous += 1
        else:
            ra_code = ""
            ra_name = ""
            status = "unresolved"
            method = "name_unresolved"
            unresolved += 1

        rows.append(
            {
                "co_localidade_cnes": code,
                "no_localidade_cnes": source_name,
                "rows_estabelecimento": n,
                "exemplo_cnes": example,
                "co_ra_ibge": ra_code,
                "no_ra": ra_name,
                "match_status": status,
                "match_method": method,
            }
        )

    if not rows:
        die("nenhuma localidade DF encontrada em tb_estabelecimento", 20)

    out.parent.mkdir(parents=True, exist_ok=True)
    state.mkdir(parents=True, exist_ok=True)

    detail = state / f"df_ra_crosswalk_{args.competencia}.tsv"
    fields = list(rows[0].keys())

    with detail.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(
            f,
            fieldnames=fields,
            delimiter="\t",
            lineterminator="\n",
        )
        w.writeheader()
        w.writerows(rows)

    tmp = out.with_name(out.name + f".partial.{os.getpid()}")

    duck(f"""
COPY (
  SELECT
    *,
    {qs(args.competencia)}::VARCHAR AS _silver_competencia,
    current_timestamp AS _built_at
  FROM read_csv(
    {qs(str(detail))},
    delim='\t',
    header=true,
    all_varchar=true,
    parallel=false
  )
)
TO {qs(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")

    os.replace(tmp, out)

    matched = len(rows) - unresolved - ambiguous
    marker = state / f"df_ra_crosswalk_{args.competencia}.ok"
    marker.unlink(missing_ok=True)

    print(
        "CNES_DF_RA_CROSSWALK "
        f"localidades={len(rows)} matched={matched} "
        f"unresolved={unresolved} ambiguous={ambiguous}"
    )
    print(f"detail={detail}")

    if unresolved or ambiguous:
        print("CNES_DF_RA_CROSSWALK_FAIL", file=sys.stderr)
        return 20

    ts = subprocess.run(
        ["date", "+%Y%m%d_%H%M%S"],
        text=True,
        capture_output=True,
        check=True,
    ).stdout.strip()

    marker.write_text(
        "\n".join(
            [
                f"competencia={args.competencia}",
                f"timestamp={ts}",
                f"localidades={len(rows)}",
                f"matched={matched}",
                "unresolved=0",
                "ambiguous=0",
                f"path={out}",
                f"detail={detail}",
                "cnes_locality_domain_table=reference/territorio/tb_municip",
                "source_ra=IBGE_Localidades_do_Brasil_2022",
                "policy=name_exact_normalized_plus_explicit_aliases;never_CO_UNIDADE_prefix",
                "",
            ]
        ),
        encoding="utf-8",
    )

    print(f"marker={marker}")
    print("CNES_DF_RA_CROSSWALK_OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
