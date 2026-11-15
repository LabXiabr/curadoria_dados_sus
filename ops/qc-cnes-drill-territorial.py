#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,os,shutil,subprocess,sys
from pathlib import Path
def die(msg:str,code:int=20): print(f"ERRO: {msg}",file=sys.stderr); raise SystemExit(code)
def duck(db:Path,sql:str)->str:
    p=subprocess.run(["duckdb",str(db),"-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr or p.stdout)
    return p.stdout
def main()->int:
    ap=argparse.ArgumentParser(); ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake")); ap.add_argument("--database",type=Path); args=ap.parse_args()
    if not shutil.which("duckdb"): die("duckdb CLI ausente",3)
    lake=Path(args.lake_root); db=(args.database or lake/"silver"/"suslake.duckdb").resolve(); state=lake/"state"/"cnes"
    if not db.is_file(): die(f"DuckDB ausente: {db}",4)
    sql="""WITH t AS (SELECT * FROM cnes.dim_territorio WHERE tp_territorio='MUNICIPIO'), e AS (SELECT * FROM cnes.vw_estabelecimento_drill),
rconf AS (SELECT count(*) n FROM (SELECT co_regiao_saude_key FROM t GROUP BY 1 HAVING count(DISTINCT co_macrorregiao_saude_key)>1 OR count(DISTINCT co_uf_key)>1)),
mconf AS (SELECT count(*) n FROM (SELECT co_macrorregiao_saude_key FROM t GROUP BY 1 HAVING count(DISTINCT co_uf_key)>1))
SELECT (SELECT count(*) FROM t),(SELECT count(DISTINCT co_regiao_key) FROM t),(SELECT count(DISTINCT no_regiao) FROM t),(SELECT count(DISTINCT co_uf_key) FROM t),
(SELECT count(*) FROM t WHERE co_regiao_key IS NULL OR no_regiao IS NULL OR no_regiao=''),
(SELECT count(*) FROM t WHERE co_macrorregiao_saude_key IS NULL OR no_macrorregiao_saude IS NULL OR no_macrorregiao_saude=''),
(SELECT count(*) FROM t WHERE co_regiao_saude_key IS NULL OR no_regiao_saude IS NULL OR no_regiao_saude=''),
(SELECT count(*) FROM t WHERE co_municipio_key IS NULL OR no_municipio IS NULL OR no_municipio=''),
(SELECT count(*) FROM cnes.dim_territorio WHERE tp_territorio='RA_DF'),
(SELECT count(*) FROM cnes.dim_estabelecimento),(SELECT count(*) FROM e),
(SELECT count(*) FROM e WHERE co_territorio_key IS NULL),
(SELECT count(*) FROM e WHERE co_regiao_key IS NULL OR no_regiao IS NULL OR no_regiao=''),
(SELECT count(*) FROM e WHERE sg_uf='DF' AND tp_territorio<>'RA_DF'),
(SELECT n FROM rconf),(SELECT n FROM mconf);"""
    vals=list(map(int,next(csv.reader([duck(db,sql).strip()]))))
    keys=["municipios","regioes","nomes_regioes","ufs","miss_regiao","miss_macro","miss_regsaud","miss_municipio","ra_df","estabelecimentos","drill_rows","estab_sem_territorio","estab_sem_regiao","df_estab_sem_ra","regiao_saude_conflitos","macro_saude_conflitos"]; s=dict(zip(keys,vals))
    for k,v in s.items(): print(f"{k}={v}")
    hard=s["municipios"]!=5571 or s["regioes"]!=5 or s["nomes_regioes"]!=5 or s["ufs"]!=27 or any(s[k] for k in ["miss_regiao","miss_macro","miss_regsaud","miss_municipio","estab_sem_territorio","estab_sem_regiao","df_estab_sem_ra","regiao_saude_conflitos","macro_saude_conflitos"]) or s["ra_df"]<20 or s["estabelecimentos"]!=s["drill_rows"]
    marker=state/"qc_drill_territorial_current.ok"; marker.unlink(missing_ok=True)
    if hard: print("CNES_DRILL_TERRITORIAL_QC_FAIL",file=sys.stderr); return 20
    marker.write_text("\n".join([f"timestamp={subprocess.run(['date','+%Y%m%d_%H%M%S'],text=True,capture_output=True,check=True).stdout.strip()}",*(f"{k}={v}" for k,v in s.items()),"status=validated",""]),encoding="utf-8")
    print(f"marker={marker}"); print("CNES_DRILL_TERRITORIAL_QC_OK"); return 0
if __name__=="__main__": raise SystemExit(main())
