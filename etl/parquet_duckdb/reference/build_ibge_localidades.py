#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,os,shutil,sqlite3,subprocess,sys,tempfile,zipfile
from pathlib import Path

FIELDS=["CD_UF","NM_UF","SIGLA_UF","CD_MUN","NM_MUN","CD_RGINT","NM_RGINT","CD_RGI","NM_RGI","CT_LOCALIDADE","SCT_LOCALIDADE","CD_LOCALIDADE","NM_LOCALIDADE","LAT_LOCALIDADE","LONG_LOCALIDADE"]

def die(msg:str,code:int=20):
    print(f"ERRO: {msg}",file=sys.stderr); raise SystemExit(code)
def qs(v:str)->str: return "'" + str(v).replace("'","''") + "'"
def qi(v:str)->str: return '"' + v.replace('"','""') + '"'
def duck(sql:str,capture:bool=False)->str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode:
        if p.stdout: print(p.stdout,file=sys.stderr)
        if p.stderr: print(p.stderr,file=sys.stderr)
        raise RuntimeError(f"duckdb rc={p.returncode}")
    return p.stdout if capture else ""
def read_marker(path:Path)->dict[str,str]:
    out={}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out

def main()->int:
    ap=argparse.ArgumentParser()
    ap.add_argument("--year",default=os.environ.get("IBGE_LOCALIDADES_YEAR","2022"))
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()
    if not shutil.which("duckdb"): die("duckdb CLI ausente",3)
    lake=Path(args.lake_root); state=lake/"state"/"reference"
    rm=state/f"ibge_localidades_{args.year}.raw.ok"
    if not rm.is_file(): die(f"marker Raw ausente: {rm}",4)
    meta=read_marker(rm); zp=Path(meta["path"])
    out=lake/"silver"/"reference"/"ibge_localidades"/"current.parquet"
    out.parent.mkdir(parents=True,exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="ibge_localidades_") as td0:
        td=Path(td0)
        with zipfile.ZipFile(zp) as zf:
            members=[n for n in zf.namelist() if n.lower().endswith(".gpkg")]
            if not members: die("GeoPackage ausente no ZIP",5)
            gpkg=td/Path(members[0]).name
            with zf.open(members[0]) as src, gpkg.open("wb") as dst: shutil.copyfileobj(src,dst)
        con=sqlite3.connect(str(gpkg))
        try:
            try:
                candidates=[r[0] for r in con.execute("SELECT table_name FROM gpkg_contents WHERE data_type='features'")]
            except sqlite3.DatabaseError:
                candidates=[]
            if not candidates:
                candidates=[r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'gpkg_%' AND name NOT LIKE 'rtree_%'")]
            table=None; actual={}
            for t in candidates:
                m={r[1].upper():r[1] for r in con.execute(f"PRAGMA table_info({qi(t)})")}
                if all(x in m for x in FIELDS):
                    table=t; actual=m; break
            if not table: die(f"schema GeoPackage inesperado: {candidates}",6)
            tsv=td/"localidades.tsv"
            cur=con.execute("SELECT "+", ".join(qi(actual[x]) for x in FIELDS)+f" FROM {qi(table)}")
            with tsv.open("w",encoding="utf-8",newline="") as f:
                w=csv.writer(f,delimiter="\t",lineterminator="\n"); w.writerow(FIELDS)
                while True:
                    rows=cur.fetchmany(5000)
                    if not rows: break
                    w.writerows(rows)
        finally:
            con.close()
        tmp=out.with_name(out.name+f".partial.{os.getpid()}")
        duck(f"""
COPY (
 SELECT *,
        {qs(args.year)}::VARCHAR AS _source_year,
        {qs(meta.get('sha256',''))}::VARCHAR AS _source_sha256,
        {qs(str(zp))}::VARCHAR AS _source_path,
        current_timestamp AS _built_at
 FROM read_csv({qs(str(tsv))},delim='\t',header=true,all_varchar=true,null_padding=true,parallel=false)
)
TO {qs(str(tmp))} (FORMAT PARQUET, COMPRESSION ZSTD);
""")
    stats=duck(f"""
SELECT count(*),
       count(*) FILTER (
         WHERE CD_UF='53' AND regexp_matches(CD_LOCALIDADE,'^[0-9]{{11}}$')
           AND regexp_matches(upper(strip_accents(coalesce(CT_LOCALIDADE,'') || ' ' || coalesce(SCT_LOCALIDADE,''))),'REGIAO ADMINISTRATIVA')
       )
FROM read_parquet({qs(str(tmp))});
""",True).strip()
    rows,ra_df=map(int,next(csv.reader([stats])))
    if rows<80000 or ra_df<20:
        tmp.unlink(missing_ok=True); die(f"cobertura inesperada rows={rows} ra_df={ra_df}",20)
    os.replace(tmp,out)
    marker=state/"ibge_localidades_current.ok"
    marker.write_text("\n".join([
      f"timestamp={subprocess.run(['date','+%Y%m%d_%H%M%S'],text=True,capture_output=True,check=True).stdout.strip()}",
      f"year={args.year}",f"rows={rows}",f"ra_df={ra_df}",f"path={out}",
      f"source_sha256={meta.get('sha256','')}",
      "scope=atributos_nao_geometricos_Localidades_do_Brasil",""
    ]),encoding="utf-8")
    print(f"IBGE_LOCALIDADES_SILVER_OK rows={rows} ra_df={ra_df}")
    print(f"path={out}"); print(f"marker={marker}"); return 0
if __name__=="__main__": raise SystemExit(main())
