#!/usr/bin/env python3
from __future__ import annotations
import argparse, csv, os, re, shutil, subprocess, sys
from pathlib import Path

ALIASES = {
    "co_municipio": ["COD_MUN","CO_MUNICIPIO","cod_mun","co_municipio"],
    "no_municipio": ["NOME_MUN","NO_MUNICIPIO","nome_mun","no_municipio"],
    "sg_uf": ["UF","CO_SIGLA_ESTADO","uf","co_sigla_estado"],
    "tp_capital": ["TP_CAPITAL","tp_capital"],
    "nu_latitude": ["NU_LATITUDE","nu_latitude"],
    "nu_longitude": ["NU_LONGITUDE","nu_longitude"],
    "nu_populacao_cnes": ["POPULACAO","NU_POPULACAO","populacao","nu_populacao"],
}

def die(msg, code=2):
    print("ERRO:",msg,file=sys.stderr); raise SystemExit(code)

def sqls(v): return "'" + str(v).replace("'","''") + "'"
def qi(v): return '"' + v.replace('"','""') + '"'

def duck(sql,capture=False):
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError("duckdb falhou")
    return p.stdout if capture else ""

def main():
    ap=argparse.ArgumentParser(description="Constrói referência municipal a partir do CNES Bronze")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslabx"))
    args=ap.parse_args()
    if not shutil.which("duckdb"): die("duckdb CLI ausente",3)
    lake=Path(args.lake_root)
    root=lake/"bronze"/"cnes"/"tb_municipio"
    comps=[]
    for p in root.glob("competencia=*/part-000.parquet"):
        m=re.search(r"competencia=(\d{6})",str(p))
        if m: comps.append((m.group(1),p))
    if not comps: die(f"tb_municipio Bronze ausente em {root}",4)
    comp,pq=sorted(comps)[-1]

    desc=duck(f"DESCRIBE SELECT * FROM read_parquet({sqls(pq)});",True)
    cols=[r[0] for r in csv.reader(desc.splitlines()) if r]
    lower={c.lower():c for c in cols}

    chosen={}
    for out,cands in ALIASES.items():
        for c in cands:
            if c.lower() in lower:
                chosen[out]=lower[c.lower()]
                break
    for req in ("co_municipio","no_municipio","sg_uf"):
        if req not in chosen: die(f"coluna obrigatoria ausente {req}; colunas={cols}",5)

    expr=[]
    for out in ALIASES:
        if out in chosen:
            expr.append(f"CAST({qi(chosen[out])} AS VARCHAR) AS {qi(out)}")
        else:
            expr.append(f"NULL::VARCHAR AS {qi(out)}")
    expr.append(f"{sqls(comp)}::VARCHAR AS _source_competencia_cnes")
    expr.append("current_timestamp AS _built_at")

    outdir=lake/"silver"/"reference"/"municipio"
    outdir.mkdir(parents=True,exist_ok=True)
    dest=outdir/"current.parquet"
    tmp=dest.with_name(dest.name+f".partial.{os.getpid()}")
    duck(f"""
COPY (
 SELECT {', '.join(expr)}
 FROM read_parquet({sqls(pq)})
)
TO {sqls(tmp)} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
    stats=duck(f"""
SELECT count(*), count(DISTINCT co_municipio), count(DISTINCT sg_uf)
FROM read_parquet({sqls(tmp)});
""",True).strip()
    rows,mun,ufs=map(int,next(csv.reader([stats])))
    if rows != mun: die(f"codigo municipal duplicado rows={rows} distinct={mun}",20)
    if rows < 5000 or ufs != 27: die(f"cobertura inesperada municipios={rows} ufs={ufs}",20)
    os.replace(tmp,dest)
    marker=lake/"state"/"reference"/"municipio.ok"
    marker.parent.mkdir(parents=True,exist_ok=True)
    marker.write_text(
        f"timestamp={subprocess.run(['date','-Is'],text=True,capture_output=True,check=True).stdout.strip()}\n"
        f"source_competencia_cnes={comp}\nmunicipios={rows}\nufs={ufs}\npath={dest}\n",
        encoding="utf-8")
    print(f"MUNICIPIO_REFERENCE_OK competencia_cnes={comp} municipios={rows} ufs={ufs}")
    print(f"marker={marker}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
