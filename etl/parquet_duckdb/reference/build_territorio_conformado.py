#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,os,shutil,subprocess,sys
from pathlib import Path
def die(msg:str,code:int=20): print(f"ERRO: {msg}",file=sys.stderr); raise SystemExit(code)
def qs(v:str)->str: return "'" + str(v).replace("'","''") + "'"
def duck(sql:str,capture:bool=False)->str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr or p.stdout)
    return p.stdout if capture else ""
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake")); args=ap.parse_args()
    if not shutil.which("duckdb"): die("duckdb CLI ausente",3)
    lake=Path(args.lake_root); ctx=lake/"silver"/"reference"/"municipio_contexto"/"current.parquet"; ra=lake/"silver"/"reference"/"ra_df"/"current.parquet"
    out=lake/"silver"/"reference"/"dim_territorio"/"current.parquet"; state=lake/"state"/"reference"
    for p in (ctx,ra):
        if not p.is_file(): die(f"referencia ausente: {p}",4)
    out.parent.mkdir(parents=True,exist_ok=True); state.mkdir(parents=True,exist_ok=True); tmp=out.with_name(out.name+f".partial.{os.getpid()}")
    duck(f"""
COPY (
WITH brasilia AS (
 SELECT * FROM read_parquet({qs(str(ctx))}) WHERE co_municipio='530010' OR co_municipio_ibge='5300108'
 QUALIFY row_number() OVER (ORDER BY co_municipio_ibge)=1
)
SELECT 'MUN:'||co_municipio_ibge AS co_territorio_key,'MUNICIPIO'::VARCHAR AS tp_territorio,5::INTEGER AS nr_nivel_drill,NULL::VARCHAR AS co_territorio_pai_key,
       'REGIAO:'||co_regiao AS co_regiao_key,'UF:'||co_uf AS co_uf_key,
       'MACRO_SAUDE:'||co_uf||':'||co_macrorregiao_saude AS co_macrorregiao_saude_key,
       'REG_SAUDE:'||co_uf||':'||co_regiao_saude AS co_regiao_saude_key,
       'REG_SAUDE_DRILL:'||co_uf||':'||co_macrorregiao_saude||':'||co_regiao_saude AS co_regiao_saude_drill_key,
       'MUN:'||co_municipio_ibge AS co_municipio_key,NULL::VARCHAR AS co_ra_key,
       c.*,NULL::VARCHAR AS co_ra_ibge,NULL::VARCHAR AS no_ra,NULL::VARCHAR AS nu_latitude_ra,NULL::VARCHAR AS nu_longitude_ra,
       'DATASUS_BASE_TERRITORIAL_MUNICIPIO_CONTEXTO'::VARCHAR AS fonte_territorio,current_timestamp AS _territorio_built_at
FROM read_parquet({qs(str(ctx))}) c
UNION ALL
SELECT 'RA_DF:'||r.co_ra_ibge,'RA_DF'::VARCHAR,6::INTEGER,'MUN:5300108'::VARCHAR,
       'REGIAO:'||b.co_regiao,'UF:'||b.co_uf,
       'MACRO_SAUDE:'||b.co_uf||':'||b.co_macrorregiao_saude,
       'REG_SAUDE:'||b.co_uf||':'||b.co_regiao_saude,
       'REG_SAUDE_DRILL:'||b.co_uf||':'||b.co_macrorregiao_saude||':'||b.co_regiao_saude,
       'MUN:5300108'::VARCHAR,'RA_DF:'||r.co_ra_ibge,
       b.*,r.co_ra_ibge,r.no_ra,r.nu_latitude_ra,r.nu_longitude_ra,
       'IBGE_LOCALIDADES_DO_BRASIL_2022'::VARCHAR,current_timestamp
FROM read_parquet({qs(str(ra))}) r CROSS JOIN brasilia b
)
TO {qs(str(tmp))} (FORMAT PARQUET,COMPRESSION ZSTD);
""")
    stats=duck(f"SELECT count(*),count(*) FILTER (WHERE tp_territorio='MUNICIPIO'),count(*) FILTER (WHERE tp_territorio='RA_DF'),count(DISTINCT co_regiao_key) FILTER (WHERE tp_territorio='MUNICIPIO'),count(DISTINCT co_uf_key) FILTER (WHERE tp_territorio='MUNICIPIO'),count(*)-count(DISTINCT co_territorio_key),count(*) FILTER (WHERE co_territorio_key IS NULL OR co_territorio_key=''),count(*) FILTER (WHERE tp_territorio='MUNICIPIO' AND (no_regiao IS NULL OR no_regiao='')) FROM read_parquet({qs(str(tmp))});",True).strip()
    vals=list(map(int,next(csv.reader([stats])))); keys=["rows","municipios","df_ra_rows","regioes","ufs","duplicate_keys","missing_keys","missing_regiao"]; s=dict(zip(keys,vals))
    if s["municipios"]!=5571 or s["df_ra_rows"]<20 or s["regioes"]!=5 or s["ufs"]!=27 or s["duplicate_keys"] or s["missing_keys"] or s["missing_regiao"]:
        tmp.unlink(missing_ok=True); die(f"QC territorio conformado falhou: {s}",20)
    os.replace(tmp,out)
    marker=state/"territorio_conformado_current.ok"
    marker.write_text("\n".join([f"timestamp={subprocess.run(['date','+%Y%m%d_%H%M%S'],text=True,capture_output=True,check=True).stdout.strip()}",*(f"{k}={v}" for k,v in s.items()),f"path={out}","source_ra_df=IBGE_Localidades_do_Brasil_2022",
      "health_hierarchy=non_strict_canonical_region;strict_drill_path=UF+MACRO+REGIAO_SAUDE",""]))
    print("TERRITORIO_CONFORMADO "+" ".join(f"{k}={v}" for k,v in s.items())); print(f"marker={marker}"); print("TERRITORIO_CONFORMADO_OK"); return 0
if __name__=="__main__": raise SystemExit(main())
