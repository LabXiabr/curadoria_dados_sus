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
    lake=Path(args.lake_root); src=lake/"silver"/"reference"/"ibge_localidades"/"current.parquet"
    out=lake/"silver"/"reference"/"ra_df"/"current.parquet"; state=lake/"state"/"reference"
    if not src.is_file(): die(f"IBGE Localidades ausente: {src}",4)
    out.parent.mkdir(parents=True,exist_ok=True); tmp=out.with_name(out.name+f".partial.{os.getpid()}")
    duck(f"""
COPY (
 SELECT DISTINCT trim(CD_LOCALIDADE) AS co_ra_ibge,
        trim(NM_LOCALIDADE) AS no_ra,
        upper(regexp_replace(strip_accents(trim(NM_LOCALIDADE)),'[^A-Z0-9]+','','g')) AS no_ra_norm,
        trim(CT_LOCALIDADE) AS ct_localidade,
        trim(SCT_LOCALIDADE) AS sct_localidade,
        trim(CD_MUN) AS co_municipio_ibge,
        trim(NM_MUN) AS no_municipio_ibge,
        trim(LAT_LOCALIDADE) AS nu_latitude_ra,
        trim(LONG_LOCALIDADE) AS nu_longitude_ra,
        _source_year,_source_sha256,current_timestamp AS _built_at
 FROM read_parquet({qs(str(src))})
 WHERE CD_UF='53' AND regexp_matches(CD_LOCALIDADE,'^[0-9]{{11}}$')
   AND regexp_matches(upper(strip_accents(coalesce(CT_LOCALIDADE,'') || ' ' || coalesce(SCT_LOCALIDADE,''))),'REGIAO ADMINISTRATIVA')
)
TO {qs(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
    stats=duck(f"SELECT count(*),count(DISTINCT co_ra_ibge),count(*) FILTER (WHERE co_ra_ibge IS NULL OR no_ra IS NULL OR no_ra='') FROM read_parquet({qs(str(tmp))});",True).strip()
    rows,uniq,missing=map(int,next(csv.reader([stats])))
    if rows<20 or rows!=uniq or missing:
        tmp.unlink(missing_ok=True); die(f"QC RA-DF falhou rows={rows} unique={uniq} missing={missing}",20)
    os.replace(tmp,out)
    marker=state/"ra_df_current.ok"
    marker.write_text("\n".join([
      f"timestamp={subprocess.run(['date','+%Y%m%d_%H%M%S'],text=True,capture_output=True,check=True).stdout.strip()}",
      f"rows={rows}",f"path={out}","key=RA_DF:co_ra_ibge","source=IBGE_Localidades_do_Brasil_2022",""
    ]),encoding="utf-8")
    print(f"RA_DF_OK rows={rows} path={out}"); print(f"marker={marker}"); return 0
if __name__=="__main__": raise SystemExit(main())
