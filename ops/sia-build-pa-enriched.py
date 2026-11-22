#!/usr/bin/env python3
from __future__ import annotations

import argparse, csv, os, re, subprocess
from pathlib import Path

def q(s): return "'" + str(s).replace("'","''") + "'"
def qid(s): return '"' + str(s).replace('"','""') + '"'

def scalar(sql):
    p=subprocess.run(["duckdb","-csv","-noheader","-c",sql],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr.strip() or p.stdout.strip())
    return p.stdout.strip()

def columns(path):
    p=subprocess.run(["duckdb","-csv","-c",f"DESCRIBE SELECT * FROM read_parquet({q(path)});"],text=True,capture_output=True)
    if p.returncode: raise RuntimeError(p.stderr.strip())
    return {r["column_name"].lower():r["column_name"] for r in csv.DictReader(p.stdout.splitlines())}

def ym_index(ym):
    y=int(ym[:4]); m=int(ym[4:6]); return y*12+m-1

def parse_partition(path):
    s=str(path)
    m=re.search(r"/uf=([A-Z]{2})/competencia=(\d{6})/",s,re.I)
    if not m: raise ValueError(f"particao nao reconhecida: {path}")
    return m.group(1).upper(),m.group(2)

def aux_files(root,uf,comp):
    target=ym_index(comp); out=[]
    for subdir in root.iterdir():
        if not subdir.is_dir() or subdir.name.lower()=="pa": continue
        # PS nao possui autorizacao util para esta ligacao.
        if subdir.name.lower()=="ps": continue
        u=subdir/f"uf={uf}"
        if not u.is_dir(): continue
        for cdir in u.glob("competencia=*"):
            c=cdir.name.split("=",1)[-1]
            if re.fullmatch(r"\d{6}",c) and abs(ym_index(c)-target)<=3:
                out.extend(cdir.rglob("*.parquet"))
    return sorted(out)

def sql_list(paths):
    return "["+",".join(q(str(x)) for x in paths)+"]"

def main():
    ap=argparse.ArgumentParser(description="Silver SIA PA enriquecido por CNSPCN com proveniencia")
    ap.add_argument("--lake-root",default="/dados/abertos/suslabx")
    ap.add_argument("--source",choices=["staging","bronze"],default="staging")
    ap.add_argument("--execute",action="store_true")
    ap.add_argument("--limit",type=int,default=0)
    args=ap.parse_args()

    lake=Path(args.lake_root)
    if args.source=="staging":
        src=lake/"staging"/"psql_snapshot"/"sia"
    else:
        src=lake/"bronze"/"sia"
    pa=src/"pa"
    if not pa.is_dir(): raise SystemExit(f"PA ausente: {pa}")
    files=sorted(pa.rglob("*.parquet"))
    if args.limit>0: files=files[:args.limit]
    destroot=lake/"silver"/"sia"/"pa_enriched"
    report=[]

    for i,paf in enumerate(files,1):
        uf,comp=parse_partition(paf); cols=columns(str(paf))
        auth=cols.get("pa_autoriz")
        rawcols=[cols[x] for x in ("nu_cnspcn","cnspcn") if x in cols]
        if not auth:
            print(f"[{i}/{len(files)}] SKIP sem pa_autoriz {paf}")
            report.append((str(paf),"skip_sem_pa_autoriz","","")); continue

        rawexpr="NULL"
        if rawcols:
            rawexpr="coalesce("+",".join(f"nullif(trim(cast(p.{qid(c)} as varchar)),'')" for c in rawcols)+")"

        afiles=aux_files(src,uf,comp)
        usable=[]
        for f in afiles:
            c=columns(str(f))
            if "ap_autoriz" in c and "ap_cnspcn" in c: usable.append(f)

        dest=destroot/f"uf={uf}"/f"competencia={comp}"/paf.name
        dest.parent.mkdir(parents=True,exist_ok=True)
        partial=dest.with_name(dest.name+f".partial.{os.getpid()}")

        base=f"""WITH p0 AS (
SELECT *, row_number() OVER ()::BIGINT AS __rn,
       {rawexpr} AS cnspcn_original_psql,
       nullif(trim(cast(p.{qid(auth)} as varchar)),'') AS __auth
FROM read_parquet({q(str(paf))}) p
)"""

        if usable:
            aux=sql_list(usable)
            match=f""",
a0 AS (
 SELECT nullif(trim(cast(ap_autoriz as varchar)),'') AS auth,
        nullif(trim(cast(ap_cnspcn as varchar)),'') AS cnspcn,
        cast(competencia as varchar) AS comp_aux,
        filename
 FROM read_parquet({aux},hive_partitioning=true,union_by_name=true,filename=true)
 WHERE ap_autoriz IS NOT NULL AND ap_cnspcn IS NOT NULL
),
cand AS (
 SELECT p.__rn,a.cnspcn,a.comp_aux,a.filename,
        abs(((cast(substr(a.comp_aux,1,4) as int)*12+cast(substr(a.comp_aux,5,2) as int)-1)
            -(cast(substr({q(comp)},1,4) as int)*12+cast(substr({q(comp)},5,2) as int)-1))) AS gap
 FROM p0 p JOIN a0 a ON a.auth=p.__auth
),
mingap AS (
 SELECT __rn,min(gap) gap FROM cand GROUP BY 1
),
chosen AS (
 SELECT c.__rn,
        CASE WHEN count(DISTINCT c.cnspcn)=1 THEN min(c.cnspcn) END AS cnspcn_recuperado_aux,
        CASE WHEN count(DISTINCT c.cnspcn)=1 THEN min(c.comp_aux) END AS competencia_aux,
        min(c.gap) AS gap_meses,
        count(DISTINCT c.cnspcn) AS qt_cnspcn_candidato
 FROM cand c JOIN mingap m USING(__rn)
 WHERE c.gap=m.gap
 GROUP BY c.__rn
)"""
            join="LEFT JOIN chosen c USING(__rn)"
            rec="c.cnspcn_recuperado_aux"
            gap="c.gap_meses"
            qtc="coalesce(c.qt_cnspcn_candidato,0)"
            acomp="c.competencia_aux"
        else:
            match=""
            join=""
            rec="NULL::VARCHAR"; gap="NULL::INTEGER"; qtc="0::BIGINT"; acomp="NULL::VARCHAR"

        finalraw=f"coalesce(p0.cnspcn_original_psql,{rec})"
        decoded=f"""regexp_replace(
translate({finalraw}, '{{}}~' || chr(127) || 'Çäüé|â', '0987654321'),
'[^0-9]','4','g')"""
        sql=base+match+f"""
COPY (
 SELECT p0.* EXCLUDE (__rn,__auth),
        {rec} AS cnspcn_recuperado_aux,
        {acomp} AS cnspcn_competencia_aux,
        {gap} AS cnspcn_gap_meses,
        {qtc} AS cnspcn_qt_candidatos,
        {finalraw} AS cnspcn_final,
        CASE
          WHEN p0.cnspcn_original_psql IS NOT NULL AND {rec} IS NOT NULL
               AND p0.cnspcn_original_psql <> {rec} THEN 'conflito_psql_aux'
          WHEN p0.cnspcn_original_psql IS NOT NULL THEN 'psql_preexistente'
          WHEN {rec} IS NOT NULL AND {gap}=0 THEN 'aux_mesmo_ufaamm'
          WHEN {rec} IS NOT NULL THEN 'aux_uf_autoriz_pm3'
          WHEN {qtc}>1 THEN 'aux_ambiguo'
          ELSE 'nao_recuperado' END AS tp_cnspcn_proveniencia,
        CASE WHEN {finalraw} IS NULL THEN NULL ELSE {decoded} END AS nu_cnspcn_sabeis_text,
        try_cast(CASE WHEN {finalraw} IS NULL THEN NULL ELSE {decoded} END AS BIGINT) AS nu_cnspcn_sabeis
 FROM p0 {join}
) TO {q(str(partial))} (FORMAT PARQUET,COMPRESSION ZSTD,ROW_GROUP_SIZE 122880);
"""
        if not args.execute:
            print(f"[{i}/{len(files)}] PLAN {uf} {comp} PA={paf.name} aux_files={len(usable)} -> {dest}")
            continue
        partial.unlink(missing_ok=True)
        pr=subprocess.run(["duckdb","-c",sql],text=True,capture_output=True)
        if pr.returncode:
            partial.unlink(missing_ok=True); raise RuntimeError(pr.stderr.strip() or pr.stdout.strip())
        n0=int(scalar(f"SELECT count(*) FROM read_parquet({q(str(paf))});"))
        n1=int(scalar(f"SELECT count(*) FROM read_parquet({q(str(partial))});"))
        if n0!=n1:
            partial.unlink(missing_ok=True); raise RuntimeError(f"grao alterado {paf}: {n0}!={n1}")
        os.replace(partial,dest)
        qc=scalar(f"""SELECT
count(*) FILTER (WHERE cnspcn_final IS NOT NULL),
count(*) FILTER (WHERE tp_cnspcn_proveniencia='conflito_psql_aux'),
count(*) FILTER (WHERE tp_cnspcn_proveniencia='aux_ambiguo')
FROM read_parquet({q(str(dest))});""")
        print(f"[{i}/{len(files)}] OK {uf} {comp} rows={n1} cns/conflict/ambiguous={qc}")
        report.append((str(paf),"ok",str(dest),qc))
    if args.execute:
        out=lake/"state"/"sia"/"pa_cnspcn_enrichment.tsv"; out.parent.mkdir(parents=True,exist_ok=True)
        with out.open("w",encoding="utf-8",newline="") as f:
            w=csv.writer(f,delimiter="\t",lineterminator="\n"); w.writerow(["source","status","dest","qc"]); w.writerows(report)
        print(f"SIA_PA_ENRICH_DONE files={len(report)} report={out}")
    else:
        print(f"DRY_RUN files={len(files)}")
    return 0

if __name__=="__main__":
    raise SystemExit(main())
