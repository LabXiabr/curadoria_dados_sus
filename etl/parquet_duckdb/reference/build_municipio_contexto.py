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

def qi(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'

def duck(sql: str, capture: bool = False) -> str:
    p = subprocess.run(["duckdb","-csv","-noheader","-c",sql], text=True, capture_output=True)
    if p.returncode:
        if p.stdout: print(p.stdout, file=sys.stderr)
        if p.stderr: print(p.stderr, file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def describe(path: Path) -> dict[str,str]:
    out = duck(f"DESCRIBE SELECT * FROM read_parquet({sqls(str(path))});", True)
    rows = list(csv.reader(out.splitlines()))
    return {r[0].upper(): r[0] for r in rows if r}

def choose(cols: dict[str,str], *cands: str) -> str | None:
    for c in cands:
        if c.upper() in cols:
            return cols[c.upper()]
    return None

def val(alias: str, col: str | None, typ: str = "VARCHAR") -> str:
    if col is None:
        return f"NULL::{typ}"
    return f"{alias}.{qi(col)}"

def text_expr(alias: str, col: str | None) -> str:
    if col is None:
        return "NULL::VARCHAR"
    return f"NULLIF(trim(cast({alias}.{qi(col)} as varchar)), '')"

def num_expr(alias: str, col: str | None) -> str:
    if col is None:
        return "NULL::DOUBLE"
    q = f"trim(cast({alias}.{qi(col)} as varchar))"
    return f"try_cast(replace(NULLIF({q}, ''), ',', '.') as DOUBLE)"

def flag_expr(alias: str, col: str | None) -> str:
    if col is None:
        return "NULL::BOOLEAN"
    q = f"upper(trim(cast({alias}.{qi(col)} as varchar)))"
    return (
        f"CASE WHEN {q} IN ('1','S','SIM','Y','YES','TRUE','T') THEN TRUE "
        f"WHEN {q} IN ('0','N','NAO','NÃO','NO','FALSE','F','') THEN FALSE "
        f"ELSE NULL END"
    )

def list_agg(expr: str) -> str:
    return f"string_agg(DISTINCT cast({expr} as varchar), '|' ORDER BY cast({expr} as varchar))"

def main() -> int:
    ap=argparse.ArgumentParser(description="Constrói referencia municipal consolidada a partir da base territorial DATASUS")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()

    if not shutil.which("duckdb"):
        die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    root=lake/"silver"/"reference"/"territorio"
    state=lake/"state"/"reference"
    outdir=lake/"silver"/"reference"/"municipio_contexto"
    outdir.mkdir(parents=True,exist_ok=True)
    state.mkdir(parents=True,exist_ok=True)

    def path(table: str) -> Path:
        return root/table/"current.parquet"

    required=["tb_municip","tb_uf","tb_regiao","rl_municip_regsaud","tb_regsaud",
              "rl_municip_macsaud","tb_macsaud"]
    missing=[t for t in required if not path(t).is_file()]
    if missing:
        die(f"tabelas territoriais obrigatorias ausentes: {missing}",4)

    schemas={}
    for p in sorted(root.glob("*/current.parquet")):
        schemas[p.parent.name]=describe(p)

    mcols=schemas["tb_municip"]
    c_mun=choose(mcols,"CO_MUNICIP")
    c_mundv=choose(mcols,"CO_MUNICDV")
    c_status=choose(mcols,"CO_STATUS")
    c_nome=choose(mcols,"DS_NOME")
    c_nomepad=choose(mcols,"DS_NOMEPAD")
    c_uf=choose(mcols,"CO_UF")
    c_sguf=choose(mcols,"UF")
    c_reg=choose(mcols,"CO_REGIAO")
    if not all([c_mun,c_mundv,c_status,c_nome,c_uf,c_reg]):
        die(f"schema tb_municip inesperado: {sorted(mcols)}",5)

    ctes=[]
    joins=[]
    select=[]

    # UF
    ucols=schemas["tb_uf"]
    u_key=choose(ucols,"CO_UF")
    u_sigla=choose(ucols,"DS_SIGLA","UF")
    u_nome=choose(ucols,"DS_NOMEPAD","DS_NOME")
    ctes.append(f"""uf AS (
SELECT cast({qi(u_key)} as varchar) AS co_uf,
       {text_expr('u',u_sigla)} AS sg_uf_dim,
       {text_expr('u',u_nome)} AS no_uf
FROM read_parquet({sqls(str(path('tb_uf')))}) u
QUALIFY row_number() OVER (PARTITION BY cast({qi(u_key)} as varchar) ORDER BY 1)=1
)""")
    joins.append(f"LEFT JOIN uf ON uf.co_uf = cast(m.{qi(c_uf)} as varchar)")

    # Região
    rcols=schemas["tb_regiao"]
    r_key=choose(rcols,"CO_REGIAO")
    r_nome=choose(rcols,"DS_NOMEPAD","DS_NOME","DS_ABREV")
    ctes.append(f"""regiao AS (
SELECT cast({qi(r_key)} as varchar) AS co_regiao,
       {text_expr('r',r_nome)} AS no_regiao
FROM read_parquet({sqls(str(path('tb_regiao')))}) r
QUALIFY row_number() OVER (PARTITION BY cast({qi(r_key)} as varchar) ORDER BY 1)=1
)""")
    joins.append(f"LEFT JOIN regiao ON regiao.co_regiao = cast(m.{qi(c_reg)} as varchar)")

    # Relacionamentos genéricos: todos agregados para garantir uma linha por município.
    specs=[
      ("regiao_saude","rl_municip_regsaud","tb_regsaud","CO_REGSAUD",("DS_NOME","DS_NOMEPAD","DS_ABREV")),
      ("macrorregiao_saude","rl_municip_macsaud","tb_macsaud","CO_MACSAUD",("DS_ABREV","DS_NOME","DS_NOMEPAD")),
      ("microrregiao_ibge","rl_municip_micibge","tb_micibge","CO_MICIBGE",("DS_NOME","DS_NOMEPAD","DS_ABREV")),
      ("regiao_metropolitana","rl_municip_regmetr","tb_regmetr","CO_REGMETR",("DS_NOME","DS_NOMEPAD","DS_ABREV")),
      ("territorio_cidadania","rl_municip_terrcid","tb_terrcid","CO_TERRCID",("DS_NOME","DS_NOMEPAD","DS_ABREV")),
      ("pndr","rl_municip_pndr","tb_pndr","CO_PNDR",("DS_NOME","DS_NOMEPAD","DS_ABREV")),
      ("divisao_administrativa","rl_municip_divadm","tb_divadm","CO_DIVADM",("DS_NOME","DS_NOMEPAD","DS_ABREV")),
      ("dsei","rl_municip_dsei","tb_dsei","CO_DSEI",("DS_NOME","DS_NOMEPAD","DS_ABREV")),
    ]

    rel_available=[]
    for slug,rel,dim,key,label_cands in specs:
        if rel not in schemas or dim not in schemas:
            continue
        rc=schemas[rel]; dc=schemas[dim]
        rm=choose(rc,"CO_MUNICIP","CO_MUNINIP")
        rk=choose(rc,key)
        dk=choose(dc,key)
        dn=choose(dc,*label_cands)
        if not all([rm,rk,dk]):
            continue
        cte=f"""x_{slug} AS (
SELECT
  cast(rr.{qi(rm)} as varchar) AS co_municipio,
  {list_agg('rr.'+qi(rk))} AS co_{slug},
  {list_agg("coalesce(nullif(trim(cast(dd."+qi(dn)+" as varchar)),''), cast(rr."+qi(rk)+" as varchar))") if dn else list_agg('rr.'+qi(rk))} AS no_{slug},
  count(DISTINCT cast(rr.{qi(rk)} as varchar)) AS qt_{slug}
FROM read_parquet({sqls(str(path(rel)))}) rr
LEFT JOIN read_parquet({sqls(str(path(dim)))}) dd
  ON cast(dd.{qi(dk)} as varchar)=cast(rr.{qi(rk)} as varchar)
GROUP BY 1
)"""
        ctes.append(cte)
        joins.append(f"LEFT JOIN x_{slug} ON x_{slug}.co_municipio = cast(m.{qi(c_mun)} as varchar)")
        rel_available.append(slug)

    # Campos principais
    direct={
      "co_municipio": f"cast(m.{qi(c_mun)} as varchar)",
      "co_municipio_ibge": f"cast(m.{qi(c_mundv)} as varchar)",
      "no_municipio": text_expr("m",c_nome),
      "no_municipio_padrao": text_expr("m",c_nomepad),
      "co_uf": f"cast(m.{qi(c_uf)} as varchar)",
      "sg_uf": f"coalesce({text_expr('m',c_sguf)}, uf.sg_uf_dim)",
      "no_uf": "uf.no_uf",
      "co_regiao": f"cast(m.{qi(c_reg)} as varchar)",
      "no_regiao": "regiao.no_regiao",
      "in_capital": flag_expr("m",choose(mcols,"IN_CAPITAL")),
      "in_amazonia_legal": flag_expr("m",choose(mcols,"IN_AMAZLEG")),
      "in_semiarido": flag_expr("m",choose(mcols,"IN_SEMIAR")),
      "in_frontzn": flag_expr("m",choose(mcols,"IN_FRONTZN")),
      "in_frontzn_raw": text_expr("m",choose(mcols,"IN_FRONTZN")),
      "dt_instal": text_expr("m",choose(mcols,"DT_INSTAL")),
      "dt_extin": text_expr("m",choose(mcols,"DT_EXTIN")),
      "nu_latitude": num_expr("m",choose(mcols,"NU_LATITUD")),
      "nu_longitude": num_expr("m",choose(mcols,"NU_LONGIT")),
      "nu_altitude": num_expr("m",choose(mcols,"NU_ALTITUD")),
      "nu_area": num_expr("m",choose(mcols,"NU_AREA")),
      "co_macrorregional_tb_municip": text_expr("m",choose(mcols,"MACRORREGIONAL")),
      "_source_snapshot": text_expr("m",choose(mcols,"_source_snapshot")),
      "_source_sha256": text_expr("m",choose(mcols,"_source_sha256")),
    }
    for alias,expr in direct.items():
        select.append(f"{expr} AS {qi(alias)}")

    for slug in rel_available:
        select += [
          f"x_{slug}.co_{slug} AS {qi('co_'+slug)}",
          f"x_{slug}.no_{slug} AS {qi('no_'+slug)}",
          f"x_{slug}.qt_{slug} AS {qi('qt_'+slug)}",
        ]

    sql=f"""
WITH
{',
'.join(ctes)}
SELECT
  {',
  '.join(select)},
  current_timestamp AS _built_at
FROM read_parquet({sqls(str(path('tb_municip')))}) m
{' '.join(joins)}
WHERE upper(trim(cast(m.{qi(c_status)} as varchar)))='ATIVO'
ORDER BY cast(m.{qi(c_mundv)} as varchar)
"""

    dest=outdir/"current.parquet"
    tmp=dest.with_name(dest.name+f".partial.{os.getpid()}")
    duck(f"COPY ({sql}) TO {sqls(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);")

    stats=duck(f"""
SELECT
 count(*) AS rows,
 count(DISTINCT co_municipio) AS mun6,
 count(DISTINCT co_municipio_ibge) AS mun7,
 count(DISTINCT co_uf) AS ufs,
 count(DISTINCT co_regiao) AS regioes,
 count(*) FILTER (WHERE co_regiao_saude IS NULL OR co_regiao_saude='') AS miss_regsaud,
 count(*) FILTER (WHERE co_macrorregiao_saude IS NULL OR co_macrorregiao_saude='') AS miss_macsaud
FROM read_parquet({sqls(str(tmp))});
""",True).strip()
    row=next(csv.reader([stats]))
    rows,mun6,mun7,ufs,regioes,miss_reg,miss_mac=map(int,row)
    if rows != mun6 or rows != mun7:
        die(f"duplicacao municipal rows={rows} mun6={mun6} mun7={mun7}",20)
    if rows < 5570 or ufs != 27 or regioes != 5:
        die(f"cobertura territorial inesperada rows={rows} ufs={ufs} regioes={regioes}",20)
    if miss_reg or miss_mac:
        die(f"municipios sem regionalizacao de saude: regsaud={miss_reg} macsaud={miss_mac}",20)

    os.replace(tmp,dest)

    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    schema_report=state/f"municipio_contexto_schema_{ts}.tsv"
    desc=duck(f"DESCRIBE SELECT * FROM read_parquet({sqls(str(dest))});",True)
    schema_report.write_text("column\ttype\n"+"\n".join(
        "\t".join(r[:2]) for r in csv.reader(desc.splitlines()) if r
    )+"\n",encoding="utf-8")

    marker=state/"municipio_contexto_current.ok"
    marker.write_text("\n".join([
      f"timestamp={ts}",
      f"rows={rows}",
      f"municipios_6d={mun6}",
      f"municipios_7d={mun7}",
      f"ufs={ufs}",
      f"regioes={regioes}",
      f"missing_regiao_saude={miss_reg}",
      f"missing_macrorregiao_saude={miss_mac}",
      f"relationships={'|'.join(rel_available)}",
      f"path={dest}",
      f"schema_report={schema_report}",
      ""
    ]),encoding="utf-8")
    print(f"MUNICIPIO_CONTEXTO_OK rows={rows} ufs={ufs} regioes={regioes}")
    print(f"path={dest}")
    print(f"marker={marker}")
    print(f"schema={schema_report}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
