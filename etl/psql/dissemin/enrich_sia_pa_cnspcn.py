#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import os
import subprocess
import sys
from pathlib import Path

def die(msg: str, code: int=2):
    print(f"ERRO: {msg}",file=sys.stderr); raise SystemExit(code)

def read_tsv(path: Path):
    with path.open(encoding="utf-8",newline="") as f:
        return list(csv.DictReader(f,delimiter="\t"))

def sqls(v: str) -> str:
    return "'" + v.replace("'","''") + "'"

def plist(paths: list[Path]) -> str:
    return "[" + ",".join(sqls(str(p)) for p in paths) + "]"

def month_index(comp: str) -> int:
    return int(comp[:4])*12 + int(comp[4:6])-1

def cols(path: Path) -> set[str]:
    p=subprocess.run(
        ["duckdb","-csv","-header","-c",f"DESCRIBE SELECT * FROM read_parquet({sqls(str(path))});"],
        text=True,capture_output=True,
    )
    if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return {r["column_name"] for r in csv.DictReader(p.stdout.splitlines())}

def scalar(sql: str) -> int:
    p=subprocess.run(["duckdb","-noheader","-csv","-c",sql],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return int(p.stdout.strip() or 0)

def main() -> int:
    ap=argparse.ArgumentParser(description="Completa SIA PA CNSPCN por autorizacao em APAC, mesma UF e janela +/-3 meses")
    ap.add_argument("--profile",default="BURETA")
    ap.add_argument("--lake-root",default=os.environ.get("LAKE_ROOT","/dados/abertos/suslake"))
    ap.add_argument("--manifest",type=Path)
    ap.add_argument("--from",dest="comp_from")
    ap.add_argument("--to",dest="comp_to")
    ap.add_argument("--uf",action="append")
    ap.add_argument("--max-files",type=int,default=0)
    ap.add_argument("--execute",action="store_true")
    args=ap.parse_args()

    lake=Path(args.lake_root).resolve(); state=lake/"state"/"psql"
    manifest=args.manifest or state/f"dissemin_silver_{args.profile.lower()}.tsv"
    if not manifest.is_file(): die(f"manifest Silver ausente: {manifest}",4)

    sia=[r for r in read_tsv(manifest) if r.get("system")=="SIA" and r.get("status")=="validated"]
    wanted_uf={x.upper() for x in (args.uf or [])}
    pa=[]
    for r in sia:
        if r.get("subsystem")!="PA": continue
        comp=r.get("source_competencia",""); uf=r.get("source_uf","").upper()
        if len(comp)!=6 or not uf: continue
        if args.comp_from and comp<args.comp_from: continue
        if args.comp_to and comp>args.comp_to: continue
        if wanted_uf and uf not in wanted_uf: continue
        pa.append(r)
    pa.sort(key=lambda r:(r["source_competencia"],r["source_uf"],r["table_schema"],r["table_name"]))
    if args.max_files>0: pa=pa[:args.max_files]

    print(f"SIA_PA_CNSPCN_PLAN files={len(pa)} execute={int(args.execute)}")
    for r in pa:
        print("\t".join([r["source_competencia"],r["source_uf"],r["table_schema"],r["table_name"],r["silver_path"]]))
    if not args.execute: return 0

    apac=[r for r in sia if r.get("subsystem")!="PA" and r.get("source_competencia") and r.get("source_uf")]
    report_rows=[]

    for i,p_row in enumerate(pa,1):
        comp=p_row["source_competencia"]; uf=p_row["source_uf"].upper(); mi=month_index(comp)
        pa_path=Path(p_row["silver_path"])
        candidates=[]
        for a in apac:
            if a["source_uf"].upper()!=uf: continue
            ac=a["source_competencia"]
            if len(ac)!=6 or abs(month_index(ac)-mi)>3: continue
            p=Path(a["silver_path"])
            if p.is_file(): candidates.append(p)
        candidates=sorted(set(candidates))
        if not candidates:
            print(f"[{i}/{len(pa)}] SIA_PA_CNSPCN_SKIP no_apac uf={uf} competencia={comp}")
            continue

        pc=cols(pa_path)
        if "nu_cnspcn_original" in pc:
            original="NULLIF(TRIM(CAST(nu_cnspcn_original AS VARCHAR)),'')"
        elif "nu_cnspcn" in pc:
            original="NULLIF(TRIM(CAST(nu_cnspcn AS VARCHAR)),'')"
        else:
            original="NULL::VARCHAR"
        replace_cols=[
            x for x in (
                "nu_cnspcn","nu_cnspcn_original","nu_cnspcn_recuperado",
                "ds_origem_cnspcn","sg_subsistema_cnspcn",
                "nu_competencia_cnspcn","nu_delta_meses_cnspcn"
            ) if x in pc
        ]
        exclude=" EXCLUDE (" + ",".join(replace_cols+["__rid","__original_cnspcn"]) + ")"
        partial=pa_path.with_name(pa_path.name+f".cnspcn.partial.{os.getpid()}")

        sql=f"""
COPY (
WITH pa0 AS (
 SELECT *,row_number() OVER () AS __rid,{original} AS __original_cnspcn
 FROM read_parquet({sqls(str(pa_path))})
), ap0 AS (
 SELECT
   NULLIF(TRIM(CAST(nu_autorizacao AS VARCHAR)),'') AS auth,
   NULLIF(TRIM(CAST(nu_cnspcn AS VARCHAR)),'') AS cns,
   CAST(_source_subsystem AS VARCHAR) AS sub,
   CAST(_source_competencia AS VARCHAR) AS comp
 FROM read_parquet({plist(candidates)},union_by_name=true)
 WHERE NULLIF(TRIM(CAST(nu_autorizacao AS VARCHAR)),'') IS NOT NULL
   AND NULLIF(TRIM(CAST(nu_cnspcn AS VARCHAR)),'') IS NOT NULL
), cand AS (
 SELECT p.__rid,a.cns,a.sub,a.comp,
        abs(date_diff('month',strptime(a.comp||'01','%Y%m%d'),
                      strptime({sqls(comp)}||'01','%Y%m%d'))) AS delta
 FROM pa0 p JOIN ap0 a
   ON NULLIF(TRIM(CAST(p.nu_autorizacao AS VARCHAR)),'')=a.auth
 WHERE p.__original_cnspcn IS NULL
), mind AS (
 SELECT __rid,min(delta) AS delta FROM cand WHERE delta<=3 GROUP BY __rid
), best AS (
 SELECT c.__rid,min(c.cns) AS cns,
        string_agg(DISTINCT c.sub,'|' ORDER BY c.sub) AS sub,
        string_agg(DISTINCT c.comp,'|' ORDER BY c.comp) AS comp,
        min(c.delta) AS delta,count(DISTINCT c.cns) AS cns_distintos
 FROM cand c JOIN mind m USING(__rid)
 WHERE c.delta=m.delta
 GROUP BY c.__rid
 HAVING count(DISTINCT c.cns)=1
)
SELECT
 p.*{exclude},
 coalesce(p.__original_cnspcn,b.cns) AS nu_cnspcn,
 p.__original_cnspcn AS nu_cnspcn_original,
 CASE WHEN p.__original_cnspcn IS NULL THEN b.cns END AS nu_cnspcn_recuperado,
 CASE WHEN p.__original_cnspcn IS NOT NULL THEN 'ORIGINAL_PA'
      WHEN b.cns IS NOT NULL THEN 'APAC_AUTORIZACAO_UF_JANELA_3M'
      ELSE NULL END AS ds_origem_cnspcn,
 CASE WHEN p.__original_cnspcn IS NULL THEN b.sub END AS sg_subsistema_cnspcn,
 CASE WHEN p.__original_cnspcn IS NULL THEN b.comp END AS nu_competencia_cnspcn,
 CASE WHEN p.__original_cnspcn IS NULL THEN b.delta END AS nu_delta_meses_cnspcn
FROM pa0 p LEFT JOIN best b USING(__rid)
)
TO {sqls(str(partial))} (FORMAT PARQUET,COMPRESSION ZSTD);
"""
        proc=subprocess.run(["duckdb","-c",sql],text=True,capture_output=True)
        if proc.returncode:
            partial.unlink(missing_ok=True); raise RuntimeError(proc.stderr.strip() or proc.stdout.strip())

        before=scalar(f"SELECT count(*) FROM read_parquet({sqls(str(pa_path))})")
        after=scalar(f"SELECT count(*) FROM read_parquet({sqls(str(partial))})")
        if before!=after:
            partial.unlink(missing_ok=True)
            raise RuntimeError(f"enriquecimento alterou grain {pa_path}: before={before} after={after}")
        original_n=scalar(f"SELECT count(*) FROM read_parquet({sqls(str(partial))}) WHERE nu_cnspcn_original IS NOT NULL")
        recovered=scalar(f"SELECT count(*) FROM read_parquet({sqls(str(partial))}) WHERE nu_cnspcn_recuperado IS NOT NULL")
        remaining=scalar(f"SELECT count(*) FROM read_parquet({sqls(str(partial))}) WHERE nu_cnspcn IS NULL")
        os.replace(partial,pa_path)
        report_rows.append({
            "profile":args.profile.upper(),"uf":uf,"competencia":comp,
            "table_schema":p_row["table_schema"],"table_name":p_row["table_name"],
            "rows":str(after),"original_cnspcn":str(original_n),
            "recovered_cnspcn":str(recovered),"remaining_null":str(remaining),
            "apac_files":str(len(candidates)),"status":"validated",
        })
        print(f"[{i}/{len(pa)}] SIA_PA_CNSPCN_OK uf={uf} competencia={comp} rows={after} recovered={recovered} remaining_null={remaining}")

    report=state/f"sia_pa_cnspcn_{args.profile.lower()}.tsv"
    fields=["profile","uf","competencia","table_schema","table_name","rows",
            "original_cnspcn","recovered_cnspcn","remaining_null","apac_files","status"]
    with report.open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=fields,delimiter="\t",lineterminator="\n")
        w.writeheader(); w.writerows(report_rows)
    print(f"SIA_PA_CNSPCN_COMPLETE files={len(report_rows)} report={report}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
