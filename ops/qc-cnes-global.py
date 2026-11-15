#!/usr/bin/env python3
from __future__ import annotations
import argparse,csv,os,subprocess,sys
from pathlib import Path

def read_marker(path:Path)->dict[str,str]:
    out={}
    if not path.is_file(): return out
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line:
            k,v=line.split("=",1); out[k]=v
    return out
def qs(v:str)->str: return "'" + str(v).replace("'","''") + "'"
def duck(sql:str)->str:
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr or p.stdout)
    return p.stdout

def main()->int:
    ap=argparse.ArgumentParser(description="QC global CNES Silver current")
    ap.add_argument("--competencia",required=True)
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    args=ap.parse_args()
    lake=Path(args.lake_root); state=lake/"state"/"cnes"; silver=lake/"silver"/"cnes"
    required=[
      state/f"qc_bronze_{args.competencia}.ok",
      state/f"qc_unidade_{args.competencia}.ok",
      state/f"df_ra_crosswalk_{args.competencia}.ok",
      state/"silver_current.ok",
      state/"duckdb_views_current.ok",
      state/"qc_drill_territorial_current.ok",
      state/"table_classification_current.ok",
    ]
    missing=[str(p) for p in required if not p.is_file()]
    if missing:
        print("CNES_GLOBAL_QC_FAIL missing_markers="+"|".join(missing),file=sys.stderr); return 20
    sm=read_marker(state/"silver_current.ok")
    if sm.get("competencia")!=args.competencia or sm.get("status")!="complete":
        print("CNES_GLOBAL_QC_FAIL silver_marker",file=sys.stderr); return 20
    report=Path(sm["report"])
    if not report.is_file():
        print("CNES_GLOBAL_QC_FAIL silver_report",file=sys.stderr); return 20
    bad=[]
    objects=0
    with report.open(encoding="utf-8",newline="") as f:
        for r in csv.DictReader(f,delimiter="\t"):
            objects+=1
            if r["status"]!="ok" or int(r["source_rows"])!=int(r["silver_rows"]) or int(r["orphan_unidade"])!=0:
                bad.append(r["object"])
    prof=silver/"dim_profissional"/"current.parquet"
    if not prof.is_file():
        bad.append("dim_profissional_missing")
        dup_prof=-1
    else:
        dup_prof=int(duck(f"""
SELECT count(*) FROM (
 SELECT co_profissional_sus_key FROM read_parquet({qs(str(prof))})
 WHERE co_profissional_sus_key IS NOT NULL AND co_profissional_sus_key<>''
 GROUP BY 1 HAVING count(*)>1
);
""").strip())
        if dup_prof: bad.append("dim_profissional_duplicate_key")
    marker=state/f"qc_global_{args.competencia}.ok"; marker.unlink(missing_ok=True)
    if bad:
        print("CNES_GLOBAL_QC_FAIL findings="+"|".join(bad),file=sys.stderr); return 20
    marker.write_text("\n".join([
      f"competencia={args.competencia}",
      f"timestamp={subprocess.run(['date','+%Y%m%d_%H%M%S'],text=True,capture_output=True,check=True).stdout.strip()}",
      f"objects={objects}",f"duplicate_profissional_key={dup_prof}",
      "status=validated",""
    ]),encoding="utf-8")
    print(f"CNES_GLOBAL_QC_OK objects={objects} duplicate_profissional_key={dup_prof}")
    print(f"marker={marker}"); return 0
if __name__=="__main__": raise SystemExit(main())
