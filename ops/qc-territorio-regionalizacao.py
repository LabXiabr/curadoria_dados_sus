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

def die(msg: str, code: int = 2):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def sqls(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def qi(v: str) -> str:
    return '"' + v.replace('"','""') + '"'

def duck(sql: str, capture: bool = False) -> str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        if p.stdout: print(p.stdout,file=sys.stderr)
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def describe(path: Path) -> dict[str,str]:
    out=duck(f"DESCRIBE SELECT * FROM read_parquet({sqls(str(path))});",True)
    return {r[0].lower():r[0] for r in csv.reader(out.splitlines()) if r}

def choose(cols: dict[str,str], *cands: str) -> str | None:
    for c in cands:
        if c.lower() in cols:
            return cols[c.lower()]
    return None

def main() -> int:
    ap=argparse.ArgumentParser(description="Compara regionalizacao territorial DATASUS com Portal de Dados Abertos")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()
    if not shutil.which("duckdb"): die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    ctx=lake/"silver"/"reference"/"municipio_contexto"/"current.parquet"
    portal=lake/"silver"/"reference"/"regionalizacao_saude"/"macroregiao_de_saude"/"current.parquet"
    state=lake/"state"/"reference"
    state.mkdir(parents=True,exist_ok=True)
    if not ctx.is_file(): die(f"contexto municipal ausente: {ctx}",4)
    if not portal.is_file(): die(f"regionalizacao Portal ausente: {portal}",4)

    pc=describe(portal)
    c_mun=choose(pc,"codigo_municipio","cod_municipio","codigo_ibge","co_municipio")
    c_reg=choose(pc,"codigo_regiao_saude","cod_regiao_saude","co_regsaud")
    c_mac=choose(pc,"codigo_macrorregiao_saude","cod_macrorregiao_saude","co_macsaud")
    c_nomemun=choose(pc,"municipio","nome_municipio","no_municipio")
    c_nreg=choose(pc,"regiao_saude","nome_regiao_saude","no_regiao_saude")
    c_nmac=choose(pc,"macrorregiao_saude","nome_macrorregiao_saude","no_macrorregiao_saude")
    if not all([c_mun,c_reg,c_mac]):
        die(f"schema Portal inesperado: {sorted(pc.values())}",5)

    raw_code=f"regexp_replace(trim(cast(p.{qi(c_mun)} as varchar)), '[^0-9]', '', 'g')"
    portal_mun6=(
        f"CASE "
        f"WHEN length({raw_code})=7 THEN substr({raw_code},1,6) "
        f"WHEN length({raw_code})<=6 THEN lpad({raw_code},6,'0') "
        f"ELSE NULL END"
    )
    portal_mun7=(
        f"CASE WHEN length({raw_code})=7 THEN {raw_code} ELSE NULL END"
    )

    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    report=state/f"qc_territorio_regionalizacao_{ts}.tsv"
    tmp=report.with_suffix(".csv")

    nmun=f"trim(cast(p.{qi(c_nomemun)} as varchar))" if c_nomemun else "NULL::VARCHAR"
    nreg=f"trim(cast(p.{qi(c_nreg)} as varchar))" if c_nreg else "NULL::VARCHAR"
    nmac=f"trim(cast(p.{qi(c_nmac)} as varchar))" if c_nmac else "NULL::VARCHAR"

    sql=f"""
WITH portal AS (
 SELECT
   {portal_mun6} AS co_municipio,
   {portal_mun7} AS co_municipio_ibge,
   {nmun} AS no_municipio_portal,
   trim(cast(p.{qi(c_reg)} as varchar)) AS co_regiao_saude_portal,
   {nreg} AS no_regiao_saude_portal,
   trim(cast(p.{qi(c_mac)} as varchar)) AS co_macrorregiao_saude_portal,
   {nmac} AS no_macrorregiao_saude_portal
 FROM read_parquet({sqls(str(portal))}) p
),
base AS (
 SELECT
   co_municipio,
   co_municipio_ibge,
   no_municipio,
   sg_uf,
   co_regiao_saude,
   no_regiao_saude,
   co_macrorregiao_saude,
   no_macrorregiao_saude,
   qt_regiao_saude,
   qt_macrorregiao_saude
 FROM read_parquet({sqls(str(ctx))})
),
cmp AS (
 SELECT
   coalesce(b.co_municipio,p.co_municipio) AS co_municipio,
   coalesce(b.co_municipio_ibge,p.co_municipio_ibge) AS co_municipio_ibge,
   b.no_municipio,
   p.no_municipio_portal,
   b.sg_uf,
   b.co_regiao_saude,
   p.co_regiao_saude_portal,
   b.no_regiao_saude,
   p.no_regiao_saude_portal,
   b.co_macrorregiao_saude,
   p.co_macrorregiao_saude_portal,
   b.no_macrorregiao_saude,
   p.no_macrorregiao_saude_portal,
   b.qt_regiao_saude,
   b.qt_macrorregiao_saude,
   CASE
     WHEN b.co_municipio IS NULL THEN 'extra_portal'
     WHEN p.co_municipio IS NULL THEN 'missing_portal'
     WHEN b.qt_regiao_saude <> 1 THEN 'ambiguous_regiao_base'
     WHEN b.qt_macrorregiao_saude <> 1 THEN 'ambiguous_macro_base'
     WHEN trim(b.co_regiao_saude) <> trim(p.co_regiao_saude_portal) THEN 'mismatch_regiao'
     WHEN trim(b.co_macrorregiao_saude) <> trim(p.co_macrorregiao_saude_portal) THEN 'mismatch_macro'
     ELSE 'ok'
   END AS status
 FROM base b
 FULL OUTER JOIN portal p USING(co_municipio)
)
SELECT * FROM cmp ORDER BY status, co_municipio
"""
    duck(f"COPY ({sql}) TO {sqls(str(tmp))} (HEADER, DELIMITER '\t');")
    os.replace(tmp,report)

    summary=duck(f"""
SELECT status,count(*) FROM ({sql}) GROUP BY 1 ORDER BY 1;
""",True)
    counts={}
    for row in csv.reader(summary.splitlines()):
        if row: counts[row[0]]=int(row[1])

    marker=state/"qc_territorio_regionalizacao_latest.ok"
    marker.write_text("\n".join([
      f"timestamp={ts}",
      f"report={report}",
      *(f"{k}={v}" for k,v in sorted(counts.items())),
      ""
    ]),encoding="utf-8")

    print(f"Relatorio: {report}")
    for k,v in sorted(counts.items()):
        print(f"{k}={v}")
    if any(k!="ok" and v>0 for k,v in counts.items()):
        print("QC_TERRITORIO_REGIONALIZACAO_WARN")
    else:
        print("QC_TERRITORIO_REGIONALIZACAO_OK")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
