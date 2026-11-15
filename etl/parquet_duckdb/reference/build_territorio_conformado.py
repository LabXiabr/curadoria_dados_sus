#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import shutil
import subprocess
import sys
from pathlib import Path

def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def qi(v: str) -> str:
    return '"' + v.replace('"','""') + '"'

def duck(sql: str, capture: bool=False) -> str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        if p.stdout: print(p.stdout,file=sys.stderr)
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def columns(path: Path) -> dict[str,str]:
    out=duck(f"DESCRIBE SELECT * FROM read_parquet({qs(str(path))});",True)
    return {r[0].upper():r[0] for r in csv.reader(out.splitlines()) if r}

def choose(cols: dict[str,str], *cands: str) -> str | None:
    for c in cands:
        if c.upper() in cols:
            return cols[c.upper()]
    return None

def main() -> int:
    ap=argparse.ArgumentParser(description="Constroi dimensao territorial conformada: municipios + divisoes administrativas do DF")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    ctx=lake/"silver"/"reference"/"municipio_contexto"/"current.parquet"
    rel=lake/"silver"/"reference"/"territorio"/"rl_municip_divadm"/"current.parquet"
    dim=lake/"silver"/"reference"/"territorio"/"tb_divadm"/"current.parquet"
    out=lake/"silver"/"reference"/"dim_territorio"/"current.parquet"
    state=lake/"state"/"reference"
    out.parent.mkdir(parents=True,exist_ok=True)
    state.mkdir(parents=True,exist_ok=True)

    for p in (ctx,rel,dim):
        if not p.is_file():
            die(f"referencia territorial ausente: {p}")

    rc=columns(rel)
    dc=columns(dim)
    rm=choose(rc,"CO_MUNICIP","CO_MUNINIP")
    rk=choose(rc,"CO_DIVADM")
    dk=choose(dc,"CO_DIVADM")
    dn=choose(dc,"DS_NOME","DS_NOMEPAD","DS_ABREV")
    if not all([rm,rk,dk,dn]):
        die(
            "schema de divisao administrativa nao resolvido: "
            f"rel={sorted(rc.values())} dim={sorted(dc.values())}"
        )

    rel_code=f"trim(cast(r.{qi(rk)} as varchar))"
    dim_name=f"nullif(trim(cast(d.{qi(dn)} as varchar)),'')"
    ra_ibge=f"CASE WHEN regexp_matches({rel_code}, '^530010[0-9]{{5}}$') THEN {rel_code} END"
    territory_key=f"coalesce({ra_ibge}, 'DF_DIVADM:' || {rel_code})"

    tmp=out.with_name(out.name+f".partial.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    duck(f"""
COPY (
WITH brasilia AS (
  SELECT *
  FROM read_parquet({qs(str(ctx))})
  WHERE co_municipio='530010' OR co_municipio_ibge='5300108'
  QUALIFY row_number() OVER (ORDER BY co_municipio_ibge)=1
),
df_div AS (
  SELECT DISTINCT
    {rel_code} AS co_divisao_administrativa,
    {dim_name} AS no_divisao_administrativa,
    {ra_ibge} AS co_ra_ibge,
    {territory_key} AS co_territorio
  FROM read_parquet({qs(str(rel))}) r
  LEFT JOIN read_parquet({qs(str(dim))}) d
    ON trim(cast(d.{qi(dk)} as varchar))={rel_code}
  WHERE trim(cast(r.{qi(rm)} as varchar))='530010'
    AND {rel_code}<>''
)
SELECT
  co_municipio_ibge AS co_territorio,
  'MUNICIPIO'::VARCHAR AS tp_territorio,
  NULL::VARCHAR AS co_territorio_pai,
  co_municipio,
  co_municipio_ibge,
  no_municipio,
  co_uf,
  sg_uf,
  no_uf,
  co_regiao,
  no_regiao,
  co_regiao_saude,
  no_regiao_saude,
  co_macrorregiao_saude,
  no_macrorregiao_saude,
  NULL::VARCHAR AS co_divisao_administrativa,
  NULL::VARCHAR AS no_divisao_administrativa,
  NULL::VARCHAR AS co_ra_ibge,
  'DATASUS_BASE_TERRITORIAL_TB_MUNICIP'::VARCHAR AS fonte_codigo,
  current_timestamp AS _built_at
FROM read_parquet({qs(str(ctx))})

UNION ALL

SELECT
  d.co_territorio,
  'RA_DF'::VARCHAR AS tp_territorio,
  '5300108'::VARCHAR AS co_territorio_pai,
  b.co_municipio,
  b.co_municipio_ibge,
  b.no_municipio,
  b.co_uf,
  b.sg_uf,
  b.no_uf,
  b.co_regiao,
  b.no_regiao,
  b.co_regiao_saude,
  b.no_regiao_saude,
  b.co_macrorregiao_saude,
  b.no_macrorregiao_saude,
  d.co_divisao_administrativa,
  d.no_divisao_administrativa,
  d.co_ra_ibge,
  'DATASUS_BASE_TERRITORIAL_TB_DIVADM'::VARCHAR AS fonte_codigo,
  current_timestamp AS _built_at
FROM df_div d
CROSS JOIN brasilia b
)
TO {qs(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")

    stats=duck(f"""
SELECT
  count(*) AS rows,
  count(*) FILTER (WHERE tp_territorio='MUNICIPIO') AS municipios,
  count(*) FILTER (WHERE tp_territorio='RA_DF') AS df_divisoes,
  count(*) FILTER (WHERE tp_territorio='RA_DF' AND co_ra_ibge IS NOT NULL) AS df_ra_ibge_resolvidas,
  count(*) FILTER (WHERE tp_territorio='RA_DF' AND co_ra_ibge IS NULL) AS df_ra_ibge_pendentes,
  count(*) - count(DISTINCT co_territorio) AS duplicate_keys
FROM read_parquet({qs(str(tmp))});
""",True).strip()
    vals=list(map(int,next(csv.reader([stats]))))
    keys=["rows","municipios","df_divisoes","df_ra_ibge_resolvidas","df_ra_ibge_pendentes","duplicate_keys"]
    s=dict(zip(keys,vals))

    if s["municipios"] != 5571 or s["df_divisoes"] < 1 or s["duplicate_keys"] != 0:
        tmp.unlink(missing_ok=True)
        die(f"QC territorio conformado falhou: {s}")

    os.replace(tmp,out)
    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    marker=state/"territorio_conformado_current.ok"
    marker.write_text("\n".join([
        f"timestamp={ts}",
        *(f"{k}={v}" for k,v in s.items()),
        f"path={out}",
        "scope=municipios_IBGE_mais_divisoes_administrativas_DF",
        "policy=co_ra_ibge_somente_quando_codigo_de_referencia_for_11d_530010xxxxx;sem_inferencia_por_CO_UNIDADE",
        ""
    ]),encoding="utf-8")

    print("TERRITORIO_CONFORMADO " + " ".join(f"{k}={v}" for k,v in s.items()))
    if s["df_ra_ibge_pendentes"]:
        print(
            "WARN: ha divisoes administrativas do DF sem codigo IBGE 11d resolvido "
            f"na referencia: {s['df_ra_ibge_pendentes']}"
        )
    print(f"path={out}")
    print(f"marker={marker}")
    print("TERRITORIO_CONFORMADO_OK")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
