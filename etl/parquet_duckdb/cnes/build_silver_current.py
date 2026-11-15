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

CORE = [
    ("dim_servico_especializado", "tb_servico_especializado", None),
    ("dim_classificacao_servico", "tb_classificacao_servico", None),
    ("dim_equipamento", "tb_equipamento", None),
    ("dim_tipo_equipamento", "tb_tipo_equipamento", None),
    ("dim_leito", "tb_leito", None),
    ("dim_tipo_estabelecimento", "tb_tipo_estabelecimento", None),
    ("dim_natureza_juridica", "tb_natureza_juridica", None),
    ("dim_profissional", "tb_dados_profissional_sus", None),
    ("fact_estabelecimento_servico", "rl_estab_serv_class", "CO_UNIDADE"),
    ("fact_estabelecimento_equipamento", "rl_estab_equipamento", "CO_UNIDADE"),
    ("fact_estabelecimento_leito", "rl_estab_complementar", "CO_UNIDADE"),
    ("fact_equipe", "tb_equipe", "CO_UNIDADE"),
    ("bridge_estabelecimento_equipe_profissional", "rl_estab_equipe_prof", "CO_UNIDADE"),
    ("fact_profissional_vinculo", "tb_carga_horaria_sus", "CO_UNIDADE"),
]
def die(msg: str, code: int = 20):
    print(f"ERRO: {msg}", file=sys.stderr)
    raise SystemExit(code)

def qs(v: str) -> str:
    return "'" + str(v).replace("'", "''") + "'"

def qi(v: str) -> str:
    return '"' + v.replace('"', '""') + '"'

def duck(sql: str, capture: bool=False) -> str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        if p.stdout: print(p.stdout,file=sys.stderr)
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""

def read_marker(path: Path) -> dict[str,str]:
    out={}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out

def columns(path: Path) -> list[str]:
    out=duck(f"DESCRIBE SELECT * FROM read_parquet({qs(str(path))});",True)
    return [r[0] for r in csv.reader(out.splitlines()) if r]

def require_col(path: Path, name: str) -> str:
    m={c.upper():c for c in columns(path)}
    if name.upper() not in m:
        raise RuntimeError(f"{path}: coluna obrigatoria ausente: {name}")
    return m[name.upper()]

def count(path: Path) -> int:
    return int(duck(f"SELECT count(*) FROM read_parquet({qs(str(path))});",True).strip())

def copy_query(sql: str, dest: Path):
    dest.parent.mkdir(parents=True,exist_ok=True)
    tmp=dest.with_name(dest.name+f".partial.{os.getpid()}")
    tmp.unlink(missing_ok=True)
    duck(f"COPY ({sql}) TO {qs(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);")
    os.replace(tmp,dest)

def main() -> int:
    ap=argparse.ArgumentParser(description="CNES Bronze homologada -> Silver current")
    ap.add_argument("--competencia",required=True)
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()

    if not re.fullmatch(r"\d{6}",args.competencia):
        die("competencia deve ser YYYYMM",2)
    if not shutil.which("duckdb"):
        die("duckdb CLI ausente",3)

    lake=Path(args.lake_root)
    bronze=lake/"bronze"/"cnes"
    silver=lake/"silver"/"cnes"
    state=lake/"state"/"cnes"
    terr_dim=lake/"silver"/"reference"/"dim_territorio"/"current.parquet"
    terr_all=lake/"silver"/"reference"/"territorio"/"tb_municip"/"current.parquet"
    df_xwalk=lake/"silver"/"cnes"/"bridge_localidade_cnes_ra_df"/"current.parquet"

    bm=state/f"qc_bronze_{args.competencia}.ok"
    tm=state/f"qc_territorio_{args.competencia}.ok"
    base=state/f"base_complete_{args.competencia}.ok"
    if not bm.is_file() or not tm.is_file() or not base.is_file():
        die("CNES Bronze/base/territorio ainda nao homologado")
    if not terr_dim.is_file() or not terr_all.is_file() or not df_xwalk.is_file():
        die("dimensao territorial/crosswalk DF ausente")

    bmeta=read_marker(bm)
    tmeta=read_marker(tm)
    if bmeta.get("competencia") != args.competencia:
        die("marker Bronze de competencia divergente")
    if str(tmeta.get("unmatched_rows","")) != "0":
        die("QC territorial possui unmatched_rows")

    estab=bronze/"tb_estabelecimento"/f"competencia={args.competencia}"/"part-000.parquet"
    if not estab.is_file():
        die(f"tb_estabelecimento ausente: {estab}")
    c_unidade=require_col(estab,"CO_UNIDADE")
    c_cnes=require_col(estab,"CO_CNES")
    c_mun=require_col(estab,"CO_MUNICIPIO_GESTOR")
    out_estab=silver/"dim_estabelecimento"/"current.parquet"

    munraw=f"regexp_replace(trim(cast(e.{qi(c_mun)} as varchar)), '[^0-9]', '', 'g')"
    munkey=f"""CASE
      WHEN substr({munraw},1,2)='53' AND length({munraw}) IN (6,7) THEN '530010'
      WHEN length({munraw})=7 THEN {munraw}
      WHEN length({munraw})=6 THEN {munraw}
      ELSE NULL
    END"""

    copy_query(f"""
WITH municipality_map AS (
  SELECT co_municipio AS mun_key, co_territorio_key
  FROM read_parquet({qs(str(terr_dim))})
  WHERE tp_territorio='MUNICIPIO'
  UNION ALL
  SELECT co_municipio_ibge AS mun_key, co_territorio_key
  FROM read_parquet({qs(str(terr_dim))})
  WHERE tp_territorio='MUNICIPIO'
),
xwalk AS (
  SELECT co_localidade_cnes, co_ra_ibge
  FROM read_parquet({qs(str(df_xwalk))})
  WHERE match_status='matched'
),
catalog AS (
  SELECT DISTINCT trim(cast(CO_MUNICIP as varchar)) AS mun6
  FROM read_parquet({qs(str(terr_all))})
),
src AS (
  SELECT e.*, {munraw} AS _municipio_gestor_cnes, {munkey} AS _municipio_match_key
  FROM read_parquet({qs(str(estab))}) e
),
resolved AS (
  SELECT src.*,
    CASE
      WHEN substr(src._municipio_gestor_cnes,1,2)='53' AND x.co_ra_ibge IS NOT NULL
        THEN 'RA_DF:' || x.co_ra_ibge
      ELSE m.co_territorio_key
    END AS _co_territorio_key,
    CASE
      WHEN substr(src._municipio_gestor_cnes,1,2)='53' AND x.co_ra_ibge IS NOT NULL THEN 1
      ELSE 0
    END AS _df_ra_matched
  FROM src
  LEFT JOIN municipality_map m ON m.mun_key=src._municipio_match_key
  LEFT JOIN xwalk x ON x.co_localidade_cnes=CASE
    WHEN length(src._municipio_gestor_cnes)>=6 THEN substr(src._municipio_gestor_cnes,1,6)
    ELSE src._municipio_gestor_cnes END
)
SELECT
  src.* EXCLUDE (_municipio_gestor_cnes,_municipio_match_key,_co_territorio_key,_df_ra_matched),
  trim(cast(src.{qi(c_unidade)} as varchar)) AS co_unidade_key,
  trim(cast(src.{qi(c_cnes)} as varchar)) AS co_cnes_key,
  src._municipio_gestor_cnes AS co_localidade_gestor_cnes,
  t.co_territorio_key,
  t.tp_territorio AS tp_territorio_resolvido,
  t.nr_nivel_drill AS nr_nivel_territorio_resolvido,
  CASE
    WHEN src._df_ra_matched=1 THEN 'df_ra_resolved'
    WHEN t.co_territorio_key IS NOT NULL THEN 'active'
    WHEN c.mun6 IS NOT NULL THEN 'historical_catalog'
    ELSE 'unmatched'
  END AS territory_status,
  t.co_municipio AS co_municipio_territorio,
  t.co_municipio_ibge AS co_municipio_ibge_territorio,
  t.no_municipio AS no_municipio_territorio,
  t.co_uf AS co_uf_territorio,
  t.sg_uf AS sg_uf_territorio,
  t.no_uf AS no_uf_territorio,
  t.co_regiao AS co_regiao_territorio,
  t.no_regiao AS no_regiao_territorio,
  t.in_capital,t.in_amazonia_legal,t.in_semiarido,t.in_frontzn,
  t.co_regiao_saude,t.no_regiao_saude,
  t.co_macrorregiao_saude,t.no_macrorregiao_saude,
  t.co_microrregiao_ibge,t.no_microrregiao_ibge,
  t.co_regiao_metropolitana,t.no_regiao_metropolitana,
  t.co_territorio_cidadania,t.no_territorio_cidadania,
  t.co_pndr,t.no_pndr,t.co_dsei,t.no_dsei,
  t.co_ra_ibge,t.no_ra,
  {qs(args.competencia)}::VARCHAR AS _silver_competencia,
  current_timestamp AS _silver_built_at
FROM resolved src
LEFT JOIN read_parquet({qs(str(terr_dim))}) t ON t.co_territorio_key=src._co_territorio_key
LEFT JOIN catalog c ON c.mun6=CASE
  WHEN length(src._municipio_match_key)=7 THEN substr(src._municipio_match_key,1,6)
  ELSE src._municipio_match_key END
""",out_estab)

    marker=state/"silver_current.ok"
    marker.unlink(missing_ok=True)

    source_estab=count(estab)
    silver_estab=count(out_estab)
    dup_unidade=int(duck(f"""
SELECT count(*) FROM (
  SELECT co_unidade_key
  FROM read_parquet({qs(str(out_estab))})
  GROUP BY 1 HAVING count(*)>1
);
""",True).strip())
    dup_cnes=int(duck(f"""
SELECT count(*) FROM (
  SELECT co_cnes_key
  FROM read_parquet({qs(str(out_estab))})
  GROUP BY 1 HAVING count(*)>1
);
""",True).strip())
    unmatched=int(duck(f"""
SELECT count(*) FROM read_parquet({qs(str(out_estab))})
WHERE territory_status='unmatched';
""",True).strip())
    missing_territory_key=int(duck(f"""
SELECT count(*) FROM read_parquet({qs(str(out_estab))})
WHERE co_territorio_key IS NULL OR co_territorio_key='';
""",True).strip())
    territory_orphan=int(duck(f"""
SELECT count(*)
FROM read_parquet({qs(str(out_estab))}) e
LEFT JOIN read_parquet({qs(str(terr_dim))}) t
  ON t.co_territorio_key=e.co_territorio_key
WHERE e.co_territorio_key IS NULL
   OR e.co_territorio_key=''
   OR t.co_territorio_key IS NULL;
""",True).strip())
    df_not_ra=int(duck(f"""
SELECT count(*) FROM read_parquet({qs(str(out_estab))})
WHERE substr(co_localidade_gestor_cnes,1,2)='53'
  AND coalesce(tp_territorio_resolvido,'')<>'RA_DF';
""",True).strip())
    if (
        source_estab != silver_estab
        or dup_unidade
        or dup_cnes
        or unmatched
        or missing_territory_key
        or territory_orphan
        or df_not_ra
    ):
        die(
            f"dim_estabelecimento QC falhou source={source_estab} silver={silver_estab} "
            f"dup_unidade={dup_unidade} dup_cnes={dup_cnes} unmatched={unmatched} "
            f"missing_territory_key={missing_territory_key} territory_orphan={territory_orphan} "
            f"df_not_ra={df_not_ra}",
            30,
        )

    report=[{
        "object":"dim_estabelecimento","source":"tb_estabelecimento",
        "source_rows":source_estab,"silver_rows":silver_estab,
        "orphan_unidade":0,"status":"ok"
    }]

    for obj,src_table,cnes_col in CORE:
        src=bronze/src_table/f"competencia={args.competencia}"/"part-000.parquet"
        if not src.is_file():
            raise RuntimeError(f"fonte ausente: {src}")
        dest=silver/obj/"current.parquet"
        src_rows=count(src)

        src_cols={c.upper():c for c in columns(src)}
        extras=[]
        if "CO_PROFISSIONAL_SUS" in src_cols:
            extras.append(f"trim(cast(s.{qi(src_cols['CO_PROFISSIONAL_SUS'])} as varchar)) AS co_profissional_sus_key")
        if "CO_EQUIPE" in src_cols:
            extras.append(f"nullif(trim(cast(s.{qi(src_cols['CO_EQUIPE'])} as varchar)),'') AS co_ine_key")
        if all(k in src_cols for k in ("CO_MUNICIPIO","CO_AREA","SEQ_EQUIPE")):
            extras.append(
                "'EQUIPE_REL:' || "
                f"trim(cast(s.{qi(src_cols['CO_MUNICIPIO'])} as varchar)) || ':' || "
                f"trim(cast(s.{qi(src_cols['CO_AREA'])} as varchar)) || ':' || "
                f"trim(cast(s.{qi(src_cols['SEQ_EQUIPE'])} as varchar)) AS co_equipe_rel_key"
            )
        extras_sql=(",\n       " + ",\n       ".join(extras)) if extras else ""

        if cnes_col is None:
            copy_query(f"""
SELECT s.*{extras_sql},
       {qs(args.competencia)}::VARCHAR AS _silver_competencia,
       current_timestamp AS _silver_built_at
FROM read_parquet({qs(str(src))}) s
""",dest)
            orphan=0
        else:
            actual=require_col(src,cnes_col)
            copy_query(f"""
SELECT s.*,
       trim(cast(s.{qi(actual)} as varchar)) AS co_unidade_key,
       d.co_cnes_key{extras_sql},
       {qs(args.competencia)}::VARCHAR AS _silver_competencia,
       current_timestamp AS _silver_built_at
FROM read_parquet({qs(str(src))}) s
LEFT JOIN read_parquet({qs(str(out_estab))}) d
  ON trim(cast(s.{qi(actual)} as varchar))=d.co_unidade_key
""",dest)
            orphan=int(duck(f"""
SELECT count(*) FROM read_parquet({qs(str(dest))})
WHERE co_unidade_key IS NOT NULL AND co_unidade_key<>'' AND co_cnes_key IS NULL;
""",True).strip())

        silver_rows=count(dest)
        if src_rows != silver_rows:
            die(f"{obj}: source_rows={src_rows} silver_rows={silver_rows}",31)
        report.append({
            "object":obj,"source":src_table,
            "source_rows":src_rows,"silver_rows":silver_rows,
            "orphan_unidade":orphan,"status":"ok"
        })
        print(f"CNES_SILVER {obj} rows={silver_rows} orphan_unidade={orphan}")

    ts=subprocess.run(["date","+%Y%m%d_%H%M%S"],text=True,capture_output=True,check=True).stdout.strip()
    report_path=state/f"silver_current_{args.competencia}_{ts}.tsv"
    with report_path.open("w",encoding="utf-8",newline="") as f:
        fields=["object","source","source_rows","silver_rows","orphan_unidade","status"]
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(report)

    orphan_total=sum(int(r["orphan_unidade"]) for r in report)
    if orphan_total:
        die(
            f"Silver CNES bloqueada: orphan_unidade_total={orphan_total}; "
            f"veja {report_path}",32
        )

    marker=state/"silver_current.ok"
    marker.write_text("\n".join([
        f"competencia={args.competencia}",
        f"timestamp={ts}",
        f"zip_sha256={bmeta.get('zip_sha256','')}",
        f"territorio_snapshot={tmeta.get('territorio_snapshot','')}",
        f"objects={len(report)}",
        f"report={report_path}",
        "scope=current_core_with_team_professional_silver",
        "visibility=private_until_public_contract",
        "qc=lossless_row_count;unique_establishment_unidade_and_cnes;territory_key_not_null;territory_referential_qc;df_ra_resolved;fact_orphans_zero",
        "status=complete",
        ""
    ]),encoding="utf-8")
    print(f"CNES_SILVER_CURRENT_OK {marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
