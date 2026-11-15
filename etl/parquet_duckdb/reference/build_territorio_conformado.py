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
    ap=argparse.ArgumentParser(
        description="Constroi dimensao territorial Silver conformada e hierarquica"
    )
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
df_ref AS (
  SELECT DISTINCT
    {rel_code} AS co_ra_referencia,
    {dim_name} AS no_ra_referencia,
    {ra_ibge} AS co_ra_ibge
  FROM read_parquet({qs(str(rel))}) r
  LEFT JOIN read_parquet({qs(str(dim))}) d
    ON trim(cast(d.{qi(dk)} as varchar))={rel_code}
  WHERE trim(cast(r.{qi(rm)} as varchar))='530010'
    AND {rel_code}<>''
),
ra_resolvida AS (
  SELECT *
  FROM df_ref
  WHERE co_ra_ibge IS NOT NULL
)
SELECT
  'MUN:' || co_municipio_ibge AS co_territorio_key,
  'MUNICIPIO'::VARCHAR AS tp_territorio,
  5::INTEGER AS nr_nivel_drill,
  NULL::VARCHAR AS co_territorio_pai_key,
  c.*,
  NULL::VARCHAR AS co_ra_referencia,
  NULL::VARCHAR AS no_ra_referencia,
  NULL::VARCHAR AS co_ra_ibge,
  NULL::VARCHAR AS no_ra,
  'DATASUS_BASE_TERRITORIAL_MUNICIPIO_CONTEXTO'::VARCHAR AS fonte_territorio,
  current_timestamp AS _territorio_built_at
FROM read_parquet({qs(str(ctx))}) c

UNION ALL

SELECT
  'RA_DF:' || r.co_ra_ibge AS co_territorio_key,
  'RA_DF'::VARCHAR AS tp_territorio,
  6::INTEGER AS nr_nivel_drill,
  'MUN:5300108'::VARCHAR AS co_territorio_pai_key,
  b.*,
  r.co_ra_referencia,
  r.no_ra_referencia,
  r.co_ra_ibge,
  r.no_ra_referencia AS no_ra,
  'DATASUS_BASE_TERRITORIAL_DIVADM_IBGE11'::VARCHAR AS fonte_territorio,
  current_timestamp AS _territorio_built_at
FROM ra_resolvida r
CROSS JOIN brasilia b
)
TO {qs(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")

    stats=duck(f"""
WITH dfref AS (
  SELECT DISTINCT
    {rel_code} AS co_ref,
    {ra_ibge} AS co_ra_ibge
  FROM read_parquet({qs(str(rel))}) r
  WHERE trim(cast(r.{qi(rm)} as varchar))='530010'
    AND {rel_code}<>''
)
SELECT
  (SELECT count(*) FROM read_parquet({qs(str(tmp))})) AS rows,
  (SELECT count(*) FROM read_parquet({qs(str(tmp))}) WHERE tp_territorio='MUNICIPIO') AS municipios,
  (SELECT count(*) FROM read_parquet({qs(str(tmp))}) WHERE tp_territorio='RA_DF') AS df_ra_rows,
  (SELECT count(*) FROM dfref) AS df_ref_codes,
  (SELECT count(*) FROM dfref WHERE co_ra_ibge IS NOT NULL) AS df_ra_ibge_resolvidas,
  (SELECT count(*) FROM dfref WHERE co_ra_ibge IS NULL) AS df_ra_ibge_pendentes,
  (SELECT count(*) - count(DISTINCT co_territorio_key) FROM read_parquet({qs(str(tmp))})) AS duplicate_keys,
  (SELECT count(*) FROM read_parquet({qs(str(tmp))}) WHERE co_territorio_key IS NULL OR co_territorio_key='') AS missing_keys;
""",True).strip()
    vals=list(map(int,next(csv.reader([stats]))))
    keys=[
        "rows","municipios","df_ra_rows","df_ref_codes",
        "df_ra_ibge_resolvidas","df_ra_ibge_pendentes",
        "duplicate_keys","missing_keys"
    ]
    s=dict(zip(keys,vals))

    if (
        s["municipios"] != 5571
        or s["df_ra_rows"] != s["df_ra_ibge_resolvidas"]
        or s["duplicate_keys"] != 0
        or s["missing_keys"] != 0
    ):
        tmp.unlink(missing_ok=True)
        die(f"QC territorio conformado falhou: {s}")

    os.replace(tmp,out)
    ts=subprocess.run(
        ["date","+%Y%m%d_%H%M%S"],
        text=True,capture_output=True,check=True
    ).stdout.strip()
    marker=state/"territorio_conformado_current.ok"
    marker.write_text("\n".join([
        f"timestamp={ts}",
        *(f"{k}={v}" for k,v in s.items()),
        f"path={out}",
        "layer=silver",
        "grain=menor_territorio_resolvido_com_seguranca",
        "key=MUN:IBGE7|RA_DF:IBGE11",
        "hierarquia_principal=REGIAO>UF>MACRORREGIAO_SAUDE>REGIAO_SAUDE>MUNICIPIO>RA_DF",
        "alternative_hierarchies=MICRORREGIAO_IBGE|REGIAO_METROPOLITANA|DSEI|PNDR|TERRITORIO_CIDADANIA",
        "policy=RA_DF_so_entra_na_dimensao_quando_codigo_IBGE11_estiver_resolvido;sem_inferencia_por_CO_UNIDADE",
        ""
    ]),encoding="utf-8")

    print("TERRITORIO_CONFORMADO " + " ".join(f"{k}={v}" for k,v in s.items()))
    if s["df_ra_ibge_pendentes"]:
        print(
            "WARN: referencia atual possui itens DF ainda nao promovidos a RA_DF: "
            f"{s['df_ra_ibge_pendentes']}"
        )
    print(f"path={out}")
    print(f"marker={marker}")
    print("TERRITORIO_CONFORMADO_OK")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
